"""Track C tools are registered and route through Router.parse()."""

import json

import pytest

from red.router import Router, RouteError
from red.tools import default_registry

C_TOOLS = ("play_online", "stop_music", "pause_music", "resume_music", "next_song",
           "check_repos")


def test_track_c_tools_registered():
    reg = default_registry()
    for name in C_TOOLS:
        assert name in reg
    for name in ("open_folder", "open_app", "open_url", "shutdown", "restart",
                 "cancel_shutdown"):
        assert name in reg


def test_there_is_no_local_music_player():
    # Every "play ..." goes online (plan.md task 3, second plan).
    assert "play_music" not in default_registry()


@pytest.fixture
def router():
    return Router(default_registry())


@pytest.mark.parametrize("raw, tool, args", [
    ({"tool": "play_online", "args": {"query": "daft punk"}}, "play_online", {"query": "daft punk"}),
    ({"tool": "stop_music", "args": {}}, "stop_music", {}),
    ({"tool": "next_song", "args": {}}, "next_song", {}),
    ({"tool": "check_repos", "args": {}}, "check_repos", {}),
    ({"tool": "check_repos", "args": {"repo": "red"}}, "check_repos", {"repo": "red"}),
])
def test_parse_valid(router, raw, tool, args):
    route = router.parse(json.dumps(raw))
    assert (route.tool, route.args, route.destructive) == (tool, args, False)


@pytest.mark.parametrize("raw", [
    {"tool": "play_music", "args": {"query": "daft punk"}},
    {"tool": "play_online", "args": {"query": ""}},
    {"tool": "play_online", "args": {"query": "x" * 151}},
    {"tool": "play_online", "args": {"query": "x", "path": "C:\\Windows"}},
    {"tool": "stop_music", "args": {"now": True}},
    {"tool": "check_repos", "args": {"repo": "x" * 101}},
    {"tool": "check_repos", "args": {"path": "D:\\"}},
])
def test_parse_rejects_bad_args(router, raw):
    with pytest.raises(RouteError):
        router.parse(json.dumps(raw))


def test_descriptions_are_in_the_prompt(router):
    for name in C_TOOLS:
        assert f"- {name}: " in router.system_prompt
