"""Routes real typed commands for the Track F tools through the local model,
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
    return " ".join(str(value).lower().replace("-", " ").split()) if isinstance(value, str) \
        else value


def has(**expected):
    """Check only the named args, ignoring case and spacing."""
    def check(args):
        return all(norm(args.get(k)) == norm(v) for k, v in expected.items())
    check.__name__ = f"has({expected})"
    return check


def contains(key, *words):
    def check(args):
        return all(w in norm(args.get(key, "")) for w in words)
    check.__name__ = f"contains({key}, {words})"
    return check


ANY = None

CASES = [
    # Office apps (open_app with App Paths)
    ("open powerpoint", "open_app", has(app="powerpoint")),
    ("open ppt", "open_app", ANY),
    ("open word", "open_app", has(app="word")),
    ("launch excel", "open_app", has(app="excel")),
    ("open outlook", "open_app", has(app="outlook")),
    # web_search
    ("search the web for best laptops 2026", "web_search", contains("query", "best laptops")),
    ("google how to boil an egg", "web_search", contains("query", "boil", "egg")),
    ("search youtube for lofi music", "web_search", has(site="youtube")),
    ("look up the weather in Pune", "web_search", contains("query", "weather", "pune")),
    ("show me pictures of cats", "web_search", has(site="images")),
    ("open youtube", "open_url", ANY),
]


@pytest.mark.parametrize("command, tool, check", CASES)
def test_routes(router, command, tool, check):
    route = router.route(command)
    assert route.tool == tool, route
    if check is not None:
        assert check(route.args), (check.__name__, route)
