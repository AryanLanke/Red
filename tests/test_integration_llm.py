"""Routes real typed commands through the local model.

Slow and needs the model downloaded, so it only runs with RED_INTEGRATION=1.
"""

import os
import sys
from datetime import datetime

import pytest

sys.path.insert(0, os.path.dirname(__file__))
from fakes import FakeAsk, FakeRunner  # noqa: E402

from red.browser import from_words  # noqa: E402
from red.config import load_settings  # noqa: E402
from red.executor import Executor  # noqa: E402
from red.llm import connect  # noqa: E402
from red.router import Router  # noqa: E402
from red.tools import default_registry  # noqa: E402
from red.tools.base import ToolRegistry  # noqa: E402
from red.tools.system import CancelShutdown, Restart, Shutdown  # noqa: E402

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(os.environ.get("RED_INTEGRATION") != "1",
                       reason="set RED_INTEGRATION=1 to run"),
]


@pytest.fixture(scope="module")
def llm():
    llm, server = connect(load_settings())
    yield llm
    if server:
        server.stop()


@pytest.fixture(scope="module")
def router(llm):
    return Router(default_registry(), llm)


@pytest.mark.parametrize("command, tool, args", [
    ("open Downloads", "open_folder", {"folder": "Downloads"}),
    ("open my documents folder", "open_folder", {"folder": "Documents"}),
    ("shut down the computer in 3 hours", "shutdown", {"minutes": 180}),
    ("restart in 10 minutes", "restart", {"minutes": 10}),
    ("cancel the shutdown", "cancel_shutdown", {}),
    ("cancel the restart", "cancel_shutdown", {}),
    ("restart the computer now", "restart", {"minutes": 0}),
    ("open the calculator", "open_app", None),
    ("open https://github.com", "open_url", {"url": "https://github.com"}),
    ("open notepad", "open_app", None),
    ("open youtube", "open_url", None),
])
def test_routes(router, command, tool, args):
    route = router.route(command)
    assert route.tool == tool, route
    if args is not None:
        assert route.args == args


# The user's words from the 23:37 voice test (commands.jsonl), and naming a browser.
@pytest.mark.parametrize("command, browser", [
    ("Open YouTube.", None),
    ("open YouTube", None),
    ("open YouTube from Chrome", "chrome"),
    ("Can you open YouTube for me from Chrome?", "chrome"),
    ("open YouTube in Edge", "edge"),
    ("Red you just open chrome. I told you to open YouTube", ...),   # either is fine
])
def test_open_youtube_and_the_browser(router, command, browser):
    route = router.route(command)
    assert route.tool == "open_url", route
    assert "youtube.com" in route.args["url"], route
    if browser is not ...:
        # What the tool will use: the model's pick only if the user named it.
        assert from_words(command, route.args.get("browser")) == browser, route


@pytest.mark.parametrize("command, browser", [
    ("search lofi in Edge", "edge"),
    ("search the web for lofi beats in Chrome", "chrome"),
    ("search the web for lofi beats", None),
])
def test_search_in_a_named_browser(router, command, browser):
    route = router.route(command)
    if route.tool == "open_url":
        # A search page through open_url opens the same results (as in test_integration_f_tools).
        url = route.args["url"].lower()
        assert ("search" in url or "results" in url) and "lofi" in url, route
    else:
        assert route.tool == "web_search", route
        query = route.args["query"].lower()
        assert "lofi" in query and "edge" not in query and "chrome" not in query, route
    assert from_words(command, route.args.get("browser")) == browser, route


COMPARE_2341 = ("Can you compare Hey Copilot with Hey Siri and then Ok Google and just tell me "
                "which one is better at what. I heard that Hey Copilot is for Windows only and what "
                "they are good at. Can you tell me those things?")


def test_the_2341_comparison_looks_the_assistants_up(router):
    """plan.md task 2c: recent products go to look_up, all three of them."""
    route = router.route(COMPARE_2341)
    assert route.tool == "look_up", route
    named = " ".join([route.args["topic"], *route.args.get("others", [])]).lower()
    assert "copilot" in named and "siri" in named and "google" in named, route


def test_an_unknown_name_is_not_made_up(llm):
    """plan.md task 2c: the answer says it doesn't know, instead of inventing."""
    from red.tools.assistant import Answer
    tool = Answer(llm)
    tool.set_command("What is Hey CD?")
    reply = tool.run(question="Hey CD is a voice assistant for Windows and macOS")
    assert "know" in reply.lower(), reply
    assert "macos" not in reply.lower(), reply


def test_read_my_screen_from_the_log(router):
    """22:25 and the plan's task 4 list: it went to none once."""
    assert router.route("Can you just read my screen? What's going on?").tool == "describe_screen"


def test_unclear_command_uses_none(router):
    route = router.route("banana")
    assert route.is_none


def test_destructive_command_asks_before_running(llm):
    """Real model, fake shutdown.exe: "no" runs nothing, "yes" schedules it."""
    runner = FakeRunner(codes={"/a": 1116})
    now = lambda: datetime(2026, 11, 8, 21, 40)  # noqa: E731
    registry = ToolRegistry([Shutdown(runner=runner, now=now), Restart(runner=runner, now=now),
                             CancelShutdown(runner=runner)])
    router = Router(registry, llm)
    ask = FakeAsk("no", "yes")
    executor = Executor(registry, ask=ask)

    command = "shut down in 2 hours"
    assert executor.execute(command, router.route(command)) == "Cancelled."
    assert runner.calls == []
    reply = executor.execute(command, router.route(command))
    assert [q for q, _ in ask.questions] == ["Shut down in 2 hours (at 11:40 PM)?"] * 2
    assert "11:40 PM" in reply
    assert runner.flags == [["/a"], ["/s", "/t", "7200"]]


# --- several commands in one sentence (plan.md task 9) ----------------------------------

@pytest.mark.parametrize("command, tools", [
    ("Open Chrome and search flights to Delhi", ["open_app", "web_search"]),
    ("mute and lock the PC", ["volume", "lock_pc"]),
    ("open my downloads folder and then play Believer", ["open_folder", "play_online"]),
    ("set a timer for 5 minutes and remind me to call mom at 6 pm", ["set_timer", "set_reminder"]),
    ("search for cats and dogs", ["web_search"]),
    ("search online for the mars rover and tell me about it", ["look_up"]),
])
def test_several_commands(router, command, tools):
    steps = router.route_many(command)
    assert [r.tool for _, r in steps] == tools, steps


def test_several_commands_with_mail_and_calendar(llm):
    from red.tools import default_registry as registry
    steps = Router(registry(google=True), llm).route_many("check my mail and read today's calendar")
    assert [r.tool for _, r in steps] == ["check_mail", "calendar_events"], steps
