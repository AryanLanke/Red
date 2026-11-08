"""Routes real typed commands for the Track G tools through the local model,
with every tool registered. Nothing is executed: only the chosen call is checked.

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


def norm(value):
    return " ".join(value.lower().split()) if isinstance(value, str) else value


def has(**expected):
    def check(args):
        return all(norm(args.get(k)) == norm(v) for k, v in expected.items())
    check.__name__ = f"has({expected})"
    return check


def contains(key, *words):
    def check(args):
        return all(w in norm(args.get(key, "")) for w in words)
    check.__name__ = f"contains({key}, {words})"
    return check


def timer_seconds(total):
    def check(args):
        return args.get("minutes", 0) * 60 + args.get("seconds", 0) == total
    check.__name__ = f"timer_seconds({total})"
    return check


ANY = None

CASES = [
    # timers and reminders
    ("set a timer for 10 minutes", "set_timer", timer_seconds(600)),
    ("timer for 30 seconds", "set_timer", timer_seconds(30)),
    ("set a pasta timer for 12 minutes", "set_timer", timer_seconds(720)),
    ("set a timer for 2 hours", "set_timer", timer_seconds(7200)),
    ("remind me at 3 pm to call mom", "set_reminder",
     lambda a: a.get("time") == "15:00" and "call mom" in norm(a.get("text"))),
    ("remind me in 20 minutes to check the oven", "set_reminder", has(in_minutes=20)),
    ("remind me tomorrow at 9 am to submit the report", "set_reminder",
     lambda a: a.get("time") == "09:00" and a.get("day") == "tomorrow"),
    ("what reminders do I have", "list_reminders", ANY),
    ("cancel the timer", "cancel_reminder", contains("which", "timer")),
    ("cancel my reminder to call mom", "cancel_reminder", contains("which", "call mom")),
    ("cancel the shutdown", "cancel_shutdown", ANY),
    ("shut down in 10 minutes", "shutdown", has(minutes=10)),
    # offline answers
    ("what is hugging face", "answer", contains("question", "hugging face")),
    ("explain recursion", "answer", contains("question", "recursion")),
    ("who was alan turing", "answer", contains("question", "turing")),
    ("how tall is mount everest", "answer", contains("question", "everest")),
    ("search the web for hugging face", "web_search", contains("query", "hugging face")),
    ("google recursion", "web_search", contains("query", "recursion")),
    ("banana", "none", ANY),
]


@pytest.mark.parametrize("command, tool, check", CASES)
def test_routes(router, command, tool, check):
    route = router.route(command)
    assert route.tool in ((tool,) if isinstance(tool, str) else tool), route
    if check is not None:
        assert check(route.args), (getattr(check, "__name__", "check"), route)


def test_answer_end_to_end(router):
    """The answer tool, bound to the router's model, gives a short spoken answer."""
    reply = router.registry.get("answer").run(question="what is recursion in programming")
    assert 20 < len(reply) <= 700
    assert "function" in reply.lower() or "itself" in reply.lower()
