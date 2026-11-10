"""notify_when_done: tell the user when an app or a build is finished.

"When VS Code finishes, remind me", "tell me when the build is done". Red
watches the window you're using (its title and the text on the screen, read
with Windows' OCR through red.screen) every 15 seconds and says so when:

- a completion phrase appears ("finished", "done", "completed", "exit code 0",
  or the user's own target text), or
- for two minutes the screen text hasn't changed at all, or
- three hours have passed (then Red stops watching).

Only the window you're using is looked at, and the text read from the screen
stays on this PC. The screen is read only while this tool is watching, and
never saved: red.screen deletes its screenshot straight after the OCR.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from pathlib import Path
from typing import Callable

from .. import config as _config
from .base import Tool, ToolError

log = logging.getLogger(__name__)

POLL_SECONDS = 15.0
STILL_SECONDS = 2 * 60.0
MAX_SECONDS = 3 * 60 * 60.0
MAX_TARGET = 80

_DONE = re.compile(r"\b(?:finished|done|completed|complete|succeeded|success|"
                   r"build succeeded|exit code 0|process exited)\b", re.I)

# What the user calls an app -> what its window title or program is called.
_ALIASES = {
    "vs code": ("visual studio code", "vscode"),
    "vscode": ("visual studio code", "vs code"),
    "visual studio": ("devenv",),
    "terminal": ("windows terminal", "powershell", "cmd"),
    "command prompt": ("cmd",),
    "powershell": ("pwsh", "powershell"),
    "android studio": ("studio64",),
    "command line": ("cmd", "powershell"),
}


def default_reader(cache_dir: Path | None = None) -> Callable[[], object]:
    """Read the window the user is in: title, program and OCR text."""
    from red.screen import read_screen

    folder = cache_dir or (_config.red_home() / "cache")

    def read():
        return read_screen(folder)

    return read


def app_matches(app_name: str, title: str, program: str = "") -> bool:
    """Is this window the app the user named? ('VS Code' is 'Visual Studio Code'.)"""
    haystack = f"{title} {program}".lower()
    key = " ".join(app_name.lower().split())
    if not key:
        return False
    names = (key, key.replace(" ", ""), *_ALIASES.get(key, ()))
    return any(name and name in haystack for name in names)


def _show_notification(title: str, body: str) -> None:
    """A Windows toast (imported here: typed mode needs no Qt)."""
    from red.overlay import show_notification

    show_notification(title, body)


def done_message(app_name: str, target_text: str, reason: str) -> str:
    if reason == "target":
        return f'{app_name} is showing "{target_text}".'
    if reason == "still":
        return f"{app_name} has stopped changing, so it looks done."
    if reason == "timeout":
        return f"I stopped watching {app_name} after three hours."
    return f"{app_name} is done."


class Watch:
    """One app being watched. `tick()` reads the screen once and reports when it's done."""

    def __init__(self, app_name: str, target_text: str = "", *,
                 read: Callable[[], object],
                 on_done: Callable[["Watch", str], None] | None = None,
                 clock: Callable[[], float] = time.monotonic,
                 poll: float = POLL_SECONDS, still_seconds: float = STILL_SECONDS,
                 max_seconds: float = MAX_SECONDS):
        self.app_name = " ".join(app_name.split()) or "the app"
        self.target_text = " ".join(target_text.split())
        self._read = read
        self._on_done = on_done
        self._clock = clock
        self.poll = poll
        self.still_seconds = still_seconds
        self.max_seconds = max_seconds
        self.started_at = clock()
        self.reason: str | None = None
        self._last_text: str | None = None
        self._last_change = self.started_at
        self._cancel = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()

    @property
    def done(self) -> bool:
        return self.reason is not None

    def _finish(self, reason: str) -> str:
        if self.reason is not None:
            return self.reason
        self.reason = reason
        if not self.cancelled and self._on_done is not None:
            try:
                self._on_done(self, reason)
            except Exception:  # noqa: BLE001 - a failed announcement must not crash the watcher
                log.exception("notify_when_done: the announcement failed")
        return reason

    def tick(self) -> str | None:
        """Read the screen once. The completion reason, or None to keep watching."""
        if self.reason is not None:
            return self.reason
        if self.cancelled:
            return None
        now = self._clock()
        if now - self.started_at >= self.max_seconds:
            return self._finish("timeout")
        try:
            info = self._read()
        except Exception as e:  # noqa: BLE001 - no OCR right now; try again next time
            log.warning("notify_when_done: couldn't read the screen: %s", e)
            return None
        title = str(getattr(info, "title", "") or "")
        program = str(getattr(info, "app", "") or "")
        if not app_matches(self.app_name, title, program):
            return None
        lines = list(getattr(info, "lines", []) or [])
        text = "\n".join(lines)
        if self.target_text and self.target_text.lower() in f"{title}\n{text}".lower():
            return self._finish("target")
        if _DONE.search(f"{title}\n{text}"):
            return self._finish("finished")
        if not lines or not getattr(info, "ocr_ok", True):
            return None                       # no screen text this time: not "still"
        if self._last_text is None:
            self._last_text, self._last_change = text, now
        elif text != self._last_text:
            self._last_text, self._last_change = text, now
        elif now - self._last_change >= self.still_seconds:
            return self._finish("still")
        return None

    def _loop(self) -> None:
        while not self._cancel.is_set():
            if self.tick() is not None:
                return
            self._cancel.wait(self.poll)

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, name="red-watch", daemon=True)
        self._thread.start()

    def cancel(self) -> bool:
        """Stop watching. True if it was still watching."""
        if self.reason is not None or self.cancelled:
            self._cancel.set()
            return False
        self._cancel.set()
        return True


class Watchers:
    """The watches Red has running, by app name, and how it tells the user they're done."""

    def __init__(self, *, read: Callable[[], object] | None = None,
                 announce: Callable[[str], None] | None = None,
                 notify: Callable[[str, str], None] | None = None,
                 clock: Callable[[], float] = time.monotonic,
                 poll: float = POLL_SECONDS, still_seconds: float = STILL_SECONDS,
                 max_seconds: float = MAX_SECONDS, autostart: bool = True):
        self._read = read or default_reader()
        self._announce = announce
        self._notify = notify if notify is not None else _show_notification
        self._clock, self._poll = clock, poll
        self._still, self._max = still_seconds, max_seconds
        self.autostart = autostart
        self._watches: dict[str, Watch] = {}
        self._lock = threading.Lock()

    def bind_announce(self, announce: Callable[[str], None] | None) -> None:
        self._announce = announce

    def watch(self, app_name: str, target_text: str = "") -> Watch:
        key = " ".join(app_name.lower().split())
        if not key:
            raise ToolError("Which app should I watch?")
        self.cancel(app_name)
        watch = Watch(app_name, target_text, read=self._read, on_done=self._finished,
                      clock=self._clock, poll=self._poll, still_seconds=self._still,
                      max_seconds=self._max)
        with self._lock:
            self._watches[key] = watch
        if self.autostart:
            watch.start()
        return watch

    def cancel(self, app_name: str = "") -> int:
        """Stop watching `app_name` (or every watch, when empty). Returns how many stopped."""
        key = " ".join(app_name.lower().split())
        with self._lock:
            if not key:
                targets = list(self._watches.values())
                self._watches.clear()
            else:
                targets = [w for k, w in self._watches.items() if k == key or key in k]
                for watch in targets:
                    self._watches.pop(watch.app_name.lower(), None)
        stopped = sum(1 for watch in targets if watch.cancel())
        return stopped

    def pending(self) -> list[Watch]:
        with self._lock:
            return [w for w in self._watches.values() if not w.done]

    def _finished(self, watch: Watch, reason: str) -> None:
        with self._lock:
            self._watches.pop(watch.app_name.lower(), None)
        message = done_message(watch.app_name, watch.target_text, reason)
        log.info("notify_when_done: %s (%s)", message, reason)
        if self._announce is not None:
            try:
                self._announce(message)
            except Exception:  # noqa: BLE001 - the toast still tells them
                log.exception("notify_when_done: couldn't speak the result")
        if self._notify is not None:
            try:
                self._notify("Red", message)
            except Exception:  # noqa: BLE001
                log.exception("notify_when_done: couldn't show the notification")


class NotifyWhenDone(Tool):
    name = "notify_when_done"
    description = ("Tell the user when an app or process finishes, for 'when VS Code finishes, "
                   "remind me' or 'tell me when the build is done'. Watches the app's window "
                   "and text until it says finished, done or completed (or the user's target "
                   "text appears). app_name is the app, e.g. 'VS Code'.")
    args_schema = {
        "type": "object",
        "properties": {
            "app_name": {"type": "string", "minLength": 1, "maxLength": 40,
                         "description": "The app whose work is finishing, e.g. \"VS Code\"."},
            "target_text": {"type": "string", "maxLength": MAX_TARGET,
                            "description": "Optional: a word or line to wait for, e.g. "
                                           "\"Build succeeded\"."},
        },
        "required": ["app_name"],
        "additionalProperties": False,
    }

    def __init__(self, watchers: Watchers | None = None):
        self.watchers = watchers or Watchers()

    def bind_announce(self, announce: Callable[[str], None]) -> None:
        self.watchers.bind_announce(announce)

    def run(self, app_name: str, target_text: str = "") -> str:
        name = " ".join(app_name.split())
        if not name:
            raise ToolError("Which app should I watch?")
        target = " ".join(target_text.split())
        self.watchers.watch(name, target)
        if target:
            return f'OK, I\'ll tell you when {name} shows "{target}".'
        return f"OK, I'll tell you when {name} is done."

    def cancel_watch(self, app_name: str = "") -> str:
        return "Stopped watching." if self.watchers.cancel(app_name) else (
            f"I wasn't watching {app_name}." if app_name else "I wasn't watching anything.")


class CancelWatch(Tool):
    name = "cancel_watch"
    description = ("Stop watching an app for notify_when_done, when the user says 'stop watching "
                   "VS Code' or 'never mind, stop watching'.")
    args_schema = {
        "type": "object",
        "properties": {"app_name": {"type": "string", "maxLength": 40,
                                    "description": "The app to stop watching. Empty stops all."}},
        "additionalProperties": False,
    }

    def __init__(self, watchers: Watchers | None = None):
        self.watchers = watchers or Watchers()

    def run(self, app_name: str = "") -> str:
        name = " ".join(app_name.split())
        if not name:
            count = self.watchers.cancel()
            return "Stopped watching." if count else "I wasn't watching anything."
        if self.watchers.cancel(name):
            return f"Stopped watching {name}."
        return f"I wasn't watching {name}."
