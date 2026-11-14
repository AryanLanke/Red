"""Hello, not briefings (plan.md A3).

Red says hello like a friend at the desk would: at the start of your day (when
Red starts, or when you're back at the PC on a new day) and when you're back
after 30 minutes or more away, with your name: "Morning, Aryan!", "Hey Aryan,
you're back." Lines vary and don't repeat what Red said the day before.

It never mentions meetings, mail, to-dos or news; those are only for when you
ask. And it keeps quiet while a full-screen app, a game or a presentation is
up, while another app is using the microphone (a call), and while Red is busy
with a command.

Chattiness (RED_CHATTINESS):
- quiet: Red only answers.
- friendly (default): the greetings above.
- chatty (and companion, which also lets a companion with music play a song of its own, red/idle.py): greetings, plus a one-liner at most once an hour when there's
  something worth saying ("It's 2 AM, you're still at it?").

Away time comes from Windows' GetLastInputInfo (no keyboard or mouse input),
so a locked PC counts as away too.
"""

from __future__ import annotations

import json
import logging
import random
import sys
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

from .memory import memory_dir

log = logging.getLogger(__name__)

CHATTINESS = ("quiet", "friendly", "chatty", "companion")
DEFAULT_CHATTINESS = "friendly"
AWAY_SECONDS = 30 * 60          # this long with no input is "away"
BACK_SECONDS = 15.0             # input this recent means you're at the PC
CHATTY_EVERY = 60 * 60          # at most one chatty line an hour
LONG_STRETCH = 2 * 60 * 60      # chatty: at the PC this long without a break
DAY_STARTS = 4                  # 2 AM still belongs to yesterday
RECENT = 8                      # lines not to repeat
POLL = 10.0

# "{name}" is the user's name; without one, ", {name}" and " {name}" just go.
MORNING = ["Morning, {name}!", "Morning, {name}. Good to see you.", "Hey {name}, morning!",
           "Morning, {name}. Coffee first, I assume.", "Up and at it, {name}. Morning!",
           "Good morning, {name}!"]
AFTERNOON = ["Hey {name}, good afternoon!", "Afternoon, {name}!", "Hey {name}. Afternoon already.",
             "Oh hey, {name}. Good afternoon.", "There you are, {name}. Afternoon!"]
EVENING = ["Evening, {name}!", "Hey {name}, good evening.", "Evening, {name}. Long day?",
           "Hey {name}. Evening shift, huh.", "Good evening, {name}!"]
NIGHT = ["Hey {name}. Burning the midnight oil, huh.", "Late one, {name}?",
         "Hey {name}. The night crew, I see.", "Oh hey, {name}. Up late."]
BACK = ["Hey {name}, you're back.", "Welcome back, {name}.", "There you are, {name}.",
        "Oh hey, {name}. Missed you. A bit.", "Back at it, {name}?", "Hey {name}. Good break?",
        "Look who's back. Hey, {name}."]
LATE = ["It's {time}, {name}. You're still at it?", "{time} already, {name}. Just saying.",
        "Hey {name}, it's {time}. Sleep is a thing, I hear."]
STRETCH = ["{hours} hours straight, {name}. Maybe stretch?", "You've been at it {hours} hours, {name}. "
           "Water break?", "{hours} hours, {name}. Your back says hi."]


def with_name(template: str, name: str | None, **values) -> str:
    """Fill in a line; without a name, ", {name}" and " {name}" drop out cleanly."""
    if not name:
        for gap in (", {name}", " {name}", "{name}, ", "{name} "):
            template = template.replace(gap, "")
        template = template.replace("{name}", "")
    text = template.format(name=name or "", **values).strip()
    return text[:1].upper() + text[1:]


def hello_lines(now: datetime) -> list[str]:
    if 5 <= now.hour < 12:
        return MORNING
    if 12 <= now.hour < 17:
        return AFTERNOON
    if 17 <= now.hour < 22:
        return EVENING
    return NIGHT


def spoken_time(now: datetime) -> str:
    hour = now.hour % 12 or 12
    return f"{hour} AM" if now.hour < 12 else f"{hour} PM"


def day_of(now: datetime) -> str:
    return (now - timedelta(hours=DAY_STARTS)).date().isoformat()


# --- Windows -----------------------------------------------------------------------------

def idle_seconds() -> float:
    """Seconds since the last keyboard or mouse input (GetLastInputInfo)."""
    if sys.platform != "win32":
        return 0.0
    import ctypes
    from ctypes import wintypes

    class LASTINPUTINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]
    info = LASTINPUTINFO()
    info.cbSize = ctypes.sizeof(info)
    if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
        return 0.0
    now = ctypes.windll.kernel32.GetTickCount() & 0xFFFFFFFF
    return ((now - info.dwTime) & 0xFFFFFFFF) / 1000.0


# SHQueryUserNotificationState: 2 busy (full screen), 3 a full-screen game, 4 presenting.
_DO_NOT_DISTURB = {2, 3, 4}


def full_screen() -> bool:
    if sys.platform != "win32":
        return False
    import ctypes
    state = ctypes.c_int(0)
    try:
        if ctypes.windll.shell32.SHQueryUserNotificationState(ctypes.byref(state)) != 0:
            return False
    except (AttributeError, OSError):
        return False
    return state.value in _DO_NOT_DISTURB


_MIC_KEY = r"Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\microphone"


def _own_exes() -> set[str]:
    """Red's own python.exe paths, as Windows writes them in the consent store ('#' for '\\')."""
    names = set()
    for exe in {sys.executable, getattr(sys, "_base_executable", "")}:
        if not exe:
            continue
        p = Path(exe)
        for variant in (p, p.with_name("python.exe"), p.with_name("pythonw.exe")):
            names.add(str(variant).replace("\\", "#").lower())
    return names


def mic_in_use_by_others() -> bool:
    """Another app has the microphone open right now (a call, a recording)."""
    if sys.platform != "win32":
        return False
    import winreg
    own = _own_exes()

    def busy(key) -> bool:
        try:
            stop, _ = winreg.QueryValueEx(key, "LastUsedTimeStop")
            start, _ = winreg.QueryValueEx(key, "LastUsedTimeStart")
        except OSError:
            return False
        return bool(start) and stop == 0

    def walk(path: str) -> bool:
        try:
            root = winreg.OpenKey(winreg.HKEY_CURRENT_USER, path)
        except OSError:
            return False
        with root:
            i = 0
            while True:
                try:
                    name = winreg.EnumKey(root, i)
                except OSError:
                    return False
                i += 1
                if name == "NonPackaged":
                    if walk(f"{path}\\{name}"):
                        return True
                    continue
                if name.lower() in own:
                    continue
                try:
                    with winreg.OpenKey(root, name) as key:
                        if busy(key):
                            return True
                except OSError:
                    continue
    try:
        return walk(_MIC_KEY)
    except Exception:  # noqa: BLE001 - unknown means "not in a call"
        return False


def do_not_disturb() -> bool:
    return full_screen() or mic_in_use_by_others()


# --- the greeter -------------------------------------------------------------------------

class Greeter:
    """Decides when to say hello. `tick()` once every few seconds; `start()` runs it on a thread.

    `say(text)` speaks and returns False when Red was busy (nothing is queued:
    a greeting late is worse than none).
    """

    def __init__(self, home: Path, say: Callable[[str], bool], *,
                 name: Callable[[], str | None] = lambda: None,
                 chattiness: str = DEFAULT_CHATTINESS,
                 idle: Callable[[], float] = idle_seconds,
                 blocked: Callable[[], bool] = do_not_disturb,
                 now: Callable[[], datetime] = datetime.now,
                 clock: Callable[[], float] = time.monotonic,
                 rng: random.Random | None = None):
        self.state_path = memory_dir(home) / "greetings.json"
        self._say = say
        self._name = name
        self.chattiness = chattiness if chattiness in CHATTINESS else DEFAULT_CHATTINESS
        self._idle = idle
        self._blocked = blocked
        self._now = now
        self._clock = clock
        self._rng = rng or random.Random()
        self._started = False           # the first tick may say the day's first hello
        self._away = False
        self._active_since = clock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # state on disk: the day of the last hello, recent lines, the last chatty line

    def _state(self) -> dict:
        try:
            return json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _save(self, state: dict) -> None:
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            self.state_path.write_text(json.dumps(state), encoding="utf-8")
        except OSError:
            log.exception("Couldn't save the greeter's state")

    def _pick(self, pool: list[str], state: dict) -> str:
        recent = state.get("recent", [])
        fresh = [line for line in pool if line not in recent] or [
            line for line in pool if line != (recent[-1] if recent else None)] or pool
        return self._rng.choice(fresh)

    def _speak(self, pool: list[str], state: dict, **values) -> str | None:
        template = self._pick(pool, state)
        try:
            name = self._name()
        except Exception:  # noqa: BLE001
            name = None
        text = with_name(template, name, **values)
        try:
            spoken = self._say(text)
        except Exception:  # noqa: BLE001 - a greeting must never break Red
            log.exception("Couldn't say hello")
            return None
        if not spoken:
            return None
        state["recent"] = (state.get("recent", []) + [template])[-RECENT:]
        self._save(state)
        log.info("Greeter: %s", text)
        return text

    def tick(self) -> str | None:
        """Look once; say hello if it's time. Returns what was said, if anything."""
        if self.chattiness == "quiet":
            return None
        first_tick, self._started = not self._started, True
        idle = self._idle()
        if idle >= AWAY_SECONDS:
            self._away = True
            return None
        here = idle < BACK_SECONDS
        came_back = self._away and here
        if came_back:
            self._away = False
            self._active_since = self._clock() - idle
        if not here:
            return None
        now = self._now()
        state = self._state()
        new_day = state.get("day") != day_of(now)
        if not ((first_tick or came_back) and (new_day or came_back)):
            return self._chatty(now, state) if self.chattiness in ("chatty", "companion") else None
        if self._blocked():
            return None                     # a game or a call: no hello, and none later either
        pool = hello_lines(now) if new_day else BACK
        state["day"] = day_of(now)
        state["last"] = now.isoformat(timespec="seconds")
        return self._speak(pool, state)

    def _chatty(self, now: datetime, state: dict) -> str | None:
        last = state.get("chatty_at")
        try:
            if last and (now - datetime.fromisoformat(last)).total_seconds() < CHATTY_EVERY:
                return None
        except ValueError:
            pass
        stretch = self._clock() - self._active_since
        if 0 <= now.hour < 4:
            pool, values = LATE, {"time": spoken_time(now)}
        elif stretch >= LONG_STRETCH:
            pool, values = STRETCH, {"hours": int(stretch // 3600)}
        else:
            return None
        if self._blocked():
            return None
        state["chatty_at"] = now.isoformat(timespec="seconds")
        said = self._speak(pool, state, **values)
        if said and pool is STRETCH:
            self._active_since = self._clock()     # don't say it again next hour
        return said

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception:  # noqa: BLE001 - never stop Red over a hello
                log.exception("Greeter failed")
            self._stop.wait(POLL)

    def start(self) -> None:
        if self.chattiness == "quiet" or self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="red-greeter", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()


def attach_greeter(app) -> Greeter | None:
    """Start greeting for a running VoiceApp (red.__main__). None if it's off or fails."""
    try:
        settings = app.settings
        greeter = Greeter(settings.home, app.greet, name=app.chat.user_name,
                          chattiness=getattr(settings, "chattiness", DEFAULT_CHATTINESS))
        greeter.start()
        return greeter
    except Exception:  # noqa: BLE001 - Red works fine without hellos
        log.exception("Couldn't start the greeter")
        return None
