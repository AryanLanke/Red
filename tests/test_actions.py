"""The real tools with fake side effects: no windows, no shutdown.exe."""

import subprocess
from datetime import datetime
from pathlib import Path

import pytest

from fakes import FakePopen, FakeRunner, FakeStartfile
from red.allowlist import Allowlist
from red.tools import default_registry
from red.tools.base import ToolError
from red.tools.system import (CancelShutdown, OpenApp, OpenFolder, Restart, Shutdown,
                              format_clock, format_duration)
from red.tools.web import OpenUrl

NOW = datetime(2026, 11, 8, 21, 40)


# ---------- open_folder ----------

@pytest.fixture
def folders(tmp_path):
    known = {"downloads": tmp_path / "Downloads", "music": tmp_path / "OneDrive" / "Music"}
    for p in known.values():
        p.mkdir(parents=True)
    projects = tmp_path / "Projects"
    projects.mkdir()
    allow = Allowlist(folders={"projects": projects, "gone": tmp_path / "missing"})
    start = FakeStartfile()
    tool = OpenFolder(allowlist=allow, startfile=start, known=lambda: known)
    return tool, start, known, projects


@pytest.mark.parametrize("name, key", [("Downloads", "downloads"), ("my music folder", "music")])
def test_open_known_folder(folders, name, key):
    tool, start, known, _ = folders
    assert tool.run(folder=name) == f"Opening {key.capitalize()}."
    assert start.calls == [(str(known[key]), {})]


def test_open_allowlisted_folder(folders):
    tool, start, _, projects = folders
    assert tool.run(folder="Projects") == "Opening projects."
    assert start.calls == [(str(projects), {})]


def test_full_path_only_if_known_or_allowlisted(folders, tmp_path):
    tool, start, known, projects = folders
    tool.run(folder=str(projects).upper() + "\\")
    tool.run(folder=str(known["downloads"]))
    assert [c[0] for c in start.calls] == [str(projects), str(known["downloads"])]
    with pytest.raises(ToolError):
        tool.run(folder=str(tmp_path))       # exists, but isn't on any list
    with pytest.raises(ToolError):
        tool.run(folder="C:\\Windows\\System32")
    assert len(start.calls) == 2


@pytest.mark.parametrize("name", ["secret stuff", "..", "C:", "%USERPROFILE%"])
def test_unknown_folder_never_guessed(folders, name):
    tool, start, _, _ = folders
    with pytest.raises(ToolError, match="allowlist"):
        tool.run(folder=name)
    assert start.calls == []


def test_missing_or_file_folder_not_opened(folders, tmp_path):
    tool, start, _, _ = folders
    with pytest.raises(ToolError, match="doesn't exist"):
        tool.run(folder="gone")
    exe = tmp_path / "evil.exe"
    exe.write_text("x")
    tool2 = OpenFolder(allowlist=Allowlist(folders={"evil": exe}), startfile=start, known=dict)
    with pytest.raises(ToolError):
        tool2.run(folder="evil")              # a file is never passed to startfile
    assert start.calls == []


def test_folder_allowlist_reloaded_each_time(tmp_path):
    allow_file = tmp_path / "allowlist.toml"
    target = tmp_path / "Work"
    target.mkdir()
    from red.allowlist import load_allowlist
    start = FakeStartfile()
    tool = OpenFolder(allowlist=lambda: load_allowlist(allow_file), startfile=start, known=dict)
    with pytest.raises(ToolError):
        tool.run(folder="work")
    allow_file.write_text(f"[folders]\nwork = '{target}'\n", encoding="utf-8")
    assert tool.run(folder="work") == "Opening work."


# ---------- open_app ----------

def _which(found):
    return lambda name: found.get(name)


def test_open_builtin_app_without_shell():
    popen = FakePopen()
    tool = OpenApp(allowlist=Allowlist(), popen=popen,
                   which=_which({"notepad.exe": "C:\\Windows\\notepad.exe"}))
    assert tool.run(app="Notepad") == "Opening Notepad."
    argv, kwargs = popen.calls[0]
    assert argv == ["C:\\Windows\\notepad.exe"]
    assert kwargs["shell"] is False


def test_open_allowlisted_app_with_args():
    popen = FakePopen()
    allow = Allowlist(apps={"vs code": ("code", "--new-window")})
    tool = OpenApp(allowlist=allow, popen=popen,
                   which=_which({"code": "C:\\VSCode\\bin\\code.cmd"}))
    assert tool.run(app="VS Code") == "Opening VS Code."
    argv, kwargs = popen.calls[0]
    assert argv == ["C:\\VSCode\\bin\\code.cmd", "--new-window"]
    assert kwargs["creationflags"] == getattr(subprocess, "CREATE_NO_WINDOW", 0)


@pytest.mark.parametrize("app", ["cmd /c del *", "powershell", "C:\\evil.exe", "notepad & calc"])
def test_unknown_app_never_run(app):
    popen = FakePopen()
    tool = OpenApp(allowlist=Allowlist(), popen=popen, which=lambda n: "C:\\x\\" + n)
    with pytest.raises(ToolError, match="allowlist"):
        tool.run(app=app)
    assert popen.calls == []


def test_app_program_missing():
    popen = FakePopen()
    tool = OpenApp(allowlist=Allowlist(apps={"x": ("nothere.exe",)}), popen=popen,
                   which=lambda n: None)
    with pytest.raises(ToolError, match="couldn't find"):
        tool.run(app="x")
    assert popen.calls == []


def test_elevated_app_falls_back_to_shell_open():
    err = OSError(22, "The requested operation requires elevation")
    err.winerror = 740
    start = FakeStartfile()
    tool = OpenApp(allowlist=Allowlist(), popen=FakePopen(error=err), startfile=start,
                   which=_which({"taskmgr.exe": "C:\\Windows\\System32\\taskmgr.exe"}))
    assert tool.run(app="task manager") == "Opening task manager."
    assert start.calls == [("C:\\Windows\\System32\\taskmgr.exe", {"arguments": ""})]


def test_app_start_error_is_tool_error():
    tool = OpenApp(allowlist=Allowlist(), popen=FakePopen(error=OSError(2, "not found")),
                   which=_which({"calc.exe": "C:\\calc.exe"}))
    with pytest.raises(ToolError, match="couldn't start"):
        tool.run(app="calculator")


# ---------- open_url ----------

def test_open_url():
    opened = []
    tool = OpenUrl(open_browser=lambda u: opened.append(u) or True)
    assert tool.run(url="https://www.youtube.com") == "Opening youtube.com."
    assert opened == ["https://www.youtube.com"]


@pytest.mark.parametrize("url", ["javascript:alert(1)", "file:///C:/x", "https://", "http:// x",
                                 "https://a\nb", "ms-settings:display"])
def test_open_url_rejects_other_schemes(url):
    opened = []
    with pytest.raises(ToolError):
        OpenUrl(open_browser=lambda u: opened.append(u) or True).run(url=url)
    assert opened == []


def test_open_url_browser_failure():
    with pytest.raises(ToolError):
        OpenUrl(open_browser=lambda u: False).run(url="https://example.com")


# ---------- shutdown, restart, cancel ----------

@pytest.mark.parametrize("minutes, text", [
    (0, "0 minutes"), (1, "1 minute"), (45, "45 minutes"), (60, "1 hour"),
    (90, "1 hour and 30 minutes"), (180, "3 hours"), (1440, "24 hours"),
])
def test_format_duration(minutes, text):
    assert format_duration(minutes) == text


def test_format_clock():
    assert format_clock(datetime(2026, 11, 8, 23, 40), NOW) == "11:40 PM"
    assert format_clock(datetime(2026, 11, 9, 9, 5), NOW) == "9:05 AM tomorrow"


def test_describe_has_exact_time():
    tool = Shutdown(runner=FakeRunner(), now=lambda: NOW)
    assert tool.describe(minutes=120) == "Shut down in 2 hours (at 11:40 PM)"
    assert tool.describe(minutes=200) == "Shut down in 3 hours and 20 minutes (at 1:00 AM tomorrow)"
    assert tool.describe(minutes=0) == "Shut down now"
    assert Restart(runner=FakeRunner(), now=lambda: NOW).describe(minutes=10) == \
        "Restart in 10 minutes (at 9:50 PM)"


@pytest.mark.parametrize("cls, flag", [(Shutdown, "/s"), (Restart, "/r")])
def test_schedule_replaces_old_one(cls, flag):
    runner = FakeRunner(codes={"/a": 1116})          # nothing scheduled yet
    reply = cls(runner=runner, now=lambda: NOW).run(minutes=120)
    assert runner.flags == [["/a"], [flag, "/t", "7200"]]
    assert "11:40 PM" in reply and "2 hours" in reply and "cancel" in reply
    argv, kwargs = runner.calls[1]
    assert argv[0].lower().endswith("shutdown.exe")
    assert "shell" not in kwargs and kwargs["timeout"] > 0


def test_shutdown_now():
    runner = FakeRunner()
    assert Shutdown(runner=runner, now=lambda: NOW).run(minutes=0) == "Shutting down now."
    assert runner.flags[-1] == ["/s", "/t", "0"]


def test_shutdown_failure_reported():
    runner = FakeRunner(codes={"/s": 5}, output="Access is denied.(5)")
    with pytest.raises(ToolError, match="Access is denied"):
        Shutdown(runner=runner, now=lambda: NOW).run(minutes=5)


def test_shutdown_rejects_out_of_range_even_without_schema():
    runner = FakeRunner()
    with pytest.raises(ToolError):
        Shutdown(runner=runner).run(minutes=24 * 60 + 1)
    with pytest.raises(ToolError):
        Restart(runner=runner).run(minutes=-1)
    assert runner.calls == []


def test_runner_crash_is_tool_error():
    def boom(argv, **kw):
        raise subprocess.TimeoutExpired(argv, 15)
    with pytest.raises(ToolError):
        Shutdown(runner=boom).run(minutes=5)


def test_cancel():
    runner = FakeRunner()
    assert "won't shut down" in CancelShutdown(runner=runner).run()
    assert runner.flags == [["/a"]]
    assert "Nothing was scheduled" in CancelShutdown(runner=FakeRunner(codes={"/a": 1116})).run()
    with pytest.raises(ToolError):
        CancelShutdown(runner=FakeRunner(codes={"/a": 5})).run()


def test_only_shutdown_and_restart_are_destructive():
    destructive = {t.name for t in default_registry() if t.destructive}
    assert {"shutdown", "restart"} <= destructive
    assert "cancel_shutdown" not in destructive
    assert not {"open_folder", "open_app", "open_url"} & destructive
