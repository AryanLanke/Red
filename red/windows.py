"""Bring the window Red just opened to the front.

Red usually runs hidden, and Windows doesn't let a background process push
a window in front of what you're using (the "foreground lock"): a new Edge
window would only flash in the taskbar. So after open_app, open_folder,
open_url or play_online starts something, Red waits up to about 5 seconds
for its top-level window and brings it to the front:

1. Snapshot the visible top-level windows before launching.
2. After launching, look for a new window from the same process, program or
   with the expected title. Browsers often open a tab in a window that's
   already there; then Red fronts the topmost window of that browser.
3. Restore it if it's minimised, then SetForegroundWindow, with
   AttachThreadInput (and the Alt-key trick if that isn't enough) to get
   past the foreground lock.

Only signed system APIs (user32, kernel32, dwmapi) through ctypes. Windows
are only looked at and activated; nothing is closed, moved or typed into.
"""

from __future__ import annotations

import logging
import os
import sys
import time
from dataclasses import dataclass, field
from typing import Callable, Protocol

log = logging.getLogger(__name__)

WAIT_SECONDS = 5.0
POLL_SECONDS = 0.1
# A browser that already had a window: if no new window shows up by then,
# the page opened as a tab in an existing one.
REUSE_AFTER_SECONDS = 1.2

BROWSERS = frozenset({"msedge.exe", "chrome.exe", "firefox.exe", "brave.exe", "opera.exe",
                      "vivaldi.exe", "iexplore.exe", "arc.exe"})
# The default browser's ProgId prefix (UserChoice) -> its program.
_PROG_IDS = (("MSEdge", "msedge.exe"), ("ChromeHTML", "chrome.exe"), ("Firefox", "firefox.exe"),
             ("BraveHTML", "brave.exe"), ("Opera", "opera.exe"), ("Vivaldi", "vivaldi.exe"),
             ("IE.HTTP", "iexplore.exe"))


@dataclass(frozen=True)
class Window:
    hwnd: int
    pid: int
    exe: str          # lower case, e.g. "msedge.exe"
    title: str


@dataclass
class Target:
    """What the launched thing's window looks like. Any one of these is enough."""

    exes: frozenset[str] = frozenset()
    pids: set[int] = field(default_factory=set)
    titles: tuple[str, ...] = ()      # lower case words expected in the title
    reuse: bool = False               # browsers: may open in an existing window

    def matches(self, w: Window) -> bool:
        title = w.title.lower()
        return (w.pid in self.pids or w.exe in self.exes
                or any(t and t in title for t in self.titles))


class Desktop(Protocol):
    def windows(self) -> list[Window]: ...      # visible top-level windows, topmost first
    def front(self, hwnd: int) -> bool: ...


def app_target(exe: str | None = None, title: str = "", pid: int | None = None) -> Target:
    exes = frozenset({os.path.basename(exe).lower()}) if exe else frozenset()
    return Target(exes=exes, pids={pid} if pid else set(),
                  titles=(title.strip().lower(),) if title.strip() else ())


def folder_target(name: str) -> Target:
    """A File Explorer window showing the folder `name`."""
    return Target(titles=(name.strip().lower(),))


def browser_target() -> Target:
    """The default browser (or any browser, if Windows doesn't say which)."""
    exe = default_browser_exe()
    return Target(exes=frozenset({exe}) if exe else BROWSERS, reuse=True)


def default_browser_exe() -> str | None:
    if sys.platform != "win32":
        return None
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\Shell\Associations\UrlAssociations"
                            r"\https\UserChoice") as key:
            prog_id, _ = winreg.QueryValueEx(key, "ProgId")
    except OSError:
        return None
    for prefix, exe in _PROG_IDS:
        if str(prog_id).startswith(prefix):
            return exe
    return None


class Watcher:
    """Made just before launching. Calling it waits for the window and fronts it."""

    def __init__(self, target: Target, desktop: Desktop, *, wait: float = WAIT_SECONDS,
                 clock: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] = time.sleep):
        self.target = target
        self._desktop = desktop
        self._wait, self._clock, self._sleep = wait, clock, sleep
        before = desktop.windows()
        self._before = {w.hwnd for w in before}
        self._had_window = target.reuse and any(w.exe in target.exes for w in before)

    def add_pid(self, pid: int | None) -> None:
        """The launched process, once it exists (open_app with Popen)."""
        if pid:
            self.target.pids.add(pid)

    def __call__(self) -> bool:
        start = self._clock()
        while True:
            now = self._desktop.windows()
            new = [w for w in now if w.hwnd not in self._before and self.target.matches(w)]
            if new:
                return self._front(new[0], "new")
            waited = self._clock() - start
            if self._had_window and waited >= REUSE_AFTER_SECONDS:
                old = [w for w in now if w.exe in self.target.exes]
                if old:
                    return self._front(old[0], "existing")
            if waited >= self._wait:
                log.info("No window showed up for %s", self.target)
                return False
            self._sleep(POLL_SECONDS)

    def _front(self, w: Window, kind: str) -> bool:
        ok = self._desktop.front(w.hwnd)
        log.info("Brought the %s window %r (%s) to the front: %s", kind, w.title[:60], w.exe, ok)
        return ok


class _NoWatch:
    """Off Windows (or if the desktop can't be read): nothing to do."""

    def add_pid(self, pid) -> None:
        pass

    def __call__(self) -> bool:
        return False


def watch(target: Target, desktop: Desktop | None = None):
    """Call before launching; pass the result to Tool.finish_later()."""
    if desktop is None:
        if sys.platform != "win32":
            return _NoWatch()
        try:
            desktop = Win32Desktop()
        except Exception:  # noqa: BLE001 - only polish; the launch still happens
            log.exception("Can't read the desktop's windows")
            return _NoWatch()
    try:
        return Watcher(target, desktop)
    except Exception:  # noqa: BLE001
        log.exception("Can't read the desktop's windows")
        return _NoWatch()


# --------------------------------------------------------------------------
# The real desktop (Windows only)
# --------------------------------------------------------------------------

SW_RESTORE = 9
GW_OWNER = 4
DWMWA_CLOAKED = 14
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
VK_MENU = 0x12
VK_UNASSIGNED = 0x88       # a key nothing uses: stops the Alt tap from opening a menu
KEYEVENTF_KEYUP = 0x0002


class Win32Desktop:
    def __init__(self):
        import ctypes
        from ctypes import wintypes

        self._ct, self._wt = ctypes, wintypes
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        try:
            self.dwmapi = ctypes.WinDLL("dwmapi")
        except OSError:
            self.dwmapi = None
        u, k = self.user32, self.kernel32
        self._enum_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        u.EnumWindows.argtypes = [self._enum_proc, wintypes.LPARAM]
        u.GetWindowTextLengthW.argtypes = [wintypes.HWND]
        u.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        u.IsWindowVisible.argtypes = [wintypes.HWND]
        u.IsIconic.argtypes = [wintypes.HWND]
        u.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
        u.GetWindow.restype = wintypes.HWND
        u.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        u.GetWindowThreadProcessId.restype = wintypes.DWORD
        u.GetForegroundWindow.restype = wintypes.HWND
        u.SetForegroundWindow.argtypes = [wintypes.HWND]
        u.BringWindowToTop.argtypes = [wintypes.HWND]
        u.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        u.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
        u.keybd_event.argtypes = [wintypes.BYTE, wintypes.BYTE, wintypes.DWORD, ctypes.c_void_p]
        k.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        k.OpenProcess.restype = wintypes.HANDLE
        k.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                                 ctypes.POINTER(wintypes.DWORD)]
        k.CloseHandle.argtypes = [wintypes.HANDLE]
        self._exe_cache: dict[int, str] = {}
        self._own_pid = os.getpid()

    def _exe(self, pid: int) -> str:
        if pid in self._exe_cache:
            return self._exe_cache[pid]
        name = ""
        handle = self.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if handle:
            try:
                buf = self._ct.create_unicode_buffer(1024)
                size = self._wt.DWORD(len(buf))
                if self.kernel32.QueryFullProcessImageNameW(handle, 0, buf, self._ct.byref(size)):
                    name = os.path.basename(buf.value).lower()
            finally:
                self.kernel32.CloseHandle(handle)
        self._exe_cache[pid] = name
        return name

    def _cloaked(self, hwnd) -> bool:
        """Hidden by the system (a suspended Store app, another virtual desktop)."""
        if self.dwmapi is None:
            return False
        value = self._ct.c_int(0)
        res = self.dwmapi.DwmGetWindowAttribute(self._wt.HWND(hwnd), DWMWA_CLOAKED,
                                                self._ct.byref(value), self._ct.sizeof(value))
        return res == 0 and value.value != 0

    def windows(self) -> list[Window]:
        u = self.user32
        found: list[Window] = []

        def visit(hwnd, _):
            if not u.IsWindowVisible(hwnd) or u.GetWindow(hwnd, GW_OWNER):
                return True
            length = u.GetWindowTextLengthW(hwnd)
            if length <= 0 or self._cloaked(hwnd):
                return True
            buf = self._ct.create_unicode_buffer(length + 1)
            u.GetWindowTextW(hwnd, buf, length + 1)
            pid = self._wt.DWORD(0)
            u.GetWindowThreadProcessId(hwnd, self._ct.byref(pid))
            if pid.value != self._own_pid:          # never Red's own glow
                found.append(Window(int(hwnd), pid.value, self._exe(pid.value), buf.value))
            return True

        u.EnumWindows(self._enum_proc(visit), 0)   # topmost first
        return found

    def front(self, hwnd: int) -> bool:
        u, k = self.user32, self.kernel32
        if u.IsIconic(hwnd):
            u.ShowWindow(hwnd, SW_RESTORE)
        if u.GetForegroundWindow() == hwnd:
            return True
        # Share input with the window that has the foreground now: then
        # Windows treats Red's request like one from that window.
        me = k.GetCurrentThreadId()
        foreground = u.GetForegroundWindow()
        other = u.GetWindowThreadProcessId(foreground, None) if foreground else 0
        attached = bool(other and other != me and u.AttachThreadInput(me, other, True))
        try:
            u.BringWindowToTop(hwnd)
            u.SetForegroundWindow(hwnd)
        finally:
            if attached:
                u.AttachThreadInput(me, other, False)
        if u.GetForegroundWindow() == hwnd:
            return True
        # The Alt-key trick: while Alt is down, Windows lifts the lock. An
        # unassigned key in between stops the Alt release from opening a menu.
        u.keybd_event(VK_MENU, 0, 0, None)
        u.keybd_event(VK_UNASSIGNED, 0, 0, None)
        u.keybd_event(VK_UNASSIGNED, 0, KEYEVENTF_KEYUP, None)
        try:
            u.SetForegroundWindow(hwnd)
        finally:
            u.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, None)
        return u.GetForegroundWindow() == hwnd
