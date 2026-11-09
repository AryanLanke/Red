"""Google Calendar, after the optional sign-in (python -m red google-login).

- calendar_events: "what's on my calendar tomorrow?"
- calendar_add: "add a meeting Friday at 3"
- calendar_move: "move my 5 pm to 6"
- calendar_cancel: "cancel my 4 pm" -- reads the event back once before deleting it

The model only fills checked values: a day (today, tomorrow, a weekday or
YYYY-MM-DD), a 24-hour time (HH:MM) and a short title. The replies are built
from Google's data, not written by the model. Times are in this PC's time zone.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Callable

from ..google_auth import GoogleApi, GoogleError
from .base import Tool, ToolError

EVENTS = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
MAX_EVENTS = 20
MAX_TITLE = 120
WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
_EVENT_ID = re.compile(r"[A-Za-z0-9_-]{1,200}")

DAY_ARG = {"type": "string", "pattern": r"^(today|tomorrow|monday|tuesday|wednesday|thursday|friday|"
                                        r"saturday|sunday|\d{4}-\d{2}-\d{2})$",
           "description": "today, tomorrow, a weekday, or YYYY-MM-DD. Default today."}
TIME_ARG = {"type": "string", "pattern": r"^([01]\d|2[0-3]):[0-5]\d$",
            "description": "24-hour HH:MM, e.g. 15:00 for 3 pm."}


def resolve_day(day: str, today: date) -> date:
    day = (day or "today").strip().lower()
    if day == "today":
        return today
    if day == "tomorrow":
        return today + timedelta(days=1)
    if day in WEEKDAYS:
        return today + timedelta(days=(WEEKDAYS.index(day) - today.weekday()) % 7)
    try:
        return date.fromisoformat(day)
    except ValueError:
        raise ToolError(f"I don't know which day {day} is.") from None


def say_day(d: date, today: date) -> str:
    if d == today:
        return "today"
    if d == today + timedelta(days=1):
        return "tomorrow"
    if 0 < (d - today).days < 7:
        return d.strftime("on %A")
    return d.strftime("on %A, %B ") + str(d.day)


_SPOKEN_TIME = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*(a\.?m\.?|p\.?m\.?)?(?=\W|$)", re.IGNORECASE)


def spoken_times(text: str) -> list[str]:
    """'move my 5 pm to 6' -> ['17:00', '18:00']: am/pm carries over to a bare hour."""
    found, half = [], None
    for m in _SPOKEN_TIME.finditer(text or ""):
        hour, minute = int(m.group(1)), int(m.group(2) or 0)
        if not (0 <= hour <= 23 and minute < 60):
            continue
        mark = (m.group(3) or "").lower().replace(".", "")
        half = mark or half
        if half == "pm" and hour < 12:
            hour += 12
        elif half == "am" and hour == 12:
            hour = 0
        found.append(f"{hour:02d}:{minute:02d}")
    return found


def say_time(t: datetime) -> str:
    """'4 PM', '10:30 AM'."""
    text = t.strftime("%I:%M %p").lstrip("0")
    return text.replace(":00 ", " ")


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _start(event: dict) -> datetime | None:
    when = event.get("start", {})
    if "dateTime" in when:
        return _parse(when["dateTime"]).astimezone()
    return None


def describe_event(event: dict, today: date) -> str:
    title = " ".join(str(event.get("summary") or "Untitled").split())[:80]
    start = _start(event)
    if start is None:
        return f"{title}, all day"
    return f"{title} at {say_time(start)}"


class _Calendar(Tool):
    def __init__(self, api: GoogleApi | None = None, now: Callable[[], datetime] | None = None):
        self._api = api or GoogleApi()
        self._now = now or (lambda: datetime.now().astimezone())

    def _today(self) -> date:
        return self._now().date()

    def _at(self, day: date, hhmm: str) -> datetime:
        hour, minute = (int(x) for x in hhmm.split(":"))
        return datetime(day.year, day.month, day.day, hour, minute, tzinfo=self._now().tzinfo)

    def _events(self, day: date) -> list[dict]:
        start = datetime(day.year, day.month, day.day, tzinfo=self._now().tzinfo)
        try:
            data = self._api.get(EVENTS, timeMin=start.isoformat(),
                                 timeMax=(start + timedelta(days=1)).isoformat(),
                                 singleEvents="true", orderBy="startTime", maxResults=MAX_EVENTS)
        except GoogleError as e:
            raise ToolError(str(e)) from e
        return [e for e in data.get("items", []) if e.get("status") != "cancelled"]

    def _find(self, day: str, time: str = "", title: str = "") -> tuple[dict, date]:
        """The one event at that time (or with that title) on that day."""
        d = resolve_day(day, self._today())
        events = self._events(d)
        if time:
            hour, minute = (int(x) for x in time.split(":"))
            events = [e for e in events if (s := _start(e)) and (s.hour, s.minute) == (hour, minute)]
        if title.strip():
            words = title.lower().split()
            events = [e for e in events if all(w in str(e.get("summary", "")).lower() for w in words)]
        when = say_day(d, self._today())
        if not events:
            at = f" at {say_time(self._at(d, time))}" if time else ""
            raise ToolError(f"I don't see anything {when}{at}.")
        if len(events) > 1:
            names = "; ".join(describe_event(e, self._today()) for e in events[:3])
            raise ToolError(f"There's more than one {when}: {names}. Which one?")
        if not _EVENT_ID.fullmatch(str(events[0].get("id", ""))):
            raise ToolError("Google gave that event an id I won't use.")
        return events[0], d


class CalendarEvents(_Calendar):
    name = "calendar_events"
    description = ("Say what's on the user's Google Calendar for a day ('what's on my calendar "
                   "tomorrow?', 'am I free on Friday?').")
    args_schema = {"type": "object", "properties": {"day": DAY_ARG}, "additionalProperties": False}

    def run(self, day: str = "today") -> str:
        d = resolve_day(day, self._today())
        events = self._events(d)
        when = say_day(d, self._today())
        if not events:
            return f"Nothing on your calendar {when}."
        listed = [describe_event(e, self._today()) for e in events]
        self.last_details = "\n".join(listed)
        count = "one thing" if len(events) == 1 else f"{len(events)} things"
        shown = "; ".join(listed[:6]) + ("; and more" if len(listed) > 6 else "")
        return f"{when.capitalize()} you have {count}: {shown}."


class CalendarAdd(_Calendar):
    name = "calendar_add"
    description = ("Add an event to the user's Google Calendar ('add a meeting Friday at 3', "
                   "'put lunch with Priya tomorrow at 1 on my calendar').")
    args_schema = {
        "type": "object",
        "properties": {
            "title": {"type": "string", "minLength": 1, "maxLength": MAX_TITLE,
                      "description": "A short title, e.g. Meeting or Lunch with Priya."},
            "day": DAY_ARG,
            "time": TIME_ARG,
            "minutes": {"type": "integer", "minimum": 5, "maximum": 24 * 60,
                        "description": "How long. Default 60."},
        },
        "required": ["title", "time"],
        "additionalProperties": False,
    }

    def run(self, title: str, time: str, day: str = "today", minutes: int = 60) -> str:
        title = " ".join(title.split())[:MAX_TITLE] or "Event"
        d = resolve_day(day, self._today())
        start = self._at(d, time)
        end = start + timedelta(minutes=minutes)
        try:
            self._api.post(EVENTS, {"summary": title, "start": {"dateTime": start.isoformat()},
                                    "end": {"dateTime": end.isoformat()}})
        except GoogleError as e:
            raise ToolError(str(e)) from e
        return f"Added {title} {say_day(d, self._today())} at {say_time(start)}."


class CalendarMove(_Calendar):
    name = "calendar_move"
    description = ("Move an event on the user's Google Calendar to another time or day. It keeps "
                   "its length. 'move my 5 pm to 6': time 17:00, new_time 18:00; 'move the dentist "
                   "to Friday at 10': title dentist, new_day friday, new_time 10:00.")
    args_schema = {
        "type": "object",
        "properties": {
            "day": DAY_ARG,
            "time": {**TIME_ARG, "description": "When it is now, 24-hour HH:MM."},
            "title": {"type": "string", "maxLength": MAX_TITLE,
                      "description": "Words from its title, if the user named it."},
            "new_day": DAY_ARG,
            "new_time": {**TIME_ARG, "description": "The new start, 24-hour HH:MM."},
        },
        "required": ["new_time"],
        "additionalProperties": False,
    }

    def set_command(self, command: str) -> None:
        self._said = command            # the user's own words (Executor)

    def run(self, new_time: str, day: str = "today", time: str = "", title: str = "",
            new_day: str = "") -> str:
        said = self.__dict__.pop("_said", "")
        if not time and not title.strip():
            # "move my 5 pm to 6": the first time you said is the event's.
            times = spoken_times(said)
            if len(times) >= 2:
                time = times[0]
        if not time and not title.strip():
            raise ToolError("Which event should I move?")
        event, d = self._find(day, time, title)
        old_start = _start(event)
        if old_start is None:
            raise ToolError("That's an all-day event; I can only move events with a time.")
        old_end = _parse(event["end"]["dateTime"]).astimezone()
        target = resolve_day(new_day, self._today()) if new_day else d
        start = self._at(target, new_time)
        end = start + (old_end - old_start)
        try:
            self._api.patch(f"{EVENTS}/{event['id']}", {"start": {"dateTime": start.isoformat()},
                                                        "end": {"dateTime": end.isoformat()}})
        except GoogleError as e:
            raise ToolError(str(e)) from e
        title = describe_event(event, self._today()).split(" at ")[0]
        return f"Moved {title} to {say_day(target, self._today())} at {say_time(start)}."


class CalendarCancel(_Calendar):
    name = "calendar_cancel"
    description = ("Delete (cancel) an event on the user's Google Calendar ('cancel my 4 pm', "
                   "'delete the dentist tomorrow'). Red reads it back before deleting.")
    destructive = True       # it deletes: read back once first
    args_schema = {
        "type": "object",
        "properties": {
            "day": DAY_ARG,
            "time": {**TIME_ARG, "description": "When it starts, 24-hour HH:MM."},
            "title": {"type": "string", "maxLength": MAX_TITLE,
                      "description": "Words from its title, if the user named it."},
        },
        "additionalProperties": False,
    }

    def prepare(self, day: str = "today", time: str = "", title: str = "") -> None:
        if not time and not title.strip():
            raise ToolError("Which event should I cancel?")
        self._found = ((day, time, title), self._find(day, time, title))

    def describe(self, day: str = "today", time: str = "", title: str = "") -> str:
        cached = getattr(self, "_found", None)
        found = cached[1] if cached and cached[0] == (day, time, title) else None
        if found is None:
            return "Delete that event"
        event, d = found
        return f"Deleting {describe_event(event, self._today())} {say_day(d, self._today())}. Delete"

    def run(self, day: str = "today", time: str = "", title: str = "") -> str:
        cached = self.__dict__.pop("_found", None)
        # The event that was read back, if it was read back for these words.
        event, d = cached[1] if cached and cached[0] == (day, time, title) else self._find(day, time, title)
        try:
            self._api.delete(f"{EVENTS}/{event['id']}")
        except GoogleError as e:
            raise ToolError(str(e)) from e
        return f"Deleted {describe_event(event, self._today())} {say_day(d, self._today())}."


def calendar_tools(api: GoogleApi | None = None) -> list[Tool]:
    api = api or GoogleApi()
    return [CalendarEvents(api), CalendarAdd(api), CalendarMove(api), CalendarCancel(api)]
