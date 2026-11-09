"""Routes "play ..." commands through the real local model: every one goes to
play_online, songs too (there's no local music). Nothing is executed.

Slow and needs the model, so it only runs with RED_INTEGRATION=1.
"""

import os

import pytest

from red.config import load_settings
from red.llm import connect
from red.router import Router
from red.tools import default_registry

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


def query_has(*words):
    def check(args):
        q = " ".join(str(args.get("query", "")).lower().split())
        return all(w in q for w in words)
    check.__name__ = f"query_has{words}"
    return check


CASES = [
    ("play a podcast about loneliness", "play_online", query_has("podcast", "loneliness")),
    ("play Punisher trailer", "play_online", query_has("punisher", "trailer")),
    ("play lofi on YouTube", "play_online", query_has("lofi")),
    ("play the new MrBeast video", "play_online", query_has("mrbeast")),
    ("put on a TED talk about sleep", "play_online", query_has("sleep")),
    # Said in the 2026-11-08 voice test (22:24 and 22:26):
    ("Can you open a podcast to me that will make my loneliness go away?", "play_online",
     query_has("podcast")),
    ("Can you just open a podcast for me from this screen? I don't wanna watch this song. "
     "A podcast that will make my loneliness go away.", "play_online", query_has("podcast")),
    # Songs and artists go online too (plan.md task 3, second plan).
    ("play Believer", "play_online", query_has("believer")),
    ("play some Arijit Singh", "play_online", query_has("arijit")),
    ("play daft punk", "play_online", query_has("daft punk")),
    ("shuffle my songs", "play_online", None),
]


def test_play_music_is_gone(router):
    assert "play_music" not in router.registry


@pytest.mark.parametrize("command, tool, check", CASES)
def test_routes(router, command, tool, check):
    route = router.route(command)
    assert route.tool in ((tool,) if isinstance(tool, str) else tool), route
    if check is not None:
        assert check(route.args), (check.__name__, route)
