"""Office and other well-known apps through App Paths. Nothing is started."""

import sys
from pathlib import Path

import pytest

from red.allowlist import Allowlist
from red.tools.apps import AppPaths, app_key, read_app_path
from red.tools.base import ToolError
from red.tools.system import OpenApp
from tests.fakes import FakePopen, FakeStartfile

OFFICE = r"C:\Program Files\Microsoft Office\Root\Office16"
STORE = r"C:\Program Files\WindowsApps\Microsoft.Paint_11_x64__8wekyb3d8bbwe\PaintApp\mspaint.exe"

REGISTRY = {
    "powerpnt.exe": rf"{OFFICE}\POWERPNT.EXE",
    "winword.exe": rf"{OFFICE}\WINWORD.EXE",
    "excel.exe": rf"{OFFICE}\EXCEL.EXE",
    "olk.exe": r"C:\Program Files\WindowsApps\Microsoft.OutlookForWindows_x64\olk.exe",
    "mspaint.exe": STORE,
    "chrome.exe": r"C:\Gone\chrome.exe",
}


def app_paths(registry=REGISTRY, missing=(r"C:\Gone\chrome.exe",)):
    return AppPaths(read=registry.get, exists=lambda p: str(p) not in missing)


def make(registry=REGISTRY, allow=None):
    start = FakeStartfile()
    popen = FakePopen()
    tool = OpenApp(allowlist=allow or Allowlist(), popen=popen, which=lambda p: None,
                   startfile=start, app_paths=app_paths(registry))
    return tool, start, popen


@pytest.mark.parametrize("said, path", [
    ("PowerPoint", rf"{OFFICE}\POWERPNT.EXE"),
    ("power point", rf"{OFFICE}\POWERPNT.EXE"),
    ("ppt", rf"{OFFICE}\POWERPNT.EXE"),
    ("Microsoft PowerPoint", rf"{OFFICE}\POWERPNT.EXE"),
    ("the word app", rf"{OFFICE}\WINWORD.EXE"),
    ("MS Excel", rf"{OFFICE}\EXCEL.EXE"),
])
def test_office_apps_open_by_registered_path(said, path):
    tool, start, popen = make()
    reply = tool.run(app=said)
    assert start.calls == [(path, {})]
    assert popen.calls == []
    assert reply.startswith("Opening ")


def test_store_apps_start_by_their_app_paths_name():
    tool, start, _ = make()
    assert tool.run(app="paint") == "Opening Paint."
    assert start.calls == [("mspaint.exe", {})]


def test_falls_back_to_the_next_exe():
    tool, start, _ = make()
    assert tool.run(app="outlook") == "Opening Outlook."
    assert start.calls == [("olk.exe", {})]          # new Outlook, a Store app


def test_known_but_not_installed():
    tool, start, _ = make()
    with pytest.raises(ToolError, match="OneNote doesn't seem to be installed"):
        tool.run(app="onenote")
    with pytest.raises(ToolError, match="Chrome doesn't seem to be installed"):
        tool.run(app="chrome")                        # registered, but the file is gone
    assert start.calls == []


def test_unknown_app_still_says_allowlist():
    tool, _, _ = make()
    with pytest.raises(ToolError, match="allowlist.toml"):
        tool.run(app="photoshop")


def test_allowlist_wins_over_app_paths():
    allow = Allowlist(apps={"word": ("wordpad.exe",)})
    start, popen = FakeStartfile(), FakePopen()
    tool = OpenApp(allowlist=allow, popen=popen, which=lambda p: r"C:\x\wordpad.exe",
                   startfile=start, app_paths=app_paths())
    tool.run(app="word")
    assert popen.calls[0][0] == [r"C:\x\wordpad.exe"]
    assert start.calls == []


def test_startfile_error_is_a_tool_error():
    def broken(path, **kw):
        raise OSError(2, "The system cannot find the file specified")

    tool = OpenApp(allowlist=Allowlist(), startfile=broken, app_paths=app_paths())
    with pytest.raises(ToolError, match="couldn't start PowerPoint"):
        tool.run(app="powerpoint")


def test_model_text_is_only_a_lookup_key():
    seen = []
    tool = OpenApp(allowlist=Allowlist(), startfile=FakeStartfile(),
                   app_paths=AppPaths(read=lambda exe: seen.append(exe)))
    with pytest.raises(ToolError):
        tool.run(app=r"C:\Windows\System32\cmd.exe")
    with pytest.raises(ToolError):
        tool.run(app="cmd.exe /c del")
    assert seen == []                                 # nothing outside the fixed list is read


@pytest.mark.parametrize("name, key", [
    ("Microsoft Word", "word"), ("the Excel application", "excel"), ("  PPT ", "ppt"),
    ("Office PowerPoint", "powerpoint"),
])
def test_app_key(name, key):
    assert app_key(name) == key


@pytest.mark.skipif(sys.platform != "win32", reason="Windows registry")
def test_real_registry_read_is_safe():
    assert read_app_path("no-such-app-for-red-tests.exe") is None
    value = read_app_path("powershell.exe")
    assert value is None or Path(value).name.lower() == "powershell.exe"
