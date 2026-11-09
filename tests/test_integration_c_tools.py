"""Routes real typed commands for the Track C tools through the local model,
and re-checks the existing tools with the Track C tools registered.

Slow and needs the model, so it only runs with RED_INTEGRATION=1. Nothing is
executed: these tests only check the tool call the model picks.
"""

import os

import pytest

from red.config import load_settings
from red.llm import connect
from red.router import Router
from red.tools import default_registry
from red.tools.git_sync import means_all_repos
from red.tools.youtube import ANYTHING_QUERY, search_words

ALL = object()   # "the tool will play a mix / check every repo"

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(os.environ.get("RED_INTEGRATION") != "1",
                       reason="set RED_INTEGRATION=1 to run"),
]


@pytest.fixture(scope="module")
def router():
    llm, server = connect(load_settings())
    yield Router(default_registry(), llm)
    if server:
        server.stop()


def _norm(text):
    return " ".join(text.lower().replace("-", " ").split())


def _check_args(tool, got, expected):
    """Compare by what the tool will do, not by the model's exact wording."""
    if tool == "play_online":
        query = search_words(got.get("query", ""))
        if expected is ALL:
            return query == ANYTHING_QUERY or "music" in query.lower() or "song" in query.lower()
        return all(w in query.lower() for w in expected["query"].split())
    if tool == "check_repos":
        if expected is ALL:
            return means_all_repos(got.get("repo"))
        return _norm(got.get("repo", "")) == expected["repo"]
    norm = lambda d: {k: _norm(v) if isinstance(v, str) else v for k, v in d.items()}  # noqa: E731
    return norm(got) == norm(expected)


# (command, tool, expected args or None to skip the args check)
NEW_TOOLS = [
    ("play some music", "play_online", ALL),
    ("play music", "play_online", ALL),
    ("shuffle my songs", "play_online", ALL),
    ("play anything", "play_online", ALL),
    ("check all my repositories", "check_repos", ALL),
    ("play daft punk", "play_online", {"query": "daft punk"}),
    ("play the song bohemian rhapsody", "play_online", {"query": "bohemian rhapsody"}),
    ("put on some jazz", "play_online", {"query": "jazz"}),
    ("stop the music", "stop_music", {}),
    ("stop playing music", "stop_music", {}),
    ("pause the music", "pause_music", {}),
    ("resume the music", "resume_music", {}),
    ("next song", "next_song", {}),
    ("skip this song", "next_song", {}),
    ("check my repos", "check_repos", ALL),
    ("are my git repos pushed", "check_repos", ALL),
    ("do I have any unpushed commits", "check_repos", ALL),
    ("check if the red repo is in sync with github", "check_repos", {"repo": "red"}),
]

# The same commands as tests/test_integration_llm.py (Track A owns that file).
EXISTING_TOOLS = [
    ("open Downloads", "open_folder", {"folder": "Downloads"}),
    ("open my documents folder", "open_folder", {"folder": "Documents"}),
    ("open my music folder", "open_folder", {"folder": "Music"}),
    ("shut down the computer in 3 hours", "shutdown", {"minutes": 180}),
    ("restart in 10 minutes", "restart", {"minutes": 10}),
    ("cancel the shutdown", "cancel_shutdown", {}),
    ("stop the shutdown", "cancel_shutdown", {}),
    ("open notepad", "open_app", None),
    ("open youtube", "open_url", None),
    ("open github", "open_url", None),
]


@pytest.mark.parametrize("command, tool, args", NEW_TOOLS + EXISTING_TOOLS)
def test_routes(router, command, tool, args):
    route = router.route(command)
    assert route.tool == tool, route
    if args is not None:
        assert _check_args(tool, route.args, args), route


def test_unclear_command_uses_none(router):
    assert router.route("banana").is_none
