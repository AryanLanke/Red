"""Real-model routing for chat, screen questions and "can you ...?" (RED_INTEGRATION=1)."""

import os

import pytest

from red.config import load_settings
from red.llm import connect
from red.router import Router
from red.tools import default_registry

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(os.environ.get("RED_INTEGRATION") != "1", reason="set RED_INTEGRATION=1 to run"),
]


@pytest.fixture(scope="module")
def router():
    llm, server = connect(load_settings())
    yield Router(default_registry(), llm)
    if server:
        server.stop()


@pytest.mark.parametrize("said", [
    "What's going on in your mind right now?",
    "I had a really bad day at college today.",
    "How are you?",
    "Tell me something about yourself",
])
def test_chat_goes_to_the_conversation(router, said):
    assert router.route(said).tool == "none"


@pytest.mark.parametrize("said", [
    "What's going on on my screen right now?",
    "What am I doing right now?",
    "Can you read my screen?",
])
def test_screen_questions(router, said):
    assert router.route(said).tool == "describe_screen"


def test_the_shutdown_question_routes_to_shutdown(router):
    # Red then asks once, "Shut down in 3 hours (at ...)?", because shutdown is risky.
    route = router.route("Can you help me with turning off my laptop after 3 hours?")
    assert (route.tool, route.args) == ("shutdown", {"minutes": 180})
    assert route.destructive
