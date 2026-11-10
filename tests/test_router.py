import json

import pytest

from red.router import RouteError, Router
from red.tools import ToolRegistry, default_registry
from red.tools.web import OpenUrl
from red.tools.base import Tool, ToolRegistry


class FakeLLM:
    def __init__(self, reply: str):
        self.reply = reply
        self.calls = []

    def complete_json(self, system, user, schema):
        self.calls.append((system, user, schema))
        return self.reply


@pytest.fixture
def router():
    return Router(default_registry())


def call(tool, **args):
    return json.dumps({"tool": tool, "args": args})


def test_valid_open_folder(router):
    route = router.parse(call("open_folder", folder="Downloads"))
    assert route.tool == "open_folder"
    assert route.args == {"folder": "Downloads"}
    assert not route.destructive


def test_shutdown_is_destructive(router):
    route = router.parse(call("shutdown", minutes=180))
    assert route.args == {"minutes": 180}
    assert route.destructive


def test_none_tool(router):
    route = router.parse(call("none", reply="Which folder?"))
    assert route.is_none
    assert not route.destructive


@pytest.mark.parametrize("raw", [
    "", "not json", "[]", '"text"', '{"args": {}}', '{"tool": 5, "args": {}}',
])
def test_malformed_replies_rejected(router, raw):
    with pytest.raises(RouteError):
        router.parse(raw)


@pytest.mark.parametrize("raw", [
    call("delete_everything"),                       # unknown tool
    call("shutdown", minutes=-1),                    # below range
    call("shutdown", minutes=5000),                  # above 24 hours
    call("shutdown", minutes="soon"),                # wrong type
    call("shutdown"),                                # missing arg
    call("shutdown", minutes=5, force=True),         # extra arg
    call("open_url", url="javascript:alert(1)"),     # not http(s)
    call("open_folder", folder=""),                  # empty
    call("cancel_shutdown", now=True),               # takes no args
    '{"tool": "open_folder", "args": {"folder": "x"}, "extra": 1}',
])
def test_invalid_calls_rejected(router, raw):
    with pytest.raises(RouteError):
        router.parse(raw)


def test_schema_covers_every_tool(router):
    names = {opt["properties"]["tool"]["const"] for opt in router.schema["anyOf"]}
    assert names == {t.name for t in default_registry()} | {"none"}


def test_prompt_lists_every_tool(router):
    for tool in default_registry():
        assert tool.name in router.system_prompt


def test_route_passes_schema_to_llm():
    llm = FakeLLM(call("open_folder", folder="Downloads"))
    r = Router(default_registry(), llm, fast=None)       # the model's path
    route = r.route("  open downloads  ")
    assert route.tool == "open_folder"
    system, user, schema = llm.calls[0]
    assert user == "open downloads"
    assert schema is r.schema


def test_empty_command_rejected():
    with pytest.raises(RouteError):
        Router(default_registry(), FakeLLM("{}")).route("   ")


class _Dummy(Tool):
    name = "dummy"
    description = "test"
    args_schema = {"type": "object"}

    def run(self, **kwargs):
        return "ok"


def test_registry_rejects_duplicates_and_reserved_name():
    reg = ToolRegistry([_Dummy()])
    with pytest.raises(ValueError):
        reg.add(_Dummy())

    class _None(_Dummy):
        name = "none"

    with pytest.raises(ValueError):
        reg.add(_None())


def test_junk_after_a_complete_call_is_ignored():
    # Qwen3.5 on Ollama once kept writing after the call (2026-11-09 benchmark).
    router = Router(ToolRegistry([OpenUrl(open_browser=lambda url: True)]))
    raw = '{"tool": "open_url", "args": {"url": "https://www.youtube.com"}}\n```json\n{"tool":\n```json\n{"'
    route = router.parse(raw)
    assert (route.tool, route.args) == ("open_url", {"url": "https://www.youtube.com"})


def test_junk_before_the_call_is_still_refused():
    router = Router(ToolRegistry([OpenUrl(open_browser=lambda url: True)]))
    with pytest.raises(RouteError):
        router.parse('Sure! {"tool": "open_url", "args": {"url": "https://www.youtube.com"}}')


# --- several commands in one sentence (plan.md task 9) ----------------------------------

from red.router import split_commands  # noqa: E402


@pytest.mark.parametrize("said, parts", [
    ("Open Chrome and search flights to Delhi", ["Open Chrome", "search flights to Delhi"]),
    ("mute and lock the PC", ["mute", "lock the PC"]),
    ("check my mail and read today's calendar", ["check my mail", "read today's calendar"]),
    ("find my resume and open it", ["find my resume", "open it"]),
    ("open YouTube, then play Believer", ["open YouTube", "play Believer"]),
    ("search for cats and dogs", ["search for cats and dogs"]),
    ("play rock and roll", ["play rock and roll"]),
    ("search online for the mars rover and tell me about it",
     ["search online for the mars rover and tell me about it"]),
    ("turn the volume up and down", ["turn the volume up and down"]),
    ("I went home and then I slept", ["I went home and then I slept"]),
    ("mute and lock and open youtube and play x and pause", ["mute and lock and open youtube and play x and pause"]),
])
def test_split_commands(said, parts):
    assert split_commands(said) == parts


class ByCommand:
    """A model that answers by the command it's given."""

    def __init__(self, calls):
        self.calls, self.asked = calls, []

    def complete_json(self, system, user, schema, **kw):
        said = user.rsplit("Command: ", 1)[-1]
        self.asked.append(said)
        return self.calls.get(said, call("none", reply="Hm?"))


def test_route_many_routes_each_part():
    llm = ByCommand({"read today's calendar": call("tell_status", what="date")})
    router = Router(default_registry(), llm)
    steps = router.route_many("Open Chrome and search flights to Delhi")
    assert [(p, r.tool) for p, r in steps] == [("Open Chrome", "open_app"), ("search flights to Delhi", "web_search")]
    assert llm.asked == []                                      # both took the fast path
    steps = router.route_many("mute and read today's calendar")
    assert [r.tool for _, r in steps] == ["volume", "tell_status"]
    assert llm.asked == ["read today's calendar"]               # only the unclear part asked the model


def test_a_part_that_is_chat_means_the_sentence_is_one_command():
    llm = ByCommand({"open the door": call("none", reply="Hm?"),
                     "I want to open the door and open my heart": call("none", reply="That's sweet.")})
    steps = Router(default_registry(), llm, fast=None).route_many("I want to open the door and open my heart")
    assert len(steps) == 1 and steps[0][1].is_none


# --- a debate, a quiz, a discussion: Chat, not one answer (Task 5) ---------------------

from red.router import is_multi_turn  # noqa: E402


@pytest.mark.parametrize("said", [
    "Let's have a debate about AI regulation",
    "debate me on tabs versus spaces",
    "argue about pineapple on pizza",
    "let's discuss AI safety",
    "Quiz me on capitals",
    "let's go back and forth on this",
])
def test_multi_turn_requests_go_to_chat_without_the_model(said):
    llm = FakeLLM(call("open_folder", folder="Downloads"))
    route = Router(default_registry(), llm).route(said)
    assert route.is_none
    assert llm.calls == []                     # never a one-shot answer
    assert route.args["reply"] == "Let's get into it."


@pytest.mark.parametrize("said", [
    "open YouTube", "stop", "play Believer", "how are you", "set a timer for 5 minutes",
])
def test_ordinary_commands_are_not_multi_turn(said):
    assert not is_multi_turn(said)


def test_a_multi_turn_request_beats_the_fast_path():
    route = Router(default_registry()).route("Quiz me: capital of France")
    assert route.is_none


def test_a_question_about_a_debate_is_still_chat():
    # Route checks the words, not intent: this must never become a tool call.
    assert Router(default_registry(), FakeLLM(call("open_url", url="https://x.example"))).route(
        "I watched a debate about the moon landing").is_none
