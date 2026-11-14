"""Bring the window Red just opened to the front.

Red usually runs hidden, and Windows doesn't let a background process push
a window in front of what you're using (the "foreground lock"): a new Edge
window would only flash in the taskbar. So after open_app, open_folder,
open_url or play_online starts something, Red waits up to about 5 seconds
for its top-level window and brings it to the front:

1. Snapshot the visible top-level windows before launching.
2. After launching, look for a new window from the same process, program or
   with the expected title. Browsers often open a tab in a window that's
   already there, so for a browser Red fronts the window whose title shows
   the page (it has the site's name, like "YouTube"), or else one whose title
   changed after the launch. A browser window whose title never changed
   isn't showing the page, so it's never fronted.
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
# A browser window whose title changed but doesn't name the site yet is
# fronted after this long (some pages never put the site's name in the title).
CHANGED_AFTER_SECONDS = 2.5

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
    # Where it is on the screen, in physical pixels (left, top, right, bottom): the visible frame
    # (DWM's extended frame bounds, without the invisible resize border), or GetWindowRect.
    rect: tuple[int, int, int, int] | None = None
    minimised: bool = False
    maximised: bool = False
    cls: str = ""     # the window class, e.g. "Chrome_WidgetWin_1"


@dataclass
class Target:
    """What the launched thing's window looks like. Any one of these is enough."""

    exes: frozenset[str] = frozenset()
    pids: set[int] = field(default_factory=set)
    titles: tuple[str, ...] = ()      # lower case words expected in the title
    browser: bool = False             # the page may open as a tab in an existing window

    def matches(self, w: Window) -> bool:
        title = w.title.lower()
        return (w.pid in self.pids or w.exe in self.exes
                or any(t and t in title for t in self.titles))

    def shows_page(self, w: Window) -> bool:
        """Browsers: the title has the site's name (or the search words)."""
        title = w.title.lower()
        return any(t and t in title for t in self.titles)


class Desktop(Protocol):
    def windows(self) -> list[Window]: ...      # visible top-level windows, topmost first
    def front(self, hwnd: int) -> bool: ...


class FrontOps(Protocol):
    """The plain Win32 calls that wake a window. Win32Desktop is one; tests use a fake."""

    def is_visible(self, hwnd: int) -> bool: ...
    def is_iconic(self, hwnd: int) -> bool: ...
    def show(self, hwnd: int, command: int) -> None: ...
    def update(self, hwnd: int) -> None: ...
    def redraw(self, hwnd: int) -> None: ...
    def foreground(self) -> int: ...
    def thread_of(self, hwnd: int) -> int: ...
    def current_thread(self) -> int: ...
    def attach(self, mine: int, other: int, on: bool) -> bool: ...
    def bring_to_top(self, hwnd: int) -> None: ...
    def set_foreground(self, hwnd: int) -> None: ...
    def press_alt(self) -> None: ...
    def release_alt(self) -> None: ...


# A restored, background-throttled Chrome can come to the front before it has
# painted, which leaves a blank white page. These give the renderer a moment
# and then ask Windows to paint the window again.
REPAINT_SETTLE_SECONDS = 0.06
SW_SHOW = 5


def front_window(ops: FrontOps, hwnd: int, *, settle: float = REPAINT_SETTLE_SECONDS,
                 sleep: Callable[[float], None] = time.sleep) -> bool:
    """Bring a window to the front, waking it first if it was minimised or hidden.

    A window that was minimised (or hidden behind another virtual desktop) may
    be throttled by its program and never paint: YouTube then shows a blank
    page when Chrome comes back. So restore it, paint it once, front it, then
    paint it again after a short yield.
    """
    woken = False
    if not ops.is_visible(hwnd):
        ops.show(hwnd, SW_SHOW)
        woken = True
    if ops.is_iconic(hwnd):
        ops.show(hwnd, SW_RESTORE)
        woken = True
    if woken:
        ops.update(hwnd)                 # paint the client area before it's fronted
    fronted = _activate(ops, hwnd)
    if fronted and woken:
        if settle:
            sleep(settle)                # let the compositor catch up
        ops.redraw(hwnd)                 # RedrawWindow + DwmFlush: no blank page
    return fronted


def _activate(ops: FrontOps, hwnd: int) -> bool:
    """SetForegroundWindow past the foreground lock, with the Alt-key trick as the backup."""
    if ops.foreground() == hwnd:
        return True
    # Share input with the window that has the foreground now: then
    # Windows treats Red's request like one from that window.
    me = ops.current_thread()
    foreground = ops.foreground()
    other = ops.thread_of(foreground) if foreground else 0
    attached = bool(other and other != me and ops.attach(me, other, True))
    try:
        ops.bring_to_top(hwnd)
        ops.set_foreground(hwnd)
    finally:
        if attached:
            ops.attach(me, other, False)
    if ops.foreground() == hwnd:
        return True
    # The Alt-key trick: while Alt is down, Windows lifts the lock. An
    # unassigned key in between stops the Alt release from opening a menu.
    ops.press_alt()
    try:
        ops.set_foreground(hwnd)
    finally:
        ops.release_alt()
    return ops.foreground() == hwnd


def app_target(exe: str | None = None, title: str = "", pid: int | None = None) -> Target:
    exes = frozenset({os.path.basename(exe).lower()}) if exe else frozenset()
    return Target(exes=exes, pids={pid} if pid else set(),
                  titles=(title.strip().lower(),) if title.strip() else ())


def folder_target(name: str) -> Target:
    """A File Explorer window showing the folder `name`."""
    return Target(titles=(name.strip().lower(),))


def browser_target(exe: str | None = None, page: tuple[str, ...] | str = ()) -> Target:
    """A browser window showing a page.

    exe is the browser Red started ("chrome.exe"); None means the Windows
    default (or any browser, if Windows doesn't say which). page is the words
    the page's title should have: the site's name ("youtube") or the search.
    """
    exe = exe or default_browser_exe()
    words = (page,) if isinstance(page, str) else page
    return Target(exes=frozenset({exe.lower()}) if exe else BROWSERS,
                  titles=tuple(t.strip().lower() for t in words if t.strip()), browser=True)


# Second-level names under a country domain: bbc.co.uk -> bbc.
_SECOND_LEVEL = {"co", "com", "org", "net", "ac", "gov", "edu"}


def site_name(host: str) -> str:
    """'www.youtube.com' -> 'youtube', 'en.wikipedia.org' -> 'wikipedia', 'bbc.co.uk' -> 'bbc'.

    Empty when it's too short to recognise in a title ('x.com').
    """
    labels = [p for p in host.lower().strip(".").split(".") if p]
    if len(labels) >= 3 and len(labels[-1]) == 2 and labels[-2] in _SECOND_LEVEL:
        labels = labels[:-1]
    name = labels[-2] if len(labels) >= 2 else (labels[0] if labels else "")
    return name if len(name) >= 3 else ""


_URL_CHOICE = r"Software\Microsoft\Windows\Shell\Associations\UrlAssociations\https"


def default_browser_exe(assoc: Callable[[], str | None] | None = None,
                        prog_ids: Callable[[], list[str]] | None = None) -> str | None:
    """The program Windows opens https links with, e.g. "chrome.exe".

    Asks the shell first (AssocQueryStringW), which knows the real answer.
    Otherwise the registry: newer Windows 11 builds keep the choice in
    UserChoiceLatest\\ProgId and leave the old UserChoice key stale. On the
    developer's PC UserChoice still said Edge while links opened in Chrome,
    so Red fronted an idle Edge window over the YouTube it had opened.
    """
    if sys.platform != "win32" and assoc is None and prog_ids is None:
        return None
    exe = (assoc or _assoc_https_exe)()
    if exe:
        name = os.path.basename(exe).lower()
        if name in BROWSERS:
            return name
    for prog_id in (prog_ids or _https_prog_ids)():
        for prefix, name in _PROG_IDS:
            if prog_id.startswith(prefix):
                return name
    return None


def _assoc_https_exe() -> str | None:
    """The shell's https handler program, through shlwapi's AssocQueryStringW."""
    try:
        import ctypes
        from ctypes import wintypes
        shlwapi = ctypes.WinDLL("shlwapi")
        query = shlwapi.AssocQueryStringW
        query.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR,
                          wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
        query.restype = ctypes.c_long
        ASSOCF_IS_PROTOCOL, ASSOCSTR_EXECUTABLE = 0x1000, 2
        buf = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(len(buf))
        if query(ASSOCF_IS_PROTOCOL, ASSOCSTR_EXECUTABLE, "https", "open", buf,
                 ctypes.byref(size)) == 0:
            return buf.value or None
    except (OSError, AttributeError):
        pass
    return None


def _https_prog_ids() -> list[str]:
    """ProgIds for https, the newest place first."""
    found = []
    try:
        import winreg
    except ImportError:
        return found
    for sub in (r"\UserChoiceLatest\ProgId", r"\UserChoice"):
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _URL_CHOICE + sub) as key:
                value, _ = winreg.QueryValueEx(key, "ProgId")
        except OSError:
            continue
        if isinstance(value, str) and value:
            found.append(value)
    return found


class Watcher:
    """Made just before launching. Calling it waits for the window and fronts it."""

    def __init__(self, target: Target, desktop: Desktop, *, wait: float = WAIT_SECONDS,
                 clock: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] = time.sleep):
        self.target = target
        self._desktop = desktop
        self._wait, self._clock, self._sleep = wait, clock, sleep
        # Each window's title before launching: a browser window that shows the
        # new page has a new title (or is a new window).
        self._before = {w.hwnd: w.title for w in desktop.windows()}
        self._changed: set[int] = set()

    def add_pid(self, pid: int | None) -> None:
        """The launched process, once it exists (open_app with Popen)."""
        if pid:
            self.target.pids.add(pid)

    def __call__(self) -> bool:
        start = self._clock()
        while True:
            now = self._desktop.windows()
            waited = self._clock() - start
            if self.target.browser:
                found = self._browser_window(now, waited)
                if found:
                    return self._front(*found)
            else:
                new = [w for w in now if w.hwnd not in self._before and self.target.matches(w)]
                if new:
                    return self._front(new[0], "new")
            if waited >= self._wait:
                log.info("No window showed the page for %s; fronting nothing", self.target)
                return False
            self._sleep(POLL_SECONDS)

    def _browser_window(self, now: list[Window], waited: float) -> tuple[Window, str] | None:
        """The browser window showing the page, once it's clear which one that is."""
        for w in now:
            if w.exe in self.target.exes and self._before.get(w.hwnd) != w.title:
                self._changed.add(w.hwnd)          # new, or its title changed: once is enough
        changed = [w for w in now if w.hwnd in self._changed]       # topmost first
        page = [w for w in changed if self.target.shows_page(w)]
        if page:
            return page[0], "page"
        if changed and waited >= CHANGED_AFTER_SECONDS:
            return changed[0], "changed"
        return None

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
DWMWA_EXTENDED_FRAME_BOUNDS = 9
DESKTOP_CLASSES = frozenset({"Progman", "WorkerW"})        # the desktop's own windows
SHELL_CLASSES = DESKTOP_CLASSES | {"Shell_TrayWnd", "Shell_SecondaryTrayWnd"}
DESKTOP_SWITCHDESKTOP = 0x0100
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
        u.UpdateWindow.argtypes = [wintypes.HWND]
        u.UpdateWindow.restype = wintypes.BOOL
        u.RedrawWindow.argtypes = [wintypes.HWND, ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT]
        u.RedrawWindow.restype = wintypes.BOOL
        u.InvalidateRect.argtypes = [wintypes.HWND, ctypes.c_void_p, wintypes.BOOL]
        u.InvalidateRect.restype = wintypes.BOOL
        u.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
        u.IsZoomed.argtypes = [wintypes.HWND]
        u.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        u.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        u.OpenInputDesktop.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        u.OpenInputDesktop.restype = wintypes.HANDLE
        u.SwitchDesktop.argtypes = [wintypes.HANDLE]
        u.CloseDesktop.argtypes = [wintypes.HANDLE]
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

    def rect(self, hwnd) -> tuple[int, int, int, int] | None:
        """The visible frame of a window (physical pixels): DWM's bounds, else GetWindowRect."""
        r = self._wt.RECT()
        if self.dwmapi is not None:
            res = self.dwmapi.DwmGetWindowAttribute(self._wt.HWND(hwnd), DWMWA_EXTENDED_FRAME_BOUNDS,
                                                    self._ct.byref(r), self._ct.sizeof(r))
            if res == 0 and r.right > r.left:
                return (r.left, r.top, r.right, r.bottom)
        if self.user32.GetWindowRect(hwnd, self._ct.byref(r)):
            return (r.left, r.top, r.right, r.bottom)
        return None

    def class_name(self, hwnd) -> str:
        buf = self._ct.create_unicode_buffer(128)
        self.user32.GetClassNameW(hwnd, buf, 128)
        return buf.value

    def _window(self, hwnd, title: str, pid: int) -> Window:
        u = self.user32
        return Window(int(hwnd), pid, self._exe(pid), title, self.rect(hwnd), bool(u.IsIconic(hwnd)),
                      bool(u.IsZoomed(hwnd)), self.class_name(hwnd))

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
                found.append(self._window(hwnd, buf.value, pid.value))
            return True

        u.EnumWindows(self._enum_proc(visit), 0)   # topmost first
        return found

    def foreground(self) -> Window | None:
        """The window in front (with its frame), or None. Red's own windows count as nothing."""
        u = self.user32
        hwnd = u.GetForegroundWindow()
        if not hwnd:
            return None
        pid = self._wt.DWORD(0)
        u.GetWindowThreadProcessId(hwnd, self._ct.byref(pid))
        if pid.value == self._own_pid:
            return None
        length = max(0, u.GetWindowTextLengthW(hwnd))
        buf = self._ct.create_unicode_buffer(length + 1)
        u.GetWindowTextW(hwnd, buf, length + 1)
        return self._window(hwnd, buf.value, pid.value)

    def screen_locked(self) -> bool:
        """True while the lock screen is up: the input desktop can't be switched to from here."""
        u = self.user32
        desk = u.OpenInputDesktop(0, False, DESKTOP_SWITCHDESKTOP)
        if not desk:
            return True
        try:
            return not u.SwitchDesktop(desk)
        finally:
            u.CloseDesktop(desk)


def desktop_in_front(foreground: Window | None, windows: list[Window]) -> bool:
    """The desktop is what the user sees: its own window is in front, or every app window is minimised.

    `foreground` and `windows` come from a Desktop (Win32Desktop, or a fake in tests). The taskbar in
    front (a click on it) counts as the desktop only when nothing else is open."""
    apps = [w for w in windows if w.cls not in SHELL_CLASSES]
    if foreground is not None and foreground.cls in DESKTOP_CLASSES:
        return True
    if all(w.minimised for w in apps):
        return True
    return foreground is not None and foreground.cls in SHELL_CLASSES and not apps


_desktop: Win32Desktop | None = None


def win32() -> Win32Desktop | None:
    """One shared Win32Desktop, or None off Windows (or if user32 can't be loaded)."""
    global _desktop
    if _desktop is None and sys.platform == "win32":
        try:
            _desktop = Win32Desktop()
        except Exception:  # noqa: BLE001
            log.exception("Can't read the desktop's windows")
    return _desktop

    def front(self, hwnd: int) -> bool:
        return front_window(_Win32Front(self), hwnd)


class _Win32Front:
    """Win32Desktop's plain Win32 calls, for front_window()."""

    REDRAW_FLAGS = 0x0001 | 0x0004 | 0x0080 | 0x0100   # INVALIDATE | ERASE | ALLCHILDREN | UPDATENOW

    def __init__(self, desktop: Win32Desktop):
        self._u = desktop.user32
        self._k = desktop.kernel32
        self._dwm = desktop.dwmapi

    def is_visible(self, hwnd: int) -> bool:
        return bool(self._u.IsWindowVisible(hwnd))

    def is_iconic(self, hwnd: int) -> bool:
        return bool(self._u.IsIconic(hwnd))

    def show(self, hwnd: int, command: int) -> None:
        self._u.ShowWindow(hwnd, command)

    def update(self, hwnd: int) -> None:
        self._u.UpdateWindow(hwnd)

    def redraw(self, hwnd: int) -> None:
        if not self._u.RedrawWindow(hwnd, None, None, self.REDRAW_FLAGS):
            self._u.InvalidateRect(hwnd, None, True)
            self._u.UpdateWindow(hwnd)
        flush = getattr(self._dwm, "DwmFlush", None) if self._dwm is not None else None
        if flush is not None:
            flush()                       # wait until the compositor has the new frame

    def foreground(self) -> int:
        return int(self._u.GetForegroundWindow() or 0)

    def thread_of(self, hwnd: int) -> int:
        if not hwnd:
            return 0
        return int(self._u.GetWindowThreadProcessId(hwnd, None))

    def current_thread(self) -> int:
        return int(self._k.GetCurrentThreadId())

    def attach(self, mine: int, other: int, on: bool) -> bool:
        return bool(self._u.AttachThreadInput(mine, other, on))

    def bring_to_top(self, hwnd: int) -> None:
        self._u.BringWindowToTop(hwnd)

    def set_foreground(self, hwnd: int) -> None:
        self._u.SetForegroundWindow(hwnd)

    def press_alt(self) -> None:
        u = self._u
        u.keybd_event(VK_MENU, 0, 0, None)
        u.keybd_event(VK_UNASSIGNED, 0, 0, None)
        u.keybd_event(VK_UNASSIGNED, 0, KEYEVENTF_KEYUP, None)

    def release_alt(self) -> None:
        self._u.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, None)
