"""Who a sentence is for (plan.md 1, stage 2): "for me", "can you", a name or "I said..." always reach Red,
and a sentence that only sounds like dictation gets "For me?" instead of being dropped. Fakes only."""

import json

import pytest

from red import __main__ as cli
from red import conversation as conv
from red import events
from red.config import load_settings
from test_conversation_loop import Script, conv_app
from test_voice_app import world  # noqa: F401  (a fixture)

VSCODE = "plan.md - red - visual studio code code.exe"

# The requests dropped as dictation on 2026-11-14 (red.log 08:27-08:38), word for word.
DROPPED = [
    "Could you write a code for me?",
    "Write a code for me that adds 2 binary numbers in Python language",
    "I said write a code for me that adds two numbers",
    "I said write a code for me that adds two numbers in Python language",
]


@pytest.fixture(autouse=True)
def _clean_events():
    events.clear()
    yield
    events.clear()


@pytest.mark.parametrize("line", DROPPED)
def test_the_dropped_write_code_requests_reach_red(line):
    assert conv.asks_red(line)
    assert not conv.dictation_like(line, VSCODE)


@pytest.mark.parametrize("said, mine", [
    ("Can you open my downloads?", True), ("So could you check the weather", True),
    ("Make me a sandwich for me", True), ("No, I meant the other file", True),
    ("I said open YouTube", True), ("Remy, what's that song?", True),
    ("Start the next task and commit it when the tests pass", False),
    ("and now I want you to install the installer", False),
    ("When I said you're crazy, I meant the replies sound written", False),
    ("and now you can do other things in the plan", False),
])
def test_asks_red(said, mine):
    assert conv.asks_red(said, ["red", "remy", "asha"]) is mine


@pytest.mark.parametrize("said, left", [
    ("I said write a code for me that adds two numbers", "Write a code for me that adds two numbers"),
    ("No, I said, open my downloads folder", "Open my downloads folder"),
    ("I asked you to check the weather in London", "Check the weather in London"),
    ("I said hi", "I said hi"),                                   # too short to be a request of its own
    ("When I said that, I meant it", "When I said that, I meant it"),
])
def test_without_repeat(said, left):
    assert conv.without_repeat(said) == left


def test_same_request():
    assert conv.same_request("I said write a code that adds two numbers",
                             "Write a code for me that adds 2 numbers in Python language")
    assert not conv.same_request("Open my downloads", "Write a code that adds two numbers")


@pytest.mark.parametrize("said, answer", [
    ("Yes.", True), ("Yeah, it's for you.", True), ("Yes, you.", True), ("For you.", True),
    ("Go ahead.", True), ("Yes please, Red.", True),
    ("No.", False), ("Not you.", False), ("No, not for you.", False), ("Never mind.", False),
    ("Open my downloads.", None), ("Yes, and open my downloads.", None), ("", None),
])
def test_for_me_answer(said, answer):
    assert conv.for_me_answer(said) is answer


# --- in the voice loop -----------------------------------------------------------------------------------

class RecordingLLM:
    """Routes everything to talk and answers chat; records the user text of each route call."""

    def __init__(self):
        self.routed = []

    def complete_json(self, system, user, schema, **kw):
        if system.startswith("You are the intent router"):
            self.routed.append(user.rsplit("\nCommand: ", 1)[-1])
            return json.dumps({"tool": "none", "args": {"reply": "On it."}})
        return json.dumps({"reply": "On it."})


@pytest.fixture
def editor_in_front(monkeypatch):
    monkeypatch.setattr(cli, "foreground_title", lambda: VSCODE)
    monkeypatch.setattr(conv, "foreground_title", lambda: VSCODE)


def test_write_a_code_for_me_is_answered_in_conversation_mode(world, monkeypatch, editor_in_front):
    world["llm"] = RecordingLLM()
    script = Script("speech", "speech")
    app, speaker, _, _ = conv_app(world, monkeypatch, ["Could you write a code for me?", "Zip it."], script)
    app.handle("conversation")
    assert world["llm"].routed == ["Could you write a code for me?"]
    assert speaker.said and speaker.said[0] != "For me?"


def test_dictation_like_gets_for_me_and_yes_runs_it(world, monkeypatch, editor_in_front):
    world["llm"] = RecordingLLM()
    line = "Start the next task and commit it when the tests pass"
    script = Script("speech", "speech", "speech")
    app, speaker, _, _ = conv_app(world, monkeypatch, [line, "Yes.", "Zip it."], script)
    app.handle("conversation")
    assert speaker.said[0] == "For me?"                    # asked, never dropped silently
    assert world["llm"].routed == [line]                    # "yes": the held sentence ran


def test_saying_it_again_runs_it(world, monkeypatch, editor_in_front):
    world["llm"] = RecordingLLM()
    line = "Start the next task and commit it when the tests pass"
    script = Script("speech", "speech", "speech")
    app, speaker, _, _ = conv_app(world, monkeypatch, [line, line, "Zip it."], script)
    app.handle("conversation")
    assert speaker.said[0] == "For me?"
    assert world["llm"].routed == [line]


def test_no_lets_it_go_quietly(world, monkeypatch, editor_in_front):
    world["llm"] = RecordingLLM()
    line = "Start the next task and commit it when the tests pass"
    script = Script("speech", "speech", "speech")
    app, speaker, _, _ = conv_app(world, monkeypatch, [line, "No.", "Zip it."], script)
    app.handle("conversation")
    assert speaker.said == ["For me?"]
    assert world["llm"].routed == []


def test_i_said_is_taken_off_before_routing(world, monkeypatch, editor_in_front):
    world["llm"] = RecordingLLM()
    script = Script("speech", "speech")
    app, speaker, _, _ = conv_app(
        world, monkeypatch, ["I said write a code for me that adds two numbers", "Zip it."], script)
    app.handle("conversation")
    assert world["llm"].routed == ["Write a code for me that adds two numbers"]


def test_claude_comma_still_is_not_for_red_even_with_for_me(world, monkeypatch, editor_in_front):
    world["llm"] = RecordingLLM()
    script = Script("speech", "speech")
    app, speaker, _, _ = conv_app(world, monkeypatch, ["Claude, write the tests for me.", "Zip it."], script)
    app.handle("conversation")
    assert world["llm"].routed == [] and speaker.said == []
