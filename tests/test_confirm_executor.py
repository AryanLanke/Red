import json
from datetime import datetime

import pytest

from fakes import FakeAsk, FakeRunner
from red import confirm as confirm_mod
from red.confirm import confirm, is_yes, typed_ask
from red.executor import Executor
from red.router import Router
from red.tools.base import Tool, ToolError, ToolRegistry
from red.tools.system import CancelShutdown, Restart, Shutdown

NOW = datetime(2026, 11, 8, 21, 40)


# ---------- is_yes / confirm ----------

@pytest.mark.parametrize("answer", ["y", "Y", "yes", "YES", " Yes. ", "yes!", "y\n", "Yes?"])
def test_yes(answer):
    assert is_yes(answer)


@pytest.mark.parametrize("answer", [None, "", "n", "no", "yeah", "yes please", "sure",
                                    "ok", "yess", "not yes", "y y", "1"])
def test_not_yes(answer):
    assert not is_yes(answer)


def test_confirm_passes_question_and_timeout():
    ask = FakeAsk("yes")
    assert confirm("Shut down now?", ask, timeout=12) is True
    assert ask.questions == [("Shut down now?", 12)]


def test_confirm_default_timeout_is_30_seconds():
    ask = FakeAsk("y")
    confirm("Q?", ask)
    assert ask.questions[0][1] == 30.0


def test_confirm_cancels_on_timeout_no_or_error():
    assert confirm("Q?", FakeAsk(None)) is False
    assert confirm("Q?", FakeAsk("no")) is False

    def broken(q, t):
        raise RuntimeError("microphone unplugged")
    assert confirm("Q?", broken) is False


class FakeConsole:
    """Stands in for msvcrt. Keys arrive at given clock times."""

    def __init__(self, keys, pending=""):
        self.pending = list(pending)  # typed before the question
        self.keys = list(keys)        # (time, char)
        self.t = 0.0
        self.echo = []

    def clock(self):
        return self.t

    def sleep(self, s):
        self.t += s

    def kbhit(self):
        if self.pending:
            return True
        return bool(self.keys) and self.keys[0][0] <= self.t

    def getwch(self):
        if self.pending:
            return self.pending.pop(0)
        return self.keys.pop(0)[1]

    def putwch(self, c):
        self.echo.append(c)


def _read(console, timeout=30):
    return confirm_mod._console_readline(timeout, msvcrt=console, clock=console.clock,
                                         sleep=console.sleep)


def test_console_reads_a_line():
    c = FakeConsole([(1, "y"), (1, "e"), (1, "x"), (1, "\x08"), (1, "s"), (2, "\r")])
    assert _read(c) == "yes"
    assert "".join(c.echo).startswith("yex")


def test_console_times_out():
    c = FakeConsole([(31, "y"), (31, "\r")])
    assert _read(c, timeout=30) is None


def test_console_ignores_type_ahead_and_special_keys():
    c = FakeConsole([(1, "\xe0"), (1, "H"), (1, "n"), (1, "\r")], pending="y\r")
    assert _read(c) == "n"


def test_console_ctrl_c_means_no():
    assert _read(FakeConsole([(1, "y"), (1, "\x03")])) == ""


def test_typed_ask_piped_input(monkeypatch, capsys):
    import io
    monkeypatch.setattr("sys.stdin", io.StringIO("yes\n"))
    assert typed_ask("Restart now?", 30) == "yes"
    assert "Restart now? [y/N]" in capsys.readouterr().out
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    assert typed_ask("Restart now?", 30) is None


# ---------- Executor ----------

class Recorder(Tool):
    name = "recorder"
    description = "test"
    args_schema = {"type": "object", "properties": {"x": {"type": "integer"}},
                   "additionalProperties": False}

    def __init__(self, result="done", error=None):
        self.result, self.error, self.calls = result, error, []

    def run(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.result


class Dangerous(Recorder):
    name = "dangerous"
    destructive = True


def _setup(tmp_path, *tools, answers=()):
    registry = ToolRegistry(tools)
    ask = FakeAsk(*answers)
    log = tmp_path / "logs" / "commands.jsonl"
    return Router(registry), Executor(registry, ask=ask, log_path=log), ask, log


def _log_lines(log):
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]


def test_safe_tool_runs_without_asking(tmp_path):
    tool = Recorder()
    router, ex, ask, log = _setup(tmp_path, tool)
    route = router.parse('{"tool": "recorder", "args": {"x": 1}}')
    assert ex.execute("do it", route) == "done"
    assert tool.calls == [{"x": 1}] and ask.questions == []
    [entry] = _log_lines(log)
    assert entry["command"] == "do it" and entry["tool"] == "recorder"
    assert entry["args"] == {"x": 1} and entry["status"] == "ok"
    assert entry["confirmed"] is None and entry["result"] == "done"
    assert datetime.fromisoformat(entry["time"]).tzinfo is not None


@pytest.mark.parametrize("answer, ran", [("yes", True), ("Y.", True), ("no", False),
                                         ("", False), ("maybe", False), (None, False)])
def test_destructive_asks_first(tmp_path, answer, ran):
    tool = Dangerous()
    router, ex, ask, log = _setup(tmp_path, tool, answers=[answer])
    reply = ex.execute("danger", router.parse('{"tool": "dangerous", "args": {}}'))
    assert len(ask.questions) == 1
    assert ask.questions[0] == ("Dangerous?", 30.0)
    assert bool(tool.calls) is ran
    [entry] = _log_lines(log)
    assert entry["confirmed"] is ran
    if not ran:
        assert entry["status"] == "cancelled"
        assert reply == ("No answer, so I cancelled it." if answer is None else "Cancelled.")


def test_real_shutdown_confirmation_flow(tmp_path):
    runner = FakeRunner(codes={"/a": 1116})
    registry = ToolRegistry([Shutdown(runner=runner, now=lambda: NOW),
                             Restart(runner=runner, now=lambda: NOW),
                             CancelShutdown(runner=runner)])
    router = Router(registry)
    ask = FakeAsk("no", "yes")
    ex = Executor(registry, ask=ask, log_path=None, confirm_timeout=5)

    route = router.parse('{"tool": "shutdown", "args": {"minutes": 120}}')
    assert ex.execute("shut down in 2 hours", route) == "Cancelled."
    assert runner.calls == []                                   # "no" ran nothing
    reply = ex.execute("shut down in 2 hours", route)
    assert ask.questions == [("Shut down in 2 hours (at 11:40 PM)?", 5)] * 2
    assert "11:40 PM" in reply
    assert runner.flags == [["/a"], ["/s", "/t", "7200"]]

    cancel = router.parse('{"tool": "cancel_shutdown", "args": {}}')
    ex.execute("cancel the shutdown", cancel)
    assert len(ask.questions) == 2                              # cancel never asks
    assert runner.flags[-1] == ["/a"]


def test_tool_errors_become_replies(tmp_path):
    for err, expected in [(ToolError("No such folder."), "No such folder."),
                          (RuntimeError("kaboom"), "Sorry, recorder failed: kaboom")]:
        router, ex, _, log = _setup(tmp_path, Recorder(error=err))
        assert ex.execute("x", router.parse('{"tool": "recorder", "args": {}}')) == expected
        entry = _log_lines(log)[-1]
        assert entry["status"] == "error" and entry["result"] == expected
    assert "RuntimeError" in entry["error"]


def test_none_route_returns_its_reply(tmp_path):
    router, ex, ask, log = _setup(tmp_path, Recorder())
    assert ex.execute("banana", router.parse('{"tool": "none", "args": {"reply": "Which one?"}}')) \
        == "Which one?"
    assert _log_lines(log)[0]["status"] == "none"


def test_describe_failure_still_asks(tmp_path):
    class BadDescribe(Dangerous):
        def describe(self, **kwargs):
            raise ValueError("oops")
    tool = BadDescribe()
    router, ex, ask, _ = _setup(tmp_path, tool, answers=["n"])
    assert ex.execute("x", router.parse('{"tool": "dangerous", "args": {}}')) == "Cancelled."
    assert "dangerous" in ask.questions[0][0] and tool.calls == []


def test_unwritable_log_does_not_crash(tmp_path):
    registry = ToolRegistry([Recorder()])
    blocker = tmp_path / "file"
    blocker.write_text("x")
    ex = Executor(registry, ask=FakeAsk(), log_path=blocker / "commands.jsonl")
    assert ex.execute("x", Router(registry).parse('{"tool": "recorder", "args": {}}')) == "done"


def test_no_log_path_writes_nothing(tmp_path):
    registry = ToolRegistry([Recorder()])
    Executor(registry, ask=FakeAsk()).execute(
        "x", Router(registry).parse('{"tool": "recorder", "args": {}}'))
    assert list(tmp_path.iterdir()) == []
