"""What the companion's right-click menu does, as plain functions (no Qt, so tests need no window).

- `remind(text, when)`: a reminder through the same scheduler the "set a reminder" tool uses, so it is
  spoken when due. `when` is what a person would type: "15:30", "3pm", "in 20 minutes", "tomorrow 9am".
- `add_task`, `list_tasks`, `set_done`, `remove_task`: the same to-do list the `todo` plugin keeps
  (RED_HOME\\memory\\todo.json), so a task added by voice shows in the menu's list and the other way round.
- `talk()` and `play_music()`: handed in by the voice loop (listen now; pick a song like the idle life does).

`remind` can be handed lane 2's `red.actions.remind` (the set_reminder tool); without it, this module parses
the time itself and uses the scheduler directly.
"""

from __future__ import annotations

import json
import re
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

MAX_TEXT = 200
MAX_TASKS = 200


# --------------------------------------------------------------------------
# Times a person would type
# --------------------------------------------------------------------------

_UNITS = {"s": 1, "sec": 1, "secs": 1, "second": 1, "seconds": 1,
          "m": 60, "min": 60, "mins": 60, "minute": 60, "minutes": 60,
          "h": 3600, "hr": 3600, "hrs": 3600, "hour": 3600, "hours": 3600}
_CLOCK = re.compile(r"^(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm|a\.m\.|p\.m\.)?$")


def _clock(text: str) -> tuple[int, int] | None:
    m = _CLOCK.match(text.strip())
    if not m:
        return None
    hour, minute, ampm = int(m.group(1)), int(m.group(2) or 0), (m.group(3) or "").replace(".", "")
    if minute > 59:
        return None
    if ampm:
        if not 1 <= hour <= 12:
            return None
        hour = hour % 12 + (12 if ampm == "pm" else 0)
    elif m.group(2) is None:
        return None                    # a bare "5" is too unclear to guess: "5 min"? "5 o'clock"?
    if hour > 23:
        return None
    return hour, minute


def parse_when(text: str, now: datetime) -> datetime | None:
    """A time from words: 'in 20 minutes', '45 min', 'an hour', 'half an hour', '15:30', '3pm',
    'at 9:15 am', 'tomorrow 9am', 'tomorrow'. None if it can't be read."""
    t = " ".join((text or "").lower().replace(",", " ").split())
    if not t:
        return None
    t = t.removeprefix("in ").strip()
    if t in ("an hour", "one hour", "1 hour", "hour"):
        return now + timedelta(hours=1)
    if t in ("half an hour", "half hour", "30 minutes"):
        return now + timedelta(minutes=30)
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*([a-z]+)", t)
    if m and m.group(2) in _UNITS:
        seconds = float(m.group(1)) * _UNITS[m.group(2)]
        return now + timedelta(seconds=seconds) if seconds > 0 else None
    day = 0
    if t.startswith("tomorrow"):
        day, t = 1, t.removeprefix("tomorrow").strip()
        if not t:
            return (now + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
    elif t.startswith("today"):
        t = t.removeprefix("today").strip()
    clock = _clock(t)
    if clock is None:
        return None
    when = (now + timedelta(days=day)).replace(hour=clock[0], minute=clock[1], second=0, microsecond=0)
    if when <= now and day == 0:
        when += timedelta(days=1)       # "9am" at 10pm means tomorrow
    return when


# --------------------------------------------------------------------------
# The to-do list
# --------------------------------------------------------------------------

@dataclass
class Task:
    id: str                    # "added|text": the todo plugin keeps no ids
    text: str
    done: bool = False
    added: str = ""


class MenuActions:
    def __init__(self, home: Path, *, scheduler: Callable[[], object] | None = None,
                 talk: Callable[[], object] | None = None, music: Callable[[], str | None] | None = None,
                 remind: Callable[[str, str], str] | None = None,
                 now: Callable[[], datetime] = datetime.now):
        self.path = Path(home) / "memory" / "todo.json"
        self._remind = remind
        self._scheduler = scheduler
        self._talk = talk
        self._music = music
        self._now = now
        self._lock = threading.Lock()

    # --- reminders -------------------------------------------------------------

    def remind(self, text: str, when: str) -> str:
        """Set a reminder. Returns what to tell the user; raises ValueError with a message to show."""
        text = " ".join((text or "").split())[:MAX_TEXT]
        if not text:
            raise ValueError("What should I remind you about?")
        if self._remind is not None:                      # lane 2's version: the set_reminder tool
            from ..tools.base import ToolError
            try:
                return self._remind(text, when)
            except ToolError as e:
                raise ValueError(str(e)) from e
        now = self._now()
        at = parse_when(when, now)
        if at is None:
            raise ValueError("I couldn't read that time. Try 15:30, 3pm or in 20 minutes.")
        if self._scheduler is None:
            from .. import scheduler as _scheduler
            source = _scheduler.default_scheduler
        else:
            source = self._scheduler
        source().add(at, f"Reminder: {text.rstrip('.')}.")           # ValueError for the past or beyond 7 days
        from ..tools.system import format_clock
        return f"Okay, I'll remind you at {format_clock(at, now)}."

    # --- tasks -----------------------------------------------------------------

    # The file is the todo plugin's: a list of {"text", "added", "done", "finished"}. Anything else in an
    # item is kept as it was.

    def _items(self) -> list[dict]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return [d for d in data if isinstance(d, dict) and d.get("text")] if isinstance(data, list) else []
        except (OSError, ValueError):
            return []

    def _write_items(self, items: list[dict]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".part")
        tmp.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self.path)

    @staticmethod
    def _id(item: dict) -> str:
        return f"{item.get('added', '')}|{item['text']}"

    def _stamp(self) -> str:
        return self._now().isoformat(timespec="seconds")

    def add_task(self, text: str) -> Task:
        text = " ".join((text or "").split())[:MAX_TEXT]
        if not text:
            raise ValueError("What's the task?")
        with self._lock:
            items = self._items()
            if len([i for i in items if not i.get("done")]) >= MAX_TASKS:
                raise ValueError("The list is full. Finish or remove some tasks first.")
            item = {"text": text, "added": self._stamp(), "done": False}
            self._write_items(items + [item])
            return Task(self._id(item), text, False, item["added"])

    def list_tasks(self, include_done: bool = True) -> list[Task]:
        with self._lock:
            items = self._items()
        tasks = [Task(self._id(i), str(i["text"]), bool(i.get("done")), str(i.get("added", ""))) for i in items]
        return [t for t in tasks if include_done or not t.done]

    def set_done(self, task_id: str, done: bool = True) -> bool:
        with self._lock:
            items = self._items()
            for item in items:
                if self._id(item) == task_id:
                    item["done"] = done
                    if done:
                        item["finished"] = self._stamp()
                    else:
                        item.pop("finished", None)
                    self._write_items(items)
                    return True
        return False

    def remove_task(self, task_id: str) -> bool:
        with self._lock:
            items = self._items()
            kept = [i for i in items if self._id(i) != task_id]
            if len(kept) == len(items):
                return False
            self._write_items(kept)
            return True

    def clear_done(self) -> int:
        with self._lock:
            items = self._items()
            kept = [i for i in items if not i.get("done")]
            self._write_items(kept)
            return len(items) - len(kept)

    # --- talking and music -------------------------------------------------------

    @property
    def can_talk(self) -> bool:
        return self._talk is not None

    @property
    def can_play_music(self) -> bool:
        return self._music is not None

    def talk(self) -> bool:
        """Start listening, as if the hotkey had been pressed."""
        if self._talk is None:
            return False
        self._talk()
        return True

    def play_music(self) -> str | None:
        """Play a song the way the idle life does. Returns the line to show, or None if it can't."""
        if self._music is None:
            return None
        return self._music()
