"""red.windows with a fake desktop: finding the window Red just opened and fronting it."""

import pytest

from fakes import FakePopen, FakeStartfile
from red import windows as w
from red.allowlist import Allowlist
from red.tools.apps import AppPaths
from red.tools.system import OpenApp, OpenFolder
from red.tools.web import OpenUrl, WebSearch
from red.tools.youtube import PlayOnline, Video

# conftest swaps red.windows.watch for a no-op in every test; this is the real one,
# taken at import time, used here only with fake desktops.
REAL_WATCH = w.watch


class FakeDesktop:
    """Windows appear on the desktop at given times; front() records what was fronted."""

    def __init__(self, now=(), later=()):
        self.now = list(now)            # there before launching
        self.later = list(later)        # (seconds after launching, Window)
        self.t = 0.0
        self.fronted = []

    def windows(self):
        shown = [win for at, win in self.later if at <= self.t]
        return list(reversed(shown)) + self.now          # newest on top

    def front(self, hwnd):
        self.fronted.append(hwnd)
        return True

    def clock(self):
        return self.t

    def sleep(self, seconds):
        self.t += seconds


def watcher(target, desktop):
    return w.Watcher(target, desktop, clock=desktop.clock, sleep=desktop.sleep)


EDGE_OLD = w.Window(1, 100, "msedge.exe", "News - Microsoft Edge")
CODE = w.Window(2, 200, "code.exe", "edge.py - VS Code")
EDGE_NEW = w.Window(3, 101, "msedge.exe", "New tab - Microsoft Edge")


def test_a_new_window_of_the_app_comes_to_the_front():
    desktop = FakeDesktop(now=[EDGE_OLD, CODE], later=[(1.5, EDGE_NEW)])
    assert watcher(w.app_target("C:\\Program Files\\msedge.exe", "Edge"), desktop)() is True
    assert desktop.fronted == [3]                 # the new one, not the old Edge window
    assert 1.5 <= desktop.t < 1.7


def test_windows_that_were_already_there_are_not_new():
    desktop = FakeDesktop(now=[EDGE_OLD, CODE])
    assert watcher(w.app_target("msedge.exe", "Edge"), desktop)() is False
    assert desktop.fronted == []
    assert desktop.t >= w.WAIT_SECONDS             # gave up after about 5 seconds


def test_matching_by_process_id():
    notepad = w.Window(9, 4242, "notepad.exe", "Untitled - Notepad")
    desktop = FakeDesktop(later=[(0.3, notepad)])
    found = watcher(w.app_target(None, "my editor"), desktop)
    found.add_pid(4242)
    assert found() is True and desktop.fronted == [9]


def test_matching_by_title_for_store_apps():
    calc = w.Window(5, 300, "applicationframehost.exe", "Calculator")
    desktop = FakeDesktop(later=[(0.8, calc)])
    assert watcher(w.app_target("calc.exe", "Calculator"), desktop)() is True
    assert desktop.fronted == [5]


def test_an_explorer_window_by_folder_name():
    other = w.Window(6, 50, "explorer.exe", "Documents")
    downloads = w.Window(7, 50, "explorer.exe", "Downloads")
    desktop = FakeDesktop(now=[other], later=[(0.4, other.__class__(8, 50, "explorer.exe", "Pictures")),
                                               (0.6, downloads)])
    assert watcher(w.folder_target("Downloads"), desktop)() is True
    assert desktop.fronted == [7]


def test_a_browser_tab_in_an_existing_window_fronts_that_window():
    desktop = FakeDesktop(now=[CODE, EDGE_OLD])        # VS Code on top, Edge behind it
    target = w.Target(exes=frozenset({"msedge.exe"}), reuse=True)
    assert watcher(target, desktop)() is True
    assert desktop.fronted == [1]
    assert w.REUSE_AFTER_SECONDS <= desktop.t < w.REUSE_AFTER_SECONDS + 0.2


def test_a_browser_that_wasnt_running_gets_time_to_start():
    desktop = FakeDesktop(now=[CODE], later=[(3.0, EDGE_NEW)])
    target = w.Target(exes=frozenset({"msedge.exe"}), reuse=True)
    assert watcher(target, desktop)() is True
    assert desktop.fronted == [3]


def test_browser_target_uses_the_default_browser(monkeypatch):
    monkeypatch.setattr(w, "default_browser_exe", lambda: "chrome.exe")
    assert w.browser_target().exes == frozenset({"chrome.exe"})
    monkeypatch.setattr(w, "default_browser_exe", lambda: None)
    assert w.browser_target().exes == w.BROWSERS


def test_watch_never_fails_the_launch():
    class Broken:
        def windows(self):
            raise OSError("no desktop")
    found = REAL_WATCH(w.Target(), Broken())
    found.add_pid(1)
    assert found() is False


# --- the tools hand the watcher to finish_later -----------------------------------

class Watches:
    def __init__(self):
        self.targets, self.pids, self.ran = [], [], 0

    def __call__(self, target):
        self.targets.append(target)
        outer = self

        class One:
            def add_pid(self, pid):
                outer.pids.append(pid)

            def __call__(self):
                outer.ran += 1
                return True
        return One()


def test_open_folder_fronts_the_explorer_window(tmp_path):
    watches = Watches()
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    tool = OpenFolder(allowlist=Allowlist(), startfile=FakeStartfile(),
                      known=lambda: {"downloads": downloads}, watch=watches)
    assert tool.run(folder="Downloads") == "Opening Downloads."
    later = tool.take_later()
    assert later is not None and watches.targets[0].titles == ("downloads",)
    later()
    assert watches.ran == 1


def test_open_app_watches_the_registered_program():
    watches = Watches()
    paths = AppPaths(read=lambda exe: "C:\\Edge\\msedge.exe" if exe == "msedge.exe" else None,
                     exists=lambda p: True)
    tool = OpenApp(allowlist=Allowlist(), startfile=FakeStartfile(), app_paths=paths, watch=watches)
    assert tool.run(app="Edge") == "Opening Edge."
    assert watches.targets[0].exes == frozenset({"msedge.exe"}) and tool.take_later() is not None


def test_open_app_adds_the_process_id(tmp_path):
    class Proc:
        pid = 777

    class Popen(FakePopen):
        def __call__(self, argv, **kwargs):
            super().__call__(argv, **kwargs)
            return Proc()
    watches = Watches()
    tool = OpenApp(allowlist=Allowlist(apps={"notepad": ("notepad.exe",)}), popen=Popen(),
                   which=lambda name: "C:\\Windows\\notepad.exe", watch=watches)
    tool.run(app="notepad")
    assert watches.pids == [777] and watches.targets[0].exes == frozenset({"notepad.exe"})


def test_a_failed_launch_leaves_nothing_to_finish():
    watches = Watches()
    tool = OpenUrl(open_browser=lambda url: False, watch=watches)
    with pytest.raises(Exception):
        tool.run(url="https://example.com")
    assert tool.take_later() is None


@pytest.mark.parametrize("make, args", [
    (lambda watch: OpenUrl(open_browser=lambda url: True, watch=watch), {"url": "https://example.com"}),
    (lambda watch: WebSearch(open_browser=lambda url: True, watch=watch), {"query": "cats"}),
    (lambda watch: PlayOnline(open_browser=lambda url: True, find=lambda q: Video("abcdefghijk", "Cats"),
                              watch=watch), {"query": "cats"}),
])
def test_browser_tools_front_the_browser(make, args):
    watches = Watches()
    tool = make(watches)
    tool.run(**args)
    assert watches.targets[0].reuse is True and tool.take_later() is not None
