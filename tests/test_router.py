import json

import pytest

from red.router import RouteError, Router
from red.tools import default_registry
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
    r = Router(default_registry(), llm)
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
