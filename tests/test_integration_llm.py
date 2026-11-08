"""Routes real typed commands through the local model.

Slow and needs the model downloaded, so it only runs with RED_INTEGRATION=1.
"""

import os
import sys
from datetime import datetime

import pytest

sys.path.insert(0, os.path.dirname(__file__))
from fakes import FakeAsk, FakeRunner  # noqa: E402

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
