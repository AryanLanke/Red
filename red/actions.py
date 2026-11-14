"""The companion menu's back end (plan.md 0.3 lane 2 task 8): plain functions around the existing tools.

    from red import actions
    actions.remind("call mom", "in 20 minutes")      # or "at 3 pm", "tomorrow 9am", "15:30", or a datetime
    actions.add_task("finish the slides")
    actions.list_tasks()                             # ["finish the slides", ...]  (open ones, in order)
    actions.play_music("Believer")                   # or "" for a song Red picks
    actions.talk()                                   # the same as the hotkey: Red starts listening

Each returns what Red would say ("Okay, I'll remind you at 3 PM: call mom.") and raises `ToolError`
(a message fit to show or say) when it can't. They run the same tools a spoken command runs, so a
reminder rings through the same scheduler, a task lands in the same list, and nothing here ever
passes text to a shell. `bind(app)` (done by the voice loop) lets them use the running app's tools
and listener; without it they build their own tools, which is what the tests and `python -m red` use.
"""

from __future__ import annotations

import functools
import re
from datetime import datetime, timedelta

from .tools.base import ToolError

__all__ = ["add_task", "bind", "list_tasks", "play_music", "remind", "talk", "when_from"]

_app = None
_DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
_WORD_NUMBERS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
                 "eight": 8, "nine": 9, "ten": 10, "fifteen": 15, "twenty": 20, "thirty": 30, "half": 0.5}


def bind(app) -> None:
    """Use the running VoiceApp's tools and listener (None unbinds)."""
    global _app
    _app = app


@functools.lru_cache(maxsize=1)
def _own_registry():
    from .tools import default_registry
    return default_registry(google=False)


def _tools():
    registry = getattr(getattr(_app, "executor", None), "registry", None)
    return registry if registry is not None else _own_registry()


def _tool(name: str):
    registry = _tools()
    if name not in registry:
        raise ToolError(f"The {name.replace('_', ' ')} isn't available right now.")
    return registry.get(name)


# --- when --------------------------------------------------------------------------------------------

_IN = re.compile(r"^(?:in|after)\s+(?P<n>an?|one|two|three|four|five|six|seven|eight|nine|ten|fifteen|twenty|thirty|"
                 r"half an?|\d+(?:\.\d+)?)\s*(?P<unit>seconds?|secs?|minutes?|mins?|m|hours?|hrs?|h|days?)\b", re.I)
_CLOCK = re.compile(r"(?:\bat\s+)?\b(?P<h>\d{1,2})(?::(?P<m>\d{2}))?\s*(?P<ap>a\.?m\.?|p\.?m\.?)?\b", re.I)


def when_from(when, now: datetime) -> dict:
    """The set_reminder arguments for `when`: a datetime, or words like 'in 20 minutes',
    'at 3 pm', 'tomorrow at 9', 'friday 15:30', '18:00'. Raises ToolError when it can't tell."""
    if isinstance(when, datetime):
        days = (when.date() - now.date()).days
        if when <= now or days < 0:
            raise ToolError("That time has already passed.")
        if days > 7:
            raise ToolError("I can only remind you up to 7 days ahead.")
        day = "today" if days == 0 else "tomorrow" if days == 1 else _DAYS[when.weekday()]
        return {"time": when.strftime("%H:%M"), "day": day}
    text = " ".join(str(when or "").lower().replace(",", " ").split())
    if not text:
        raise ToolError("When should I remind you?")
    m = _IN.match(text)
    if m:
        n = m.group("n")
        n = 0.5 if n.startswith("half") else _WORD_NUMBERS.get(n, None) or float(n)
        unit = m.group("unit")
        if unit.startswith("s"):
            minutes = n / 60
        elif unit.startswith("h"):
            minutes = n * 60
        elif unit.startswith("d"):
            minutes = n * 24 * 60
        else:
            minutes = n
        minutes = max(1, int(round(minutes)))
        if minutes > 7 * 24 * 60:
            raise ToolError("I can only remind you up to 7 days ahead.")
        return {"in_minutes": minutes}
    day = None
    for word in ("today", "tomorrow", *_DAYS):
        if re.search(rf"\b{word}\b", text):
            day = word
            text = re.sub(rf"\b{word}\b", " ", text)
            break
    if "tonight" in text:
        day, text = "today", text.replace("tonight", " ")
    c = _CLOCK.search(text)
    if not c:
        raise ToolError("I didn't catch the time. Try 'in 20 minutes' or 'at 3 pm'.")
    hour, minute = int(c.group("h")), int(c.group("m") or 0)
    ap = (c.group("ap") or "").replace(".", "")
    if ap == "pm" and hour < 12:
        hour += 12
    elif ap == "am" and hour == 12:
        hour = 0
    elif not ap and not c.group("m") and hour <= 12 and "tonight" in str(when).lower():
        hour = hour % 12 + 12
    if not (0 <= hour < 24 and 0 <= minute < 60):
        raise ToolError("I didn't catch the time. Try 'in 20 minutes' or 'at 3 pm'.")
    args = {"time": f"{hour:02d}:{minute:02d}"}
    if day:
        args["day"] = day
    return args


# --- the actions -----------------------------------------------------------------------------------------

def remind(text: str, when, *, now: datetime | None = None) -> str:
    """Set a reminder (the set_reminder tool). `when`: a datetime or words (see `when_from`)."""
    what = " ".join(str(text or "").split())
    if not what:
        raise ToolError("Remind you of what?")
    args = when_from(when, now or datetime.now())
    return _tool("set_reminder").run(text=what[:200], **args)


def add_task(text: str) -> str:
    """Put something on the to-do list (the todo plugin)."""
    what = " ".join(str(text or "").split())
    if not what:
        raise ToolError("Add what?")
    return _tool("todo").run(action="add", text=what[:200])


def list_tasks() -> list[str]:
    """The open to-dos, oldest first (the todo plugin's own list)."""
    tool = _tool("todo")
    module = __import__(type(tool).__module__, fromlist=["_load"])
    load = getattr(module, "_load", None)
    if load is None:                                   # a user's replacement of the plugin: use its words
        said = tool.run(action="list")
        return [] if said.startswith("Nothing") else [p.strip(" .") for p in said.split(":", 1)[-1].split(";")]
    return [str(i["text"]) for i in load() if not i.get("done")]


def play_music(query: str = "") -> str:
    """Play something: `query` on YouTube (play_online), or, with no query, a song Red picks
    (your Music folder, YouTube or Spotify, as for his own idle song)."""
    from .executor import run_later
    query = " ".join(str(query or "").split())[:100]
    if query:
        tool = _tool("play_online")
        reply = tool.run(query=query)
        run_later(tool.take_later())
        return reply
    from . import companions
    from .idle import make_music
    home = getattr(getattr(_app, "settings", None), "home", None)
    song = make_music(_tools())(companions.active(home))
    if song is None:
        raise ToolError("I couldn't find anything to play.")
    song.play()
    return song.announce


def talk() -> str:
    """Start listening, as the hotkey does. Needs the running voice loop (`bind`)."""
    listener = getattr(_app, "listener", None)
    fire = getattr(listener, "_fire", None)
    if fire is None:
        raise ToolError("I'm not listening right now.")
    fire("menu")
    return "Listening."
