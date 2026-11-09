"""Timers and reminders that survive a restart.

The app sets `default_scheduler().on_due` to a function that says or prints
the text. A daemon thread calls it when a reminder is due. Reminders are kept
in RED_HOME\\data\\reminders.json, so they're still there after Red restarts.
One that came due while Red was closed is announced as missed when Red starts
again (if it's less than a day late).
"""

from __future__ import annotations

import json
import logging
import os
import threading
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

from .config import red_home

log = logging.getLogger(__name__)

MAX_AHEAD = timedelta(days=7)
MISSED_GRACE = timedelta(days=1)    # older missed reminders are dropped quietly
POLL_SECONDS = 1.0
MAX_PENDING = 100
MAX_TEXT = 200


def reminders_file() -> Path:
    return red_home() / "data" / "reminders.json"


class Scheduler:
    def __init__(self, path: Path | None = None, now: Callable[[], datetime] = datetime.now,
                 start: bool = True):
        self.on_due: Callable[[str], None] | None = None
        self._path = path
        self._now = now
        self._lock = threading.RLock()
        self._wake = threading.Event()
        self._items: dict[str, tuple[datetime, str]] = {}
        self._thread: threading.Thread | None = None
        self._load()
        if start:
            self.start()

    # --- the contract ---------------------------------------------------------

    def add(self, when: datetime, text: str) -> str:
        """Schedule `text` for `when` (local time). Returns the new id."""
        text = " ".join(str(text).split())[:MAX_TEXT]
        if not text:
            raise ValueError("A reminder needs some text")
        when = when.replace(microsecond=0)
        now = self._now()
        if when <= now:
            raise ValueError("That time has already passed")
        if when - now > MAX_AHEAD:
            raise ValueError("Reminders can be at most 7 days ahead")
        with self._lock:
            if len(self._items) >= MAX_PENDING:
                raise ValueError(f"There are already {MAX_PENDING} reminders")
            rid = uuid.uuid4().hex[:8]
            self._items[rid] = (when, text)
            self._save()
        self._wake.set()
        return rid

    def cancel(self, id_or_text: str) -> bool:
        """Cancel by id, or the soonest reminder whose text contains `id_or_text`."""
        key = " ".join(str(id_or_text).lower().split())
        if not key:
            return False
        with self._lock:
            if key in self._items:
                rid = key
            else:
                matches = [(when, rid) for rid, (when, text) in self._items.items()
                           if key in text.lower()]
                if not matches:
                    return False
                rid = min(matches)[1]
            del self._items[rid]
            self._save()
        return True

    def pending(self) -> list[tuple[str, datetime, str]]:
        """(id, when, text), soonest first."""
        with self._lock:
            return sorted(((rid, when, text) for rid, (when, text) in self._items.items()),
                          key=lambda item: item[1])

    # --- running ----------------------------------------------------------------

    def start(self) -> None:
        with self._lock:
            if self._thread is None:
                self._thread = threading.Thread(target=self._run, name="red-scheduler",
                                                daemon=True)
                self._thread.start()

    def tick(self) -> list[str]:
        """Deliver every due reminder now. Returns the texts delivered.

        Due reminders wait while `on_due` is unset, so none is lost before the
        app has wired its voice or console.
        """
        handler = self.on_due
        if handler is None:
            return []
        now = self._now()
        with self._lock:
            due = sorted((when, rid, text) for rid, (when, text) in self._items.items()
                         if when <= now)
            for _, rid, _ in due:
                del self._items[rid]
            if due:
                self._save()
        said = []
        for when, _, text in due:
            if now - when > timedelta(minutes=2):
                text = f"You missed a reminder at {_clock(when)}: {text}"
            try:
                handler(text)
            except Exception:   # noqa: BLE001 - a broken handler mustn't stop the thread
                log.exception("on_due failed for %r", text)
            said.append(text)
        return said

    def _run(self) -> None:
        while True:
            self._wake.wait(POLL_SECONDS)
            self._wake.clear()
            try:
                self.tick()
            except Exception:  # noqa: BLE001
                log.exception("Scheduler tick failed")

    # --- storage ----------------------------------------------------------------

    def _load(self) -> None:
        if self._path is None or not self._path.is_file():
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            items = {}
            for row in data.get("reminders", []):
                when = datetime.fromisoformat(row["when"])
                text = str(row["text"])[:MAX_TEXT]
                if self._now() - when <= MISSED_GRACE:
                    items[str(row["id"])] = (when, text)
        except (OSError, ValueError, KeyError, TypeError) as e:
            log.warning("Ignoring unreadable %s: %s", self._path, e)
            return
        self._items = items

    def _save(self) -> None:
        if self._path is None:
            return
        rows = [{"id": rid, "when": when.isoformat(), "text": text}
                for rid, when, text in self.pending()]
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"reminders": rows}, indent=1), encoding="utf-8")
            os.replace(tmp, self._path)          # never leaves a half-written file
        except OSError as e:
            log.warning("Couldn't save reminders to %s: %s", self._path, e)


def _clock(t: datetime) -> str:
    return t.strftime("%I:%M %p").lstrip("0")


_default: Scheduler | None = None
_default_lock = threading.Lock()


def default_scheduler() -> Scheduler:
    """One scheduler per process, stored under RED_HOME, started on first use."""
    global _default
    with _default_lock:
        if _default is None:
            _default = Scheduler(reminders_file())
        return _default
