"""Small desktop actions the app plugins share (plan.md B3): front an app's window,
check which app is in front, put text on the clipboard, press a key combination.

All are signed user32 calls through ctypes. Keys are pressed only from fixed
combinations a plugin or the user's own config names ("ctrl+alt+i"), never
from model text, and text reaches an app only through the clipboard (the user's
own words, read back first by the tool that uses it).
"""

from __future__ import annotations

import logging
import sys
import time
from typing import Callable

log = logging.getLogger(__name__)

VK = {"ctrl": 0x11, "control": 0x11, "alt": 0x12, "shift": 0x10, "win": 0x5B, "enter": 0x0D,
      "return": 0x0D, "tab": 0x09, "esc": 0x1B, "escape": 0x1B, "space": 0x20, "backspace": 0x08,
      "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27, "home": 0x24, "end": 0x23,
      "pageup": 0x21, "pagedown": 0x22, "delete": 0x2E, "/": 0xBF, ";": 0xBA, ",": 0xBC, ".": 0xBE,
      "`": 0xC0, "[": 0xDB, "]": 0xDD, "-": 0xBD, "=": 0xBB}
VK.update({f"f{n}": 0x6F + n for n in range(1, 13)})
KEYUP = 0x0002


def parse_keys(combo: str) -> list[int]:
    """'ctrl+shift+m' -> virtual-key codes. Raises ValueError for anything unknown."""
    codes = []
    for part in combo.lower().replace(" ", "").split("+"):
        if part in VK:
            codes.append(VK[part])
        elif len(part) == 1 and part.isalnum():
            codes.append(ord(part.upper()))
        else:
            raise ValueError(f"Unknown key {part!r} in {combo!r}")
    if not codes:
        raise ValueError("No keys")
    return codes


def press(combo: str) -> None:
    """Press and release a combination ('ctrl+v', 'enter')."""
    codes = parse_keys(combo)
    if sys.platform != "win32":
        return
    import ctypes
    user32 = ctypes.windll.user32
    for code in codes:
        user32.keybd_event(code, 0, 0, 0)
    for code in reversed(codes):
        user32.keybd_event(code, 0, KEYUP, 0)
    time.sleep(0.05)


def set_clipboard(text: str) -> None:
    """Put text on the Windows clipboard (CF_UNICODETEXT)."""
    if sys.platform != "win32":
        return
    import ctypes
    from ctypes import wintypes
    user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
    kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
    kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    data = text.encode("utf-16-le") + b"\x00\x00"
    for _ in range(10):
        if user32.OpenClipboard(None):
            break
        time.sleep(0.05)
    else:
        raise OSError("The clipboard is busy")
    try:
        user32.EmptyClipboard()
        handle = kernel32.GlobalAlloc(0x0002, len(data))          # GMEM_MOVEABLE
        pointer = kernel32.GlobalLock(handle)
        ctypes.memmove(pointer, data, len(data))
        kernel32.GlobalUnlock(handle)
        if not user32.SetClipboardData(13, handle):              # the system owns it now
            raise OSError("Couldn't set the clipboard")
    finally:
        user32.CloseClipboard()


def _desktop():
    from .windows import Win32Desktop
    return Win32Desktop()


def foreground_exe() -> str:
    """The lower-case exe name of the window in front ('' if unknown)."""
    if sys.platform != "win32":
        return ""
    import ctypes
    hwnd = ctypes.windll.user32.GetForegroundWindow()
    try:
        for w in _desktop().windows():
            if w.hwnd == hwnd:
                return w.exe
    except Exception:  # noqa: BLE001
        log.exception("Couldn't read the foreground window")
    return ""


def front_app(exes: set[str], wait: float = 8.0, title: str = "",
              sleep: Callable[[float], None] = time.sleep) -> bool:
    """Wait up to `wait` seconds for a window of one of `exes` (lower case) and bring it to front."""
    if sys.platform != "win32":
        return False
    exes = {e.lower() for e in exes}
    deadline = time.monotonic() + wait
    try:
        desktop = _desktop()
    except Exception:  # noqa: BLE001
        log.exception("Can't read the desktop's windows")
        return False
    while True:
        windows = [w for w in desktop.windows() if w.exe in exes
                   and (not title or title.lower() in w.title.lower())]
        if windows:
            ok = desktop.front(windows[0].hwnd)
            if ok:
                sleep(0.3)                 # let it take the keyboard
            return ok
        if time.monotonic() >= deadline:
            return False
        sleep(0.25)


class Desk:
    """The actions above, as one object a tool can take (tests pass a fake)."""

    press = staticmethod(press)
    set_clipboard = staticmethod(set_clipboard)
    foreground_exe = staticmethod(foreground_exe)
    front_app = staticmethod(front_app)

    @staticmethod
    def launch(args: list[str], cwd: str | None = None) -> int:
        """Start a program with a list of arguments (never a shell). Returns its pid."""
        import subprocess
        return subprocess.Popen(args, cwd=cwd, close_fds=True).pid

    @staticmethod
    def open_uri(uri: str) -> None:
        """Hand a link (whatsapp://, discord://, spotify:) to the app Windows has for it."""
        import os
        os.startfile(uri)  # noqa: S606 - a fixed scheme built by the plugin, not model text
