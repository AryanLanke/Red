"""Timers and reminders, built on red.scheduler.

Times are local. A reminder can't be in the past or more than 7 days ahead.
The scheduler is reached lazily, so building the registry starts no thread.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Callable

from .. import scheduler as _scheduler
from .base import Tool, ToolError
from .system import format_clock, format_duration

MAX_MINUTES = 7 * 24 * 60
DAYS = ("today", "tomorrow", "monday", "tuesday", "wednesday", "thursday", "friday",
        "saturday", "sunday")
_TIMER = re.compile(r"^Your (.+) timer is done\.$")
_REMINDER = "Reminder: "

SchedulerSource = Callable[[], "_scheduler.Scheduler"]


class _ReminderTool(Tool):
    def __init__(self, scheduler: SchedulerSource = _scheduler.default_scheduler,
                 now: Callable[[], datetime] = datetime.now):
        self._scheduler = scheduler
        self._now = now

    def _add(self, when: datetime, text: str) -> None:
        try:
            self._scheduler().add(when, text)
        except ValueError as e:
            raise ToolError(f"{e}.") from e

    def _when(self, when: datetime) -> str:
        return format_clock(when, self._now())


def describe_item(text: str) -> str:
    """'Your 10 minute timer is done.' -> 'the 10 minute timer'; reminders -> their text."""
    m = _TIMER.match(text)
    if m:
        return f"the {m.group(1)} timer"
    return text[len(_REMINDER):].rstrip(".") if text.startswith(_REMINDER) else text


class SetTimer(_ReminderTool):
    name = "set_timer"
    description = "Start a countdown timer, for example 'set a timer for 10 minutes'."
    args_schema = {
        "type": "object",
        "properties": {
            "minutes": {"type": "integer", "minimum": 0, "maximum": MAX_MINUTES,
                        "description": "Convert hours to minutes."},
            "seconds": {"type": "integer", "minimum": 0, "maximum": 3600},
            "label": {"type": "string", "maxLength": 40,
                      "description": "What the timer is for, if the user said (pasta)."},
        },
        "additionalProperties": False,
    }

    def run(self, minutes: int = 0, seconds: int = 0, label: str = "") -> str:
        total = minutes * 60 + seconds
        if total <= 0:
            raise ToolError("How long should the timer be?")
        if total > MAX_MINUTES * 60:
            raise ToolError("Timers can be at most 7 days long.")
        length = _length(minutes, seconds)
        label = " ".join(label.split()).lower()
        # "10 minute timer", not "10 minutes timer"
        name = (label if label and label not in {"timer", "a timer"}
                else re.sub(r"\b(minute|hour|second)s\b", r"\1", length))
        when = self._now().replace(microsecond=0) + timedelta(seconds=total)
        self._add(when, f"Your {name} timer is done.")
        return f"Timer set for {length}. It ends at {self._when(when)}."


def _length(minutes: int, seconds: int) -> str:
    minutes, extra = minutes + seconds // 60, seconds % 60
    if minutes and extra:
        return f"{format_duration(minutes)} and {extra} second{'s' if extra != 1 else ''}"
    if minutes:
        return format_duration(minutes)
    return f"{extra} second{'s' if extra != 1 else ''}"


class SetReminder(_ReminderTool):
    name = "set_reminder"
    description = ("Remind the user of something at a time of day or after some minutes, "
                   "for example 'remind me at 3 pm to call mom' or 'remind me in 20 minutes "
                   "to check the oven'.")
    args_schema = {
        "type": "object",
        "properties": {
            "text": {"type": "string", "minLength": 1, "maxLength": 200,
                     "description": "What to remind about, for example 'call mom'."},
            "time": {"type": "string", "pattern": "^([01][0-9]|2[0-3]):[0-5][0-9]$",
                     "description": "24-hour local time, for example 15:00 for 3 pm."},
            "day": {"type": "string", "enum": list(DAYS)},
            "in_minutes": {"type": "integer", "minimum": 1, "maximum": MAX_MINUTES},
        },
        "required": ["text"],
        "additionalProperties": False,
    }

    def resolve(self, time: str | None = None, day: str | None = None,
                in_minutes: int | None = None) -> datetime:
        now = self._now().replace(microsecond=0)
        if in_minutes:
            return now + timedelta(minutes=in_minutes)
        if not time:
            raise ToolError("When should I remind you?")
        hour, minute = (int(x) for x in time.split(":"))
        at = now.replace(hour=hour, minute=minute, second=0)
        if day in (None, "", "today"):
            if at <= now:
                if day == "today":
                    raise ToolError(f"{format_clock(at, now)} has already passed today.")
                at += timedelta(days=1)       # "at 9 am" said in the evening means tomorrow
        elif day == "tomorrow":
            at += timedelta(days=1)
        else:
            ahead = (DAYS.index(day) - 2 - now.weekday()) % 7
            at += timedelta(days=ahead)
            if at <= now:
                at += timedelta(days=7)
        return at

    def run(self, text: str, time: str | None = None, day: str | None = None,
            in_minutes: int | None = None) -> str:
        what = " ".join(text.split()).rstrip(".")
        what = re.sub(r"^(to|that)\s+", "", what, flags=re.I)
        if not what:
            raise ToolError("What should I remind you about?")
        when = self.resolve(time, day, in_minutes)
        self._add(when, f"{_REMINDER}{what}.")
        return f"OK, I'll remind you at {self._when(when)} to {what}."


class ListReminders(_ReminderTool):
    name = "list_reminders"
    description = "Say which timers and reminders are set."
    args_schema = {"type": "object", "properties": {}, "additionalProperties": False}

    def __init__(self, scheduler: SchedulerSource = _scheduler.default_scheduler,
                 now: Callable[[], datetime] = datetime.now):
        super().__init__(scheduler, now)
        self.last_details = ""

    def run(self) -> str:
        items = self._scheduler().pending()
        self.last_details = "\n".join(f"{self._when(when)}: {describe_item(text)}"
                                      for _, when, text in items)
        if not items:
            return "You don't have any timers or reminders."
        spoken = "; ".join(f"{describe_item(text)} at {self._when(when)}"
                           for _, when, text in items[:3])
        more = f"; and {len(items) - 3} more" if len(items) > 3 else ""
        count = "one" if len(items) == 1 else str(len(items))
        return f"You have {count}: {spoken}{more}."


def _reminder_key(text: str) -> str:
    """'my reminder to call mom' -> 'call mom'."""
    text = re.sub(r"[^\w' ]+", " ", text.lower())
    return " ".join(re.sub(r"\b(the|my|a|reminder|reminders|for|about|to)\b", " ", text).split())


class CancelReminder(_ReminderTool):
    name = "cancel_reminder"
    description = ("Cancel a timer or reminder (not a shutdown). Set which to words from it, "
                   "'timer', or 'all'.")
    args_schema = {
        "type": "object",
        "properties": {"which": {"type": "string", "maxLength": 100}},
        "additionalProperties": False,
    }

    def set_command(self, command: str) -> None:
        self._said = command            # the user's own words (Executor)

    def run(self, which: str = "") -> str:
        said = self.__dict__.pop("_said", "")
        sched = self._scheduler()
        items = sched.pending()
        if not items:
            return "You don't have any timers or reminders."
        key = _reminder_key(which)
        if not key and said:
            # The model sometimes says only "reminder"; "cancel my reminder to
            # call mom" still names the one to cancel.
            words = _reminder_key(re.sub(r"\b(cancel|delete|remove|clear|stop|forget|please|"
                                         r"can you|could you|red)\b", " ", said.lower()))
            if words and any(words in text.lower() for _, _, text in items):
                key = words
        if key in {"all", "everything", "all of them", "all timers", "all timer"}:
            for rid, _, _ in items:
                sched.cancel(rid)
            return f"Cancelled all {len(items)}."
        if not key:
            if len(items) > 1:
                raise ToolError(f"You have {len(items)}. Which one should I cancel?")
            key = items[0][0]
        if key in {"timers"}:
            key = "timer"
        target = next((t for rid, _, t in items if rid == key or key in t.lower()), None)
        if target is None or not sched.cancel(key):
            raise ToolError(f"I couldn't find a timer or reminder about {which}.")
        return f"Cancelled {describe_item(target)}."
