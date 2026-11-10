"""red.windows: waking and fronting a window (the blank YouTube page fix).

No real window is touched: a fake FrontOps records the Win32 calls, and a
fake desktop drives the Watcher end to end.
"""

from red.windows import (SW_RESTORE, SW_SHOW, Watcher, Window, browser_target, front_window,
                         site_name)


class FakeOps:
    """Window state and the Win32 calls front_window() makes, recorded in order."""

    def __init__(self, *, visible=True, iconic=False, foreground=0, can_activate=True,
                 alt_works=True):
        self.visible, self.iconic = visible, iconic
        self._foreground = foreground
        self.can_activate, self.alt_works = can_activate, alt_works
        self.alt_down = False
        self.calls = []

    def is_visible(self, hwnd):
        return self.visible

    def is_iconic(self, hwnd):
        return self.iconic

    def show(self, hwnd, command):
        self.calls.append(("show", command))
        if command == SW_SHOW:
            self.visible = True
        if command == SW_RESTORE:
            self.iconic = False
            self.visible = True

    def update(self, hwnd):
        self.calls.append(("update", hwnd))

    def redraw(self, hwnd):
        self.calls.append(("redraw", hwnd))

    def foreground(self):
        return self._foreground

    def thread_of(self, hwnd):
        return 0

    def current_thread(self):
        return 100

    def attach(self, mine, other, on):
        return True

    def bring_to_top(self, hwnd):
        self.calls.append(("top", hwnd))

    def set_foreground(self, hwnd):
        self.calls.append(("set_foreground", hwnd))
        if self.can_activate or (self.alt_down and self.alt_works):
            self._foreground = hwnd

    def press_alt(self):
        self.calls.append(("press_alt", None))
        self.alt_down = True

    def release_alt(self):
        self.calls.append(("release_alt", None))
        self.alt_down = False


def window(hwnd=7, title="YouTube", exe="chrome.exe"):
    return Window(hwnd, 1234, exe, title)


# --- restoring, repainting, fronting ------------------------------------------------

def test_a_minimised_window_is_restored_and_repainted_before_it_is_fronted():
    ops = FakeOps(iconic=True)
    assert front_window(ops, 7, settle=0, sleep=lambda s: None) is True
    assert ops.foreground() == 7
    kinds = [c[0] for c in ops.calls]
    assert ops.calls[:2] == [("show", SW_RESTORE), ("update", 7)]
    assert kinds[-1] == "redraw"
    assert kinds.index("top") < kinds.index("set_foreground") < kinds.index("redraw")


def test_a_hidden_window_is_shown_and_repainted():
    ops = FakeOps(visible=False)
    assert front_window(ops, 7, settle=0, sleep=lambda s: None) is True
    assert ops.calls[0] == ("show", SW_SHOW)
    assert ("update", 7) in ops.calls and ("redraw", 7) in ops.calls


def test_a_normal_window_is_just_fronted():
    ops = FakeOps()
    assert front_window(ops, 7, settle=0, sleep=lambda s: None) is True
    assert ops.calls == [("top", 7), ("set_foreground", 7)]      # no restore, no redraw


def test_a_window_already_in_front_is_left_alone():
    ops = FakeOps(foreground=7)
    assert front_window(ops, 7, settle=0, sleep=lambda s: None) is True
    assert ops.calls == []


def test_a_minimised_window_already_in_front_is_still_restored():
    ops = FakeOps(iconic=True, foreground=7)
    assert front_window(ops, 7, settle=0, sleep=lambda s: None) is True
    kinds = [c[0] for c in ops.calls]
    assert kinds[:2] == ["show", "update"] and kinds[-1] == "redraw"


def test_the_alt_key_trick_is_the_backup_when_the_lock_wont_lift():
    ops = FakeOps(can_activate=False, alt_works=True)
    assert front_window(ops, 7, settle=0, sleep=lambda s: None) is True
    kinds = [c[0] for c in ops.calls]
    assert kinds.count("set_foreground") == 2
    press, release = kinds.index("press_alt"), kinds.index("release_alt")
    assert kinds.index("top") < press < release
    assert kinds.index("set_foreground", press) < release


def test_a_window_that_cannot_be_fronted_is_reported():
    ops = FakeOps(can_activate=False, alt_works=False)
    assert front_window(ops, 7, settle=0, sleep=lambda s: None) is False
    assert not ops.alt_down and "redraw" not in [c[0] for c in ops.calls]


def test_a_restored_window_is_given_a_moment_to_paint():
    slept = []
    ops = FakeOps(iconic=True)
    front_window(ops, 7, settle=0.06, sleep=slept.append)
    assert slept == [0.06]


# --- the watcher wakes a browser's window ---------------------------------------------

class FakeDesktop:
    """Windows with titles, and fronting through front_window()."""

    def __init__(self, windows, ops):
        self._windows, self.ops, self.fronted = list(windows), ops, []

    def windows(self):
        return list(self._windows)

    def front(self, hwnd):
        self.fronted.append(hwnd)
        return front_window(self.ops, hwnd, settle=0, sleep=lambda s: None)


def test_the_watcher_restores_the_browser_window_a_youtube_tab_lands_in():
    ops = FakeOps(iconic=True, foreground=1)
    desktop = FakeDesktop([Window(7, 55, "chrome.exe", "New Tab")], ops)
    watcher = Watcher(browser_target("chrome.exe", "youtube"), desktop,
                      wait=1, clock=iter([0, 1, 2]).__next__, sleep=lambda s: None)
    # The tab loads in the window that was already there: its title changes,
    # and it has been minimised for a while (so it was throttled).
    desktop._windows = [Window(7, 55, "chrome.exe", "YouTube")]
    assert watcher() is True
    assert desktop.fronted == [7]
    assert ("show", SW_RESTORE) in ops.calls and ("redraw", 7) in ops.calls


def test_the_watcher_ignores_a_browser_window_that_never_shows_the_page():
    ops = FakeOps()
    desktop = FakeDesktop([Window(7, 55, "chrome.exe", "New Tab")], ops)
    watcher = Watcher(browser_target("chrome.exe", "youtube"), desktop,
                      wait=0, clock=iter([0, 0, 1]).__next__, sleep=lambda s: None)
    assert watcher() is False
    assert desktop.fronted == [] and ops.calls == []


def test_youtube_is_recognised_in_a_page_title():
    assert site_name("www.youtube.com") == "youtube"
    target = browser_target("chrome.exe", "youtube")
    assert target.shows_page(window(title="Crazy (Official Video) - YouTube"))
    assert not target.shows_page(window(title="New Tab"))
