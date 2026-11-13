"""Hidden background Red: start, stop and status, with fake processes."""

from types import SimpleNamespace

import pytest

from red import background as bg


class Runner:
    def __init__(self, alive=()):
        self.alive, self.calls = set(alive), []

    def __call__(self, cmd, **kw):
        self.calls.append(cmd)
        if cmd[0] == "tasklist":
            pid = int(cmd[2].split()[-1])
            out = f'"pythonw.exe","{pid}","Console","1","9,000 K"' if pid in self.alive else "INFO: No tasks"
            return SimpleNamespace(stdout=out, returncode=0)
        if cmd[0] == "taskkill":
            self.alive.discard(int(cmd[2]))
        return SimpleNamespace(stdout="", returncode=0)


class Popen:
    instances = []

    def __init__(self, cmd, **kw):
        self.cmd, self.kw, self.pid = cmd, kw, 4242
        Popen.instances.append(self)


@pytest.fixture(autouse=True)
def fresh():
    Popen.instances = []


def test_start_launches_a_hidden_red_and_remembers_it(tmp_path):
    pid = bg.start(tmp_path, popen=Popen, runner=Runner(), python="pythonw.exe")
    assert pid == 4242
    p = Popen.instances[0]
    assert p.cmd == ["pythonw.exe", "-m", "red", "--home", str(tmp_path)]
    assert p.kw["creationflags"] & bg.CREATE_NO_WINDOW and p.kw["creationflags"] & bg.DETACHED_PROCESS
    assert bg.read_pid(tmp_path) == 4242


def test_start_refuses_a_second_copy(tmp_path):
    bg.pid_file(tmp_path).parent.mkdir()
    bg.pid_file(tmp_path).write_text("4242")
    with pytest.raises(bg.BackgroundError, match="already running"):
        bg.start(tmp_path, popen=Popen, runner=Runner(alive={4242}))
    assert Popen.instances == []


def test_a_stale_pid_file_does_not_block_start(tmp_path):
    bg.pid_file(tmp_path).parent.mkdir()
    bg.pid_file(tmp_path).write_text("4242")
    assert bg.start(tmp_path, popen=Popen, runner=Runner(), python="p.exe") == 4242


def test_stop_kills_the_whole_tree_and_forgets_it(tmp_path):
    runner = Runner(alive={4242})
    bg.pid_file(tmp_path).parent.mkdir()
    bg.pid_file(tmp_path).write_text("4242")
    assert bg.stop(tmp_path, runner=runner) is True
    assert ["taskkill", "/PID", "4242", "/T", "/F"] in runner.calls
    assert bg.read_pid(tmp_path) is None


def test_stop_with_nothing_running(tmp_path):
    assert bg.stop(tmp_path, runner=Runner()) is False


def test_main_messages(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(bg, "start", lambda home: 99)
    assert bg.main("background", tmp_path) == 0
    assert "process 99" in capsys.readouterr().out
    monkeypatch.setattr(bg, "stop", lambda home: False)
    assert bg.main("stop", tmp_path) == 0
    assert "No hidden Red" in capsys.readouterr().out


# --- the hotkey watcher ------------------------------------------------------------

def test_start_if_needed_starts_red_when_nothing_is_running(tmp_path):
    bg.pid_file(tmp_path).parent.mkdir()
    assert bg._start_if_needed(tmp_path, runner=Runner(), popen=Popen, python="pythonw.exe") is True
    assert Popen.instances[0].cmd == ["pythonw.exe", "-m", "red", "--home", str(tmp_path)]


def test_start_if_needed_does_nothing_while_red_runs(tmp_path):
    bg.pid_file(tmp_path).parent.mkdir()
    bg.pid_file(tmp_path).write_text("4242")
    assert bg._start_if_needed(tmp_path, runner=Runner(alive={4242}), popen=Popen) is False
    assert Popen.instances == []


def test_start_if_needed_swallows_a_race(tmp_path, monkeypatch):
    def refuse(home, **kw):
        raise bg.BackgroundError("already running")

    monkeypatch.setattr(bg, "start", refuse)
    assert bg._start_if_needed(tmp_path, runner=Runner(), popen=Popen) is False


def test_hotkey_main_routes_to_the_watcher(tmp_path, monkeypatch, capsys):
    seen = []
    monkeypatch.setattr(bg, "watch", lambda home, **kw: seen.append((home, kw["hotkey"])))
    assert bg.main("hotkey", tmp_path, hotkey="Ctrl+Alt+R") == 0
    assert seen == [(tmp_path, "Ctrl+Alt+R")]
    assert bg.main("hotkey", tmp_path, hotkey=None) == 1
    assert "turned off" in capsys.readouterr().out


# --- the watchdog: a crashed Red comes back (plan.md task 2.4) ----------------

def crashed(tmp_path, pid=111):
    bg.pid_file(tmp_path).parent.mkdir(parents=True, exist_ok=True)
    bg.pid_file(tmp_path).write_text(str(pid), encoding="ascii")   # left behind, process gone


def test_a_crashed_red_is_started_again(tmp_path, caplog):
    crashed(tmp_path)
    dog = bg.Watchdog(tmp_path, runner=Runner(), popen=Popen, python="pythonw.exe")
    assert dog.check(now=0.0) is True
    assert len(Popen.instances) == 1 and bg.read_pid(tmp_path) == 4242
    assert "stopped unexpectedly" in caplog.text


def test_a_running_red_is_left_alone(tmp_path):
    crashed(tmp_path, pid=111)
    dog = bg.Watchdog(tmp_path, runner=Runner(alive={111}), popen=Popen, python="pythonw.exe")
    assert dog.check(now=0.0) is False and Popen.instances == []


def test_a_red_stopped_on_purpose_stays_stopped(tmp_path):
    runner = Runner(alive={111})
    crashed(tmp_path, pid=111)
    bg.stop(tmp_path, runner=runner)                              # python -m red stop
    dog = bg.Watchdog(tmp_path, runner=runner, popen=Popen, python="pythonw.exe")
    assert dog.check(now=0.0) is False and Popen.instances == []


def test_at_most_three_restarts_an_hour(tmp_path, caplog):
    dog = bg.Watchdog(tmp_path, runner=Runner(), popen=Popen, python="pythonw.exe")
    for minute in range(4):
        crashed(tmp_path)
        dog.check(now=minute * 60.0)
    assert len(Popen.instances) == 3
    assert "not starting it again" in caplog.text
    crashed(tmp_path)
    assert dog.check(now=3700.0) is True                          # an hour later it tries again
