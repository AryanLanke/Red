"""Idle life and temper (plan.md 0.1 items 4 and 5): the companion is a little alive when you leave it alone.

While you're at the PC (keyboard or mouse input in the last 10 minutes) and nothing important is on
(no full-screen app, no game, no call, no turn in progress), `IdleLife.tick()` now and then fires:
- a small action as an event, `events.emit("idle_action", name=...)`: look_around, yawn, stretch,
  doze (only after a few quiet minutes), wander, hum (music lovers). The avatar plays them.
- the temper: a grumbled one-liner when you've ignored the companion for a while (how long depends on
  the pack's `temper`), at most once an hour, never when you said you're upset, never insulting.
- a song of its own, at most once every 2 hours and only at the `companion` chattiness level: it
  says what it's playing first, then plays it from your Music folder (red/tools/local_music.py), YouTube
  (`play_online`) or Spotify when it is open; "stop" stops it (`IdleLife.stop_reply`).

Every switch is in the companion's pack (`idle = { look_around, sleep, wander, grumble, music }`).
Rates are persisted in RED_HOME\\cache\\idle.json so a restart doesn't reset the hour. Tests drive
`tick()` with a fake clock; nothing here touches the real keyboard, speakers or windows unless
`attach_idle()` builds the real parts.
"""

from __future__ import annotations

import json
import logging
import os
import random
import re
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from . import events
from .companions import Companion
from .greeter import do_not_disturb, idle_seconds

log = logging.getLogger(__name__)

ACTIONS = ("look_around", "yawn", "stretch", "doze", "wander", "hum")
POLL = 10.0
AT_PC_SECONDS = 10 * 60          # input this recently means you're at the PC
DOZE_AFTER = 3 * 60              # no input for this long: it may doze off
WORKING_SECONDS = 2 * 60         # input this recently: you're busy with something else (so ignoring it)
ACTION_GAP = (45.0, 150.0)       # seconds between small actions
GRUMBLE_EVERY = 60 * 60          # at most one grumble an hour
SONG_EVERY = 2 * 60 * 60         # at most one song of its own every 2 hours
SONG_DELAY = (15 * 60.0, 60 * 60.0)    # once allowed, it picks a moment 15 to 60 minutes later
SONG_RETRY = 10 * 60.0
BLOCKED_RECHECK = 60.0           # a game or a call is on: look again in a minute
SONG_STOPPABLE = 30 * 60.0       # "stop" means the song for this long after it started
UPSET_QUIET = 2 * 60 * 60        # no grumbles for this long after you said you're upset
IGNORED_AFTER = {"low": 90 * 60.0, "medium": 40 * 60.0, "high": 20 * 60.0}

WEIGHTS = {"look_around": 4.0, "yawn": 1.0, "stretch": 1.0, "wander": 1.5, "hum": 1.5, "doze": 6.0}
GATES = {"look_around": "look_around", "yawn": "look_around", "stretch": "look_around",
         "doze": "sleep", "wander": "wander", "hum": "music"}

# A grumble is a quick sting, never an insult, and never about a life it doesn't have.
GRUMBLES = {
    "red": ["Still alive over there?", "Hello? I do still exist.", "Oh, so I'm furniture now.",
            "Not that I'm counting, but it's been a while.", "You know I can hear when you ignore me, right?"],
    "bruno": ["Ignoring me. Great. Fine.", "Nobody talks to me. Typical.", "Hello? Anyone? No? Fine.",
              "Don't mind me. I'll just grumble quietly."],
    "winston": ["I do hope I haven't been forgotten.", "Not to be a bother, but I'm still available.",
                "A word, whenever it suits you. No hurry. Some hurry."],
    "remy": ["Hey, it's me! Say something, anything."],
    "asha": ["Hello? Am I invisible today?", "You've gone very quiet. Suspicious."],
}
GENERIC_GRUMBLES = ["Hello? Anyone there?", "Still alive over there?", "You've gone quiet."]

# Famous songs only, so nothing said about them can be wrong. (spoken name, YouTube search)
SONGS = {
    "red": [("Come Together", "Come Together The Beatles"), ("Back in Black", "Back in Black AC/DC"),
            ("Seven Nation Army", "Seven Nation Army The White Stripes"), ("Hotel California", "Hotel California Eagles"),
            ("Money for Nothing", "Money for Nothing Dire Straits"), ("Under Pressure", "Under Pressure Queen and David Bowie")],
    "remy": [("Don't Stop Me Now", "Don't Stop Me Now Queen"), ("Dancing Queen", "Dancing Queen ABBA"),
             ("September", "September Earth, Wind & Fire"), ("Here Comes the Sun", "Here Comes the Sun The Beatles"),
             ("Uptown Funk", "Uptown Funk Mark Ronson Bruno Mars"), ("Shake It Off", "Shake It Off Taylor Swift")],
}
GENERIC_SONGS = SONGS["red"]
ANNOUNCE = {
    "red": ["Putting on {title}. Don't argue.", "I'm putting on {title}.", "{title}. Trust me."],
    "remy": ["Okay, {title}! Turn it up.", "Oh, this is a {title} moment. Putting it on!", "{title}. Yes."],
}
GENERIC_ANNOUNCE = ["Putting on {title}."]

_UPSET = re.compile(r"\b(?:i'?m|i am|feeling|feel|so|really|very|been) (?:\w+ )?(?:sad|upset|depressed|anxious|stressed|"
                    r"lonely|miserable|awful|terrible|crying|scared|hurt|exhausted|overwhelmed)\b|"
                    r"\b(?:rough|bad|terrible|awful|hard) (?:day|week|night|time)\b|\bi (?:hate|can'?t) (?:my|this|it)\b|"
                    r"\bleave me alone\b|\bgo away\b|\bshut up\b", re.IGNORECASE)
_STOP = re.compile(r"^(?:hey red[, ]*)?(?:(?:okay|ok|please|no)[, ]+)*(?:stop|stop (?:it|that|this|the (?:song|music))|"
                   r"turn (?:it|that|the music) off|enough|that'?s enough|cut it out)(?: please)?[.!]?$",
                   re.IGNORECASE)


@dataclass
class Song:
    announce: str                       # what the companion says first
    play: Callable[[], object]          # starts it (after the announcement was spoken)
    source: str = ""                    # local | spotify | online


def effective_chattiness(setting: str, explicit: bool, companion: Companion | None) -> str:
    """The user's own RED_CHATTINESS when they set it, else the companion's own level."""
    if explicit or companion is None:
        return setting
    return companion.chattiness


class IdleLife:
    """Decides what the companion does when left alone. `tick()` every few seconds; `start()` threads it."""

    def __init__(self, home: Path, companion: Callable[[], Companion], say: Callable[[str], bool], *,
                 music: Callable[[Companion], Song | None] | None = None,
                 level: Callable[[], str] = lambda: "friendly",
                 idle: Callable[[], float] = idle_seconds,
                 blocked: Callable[[], bool] = do_not_disturb,
                 busy: Callable[[], bool] = lambda: False,
                 playing: Callable[[], bool] = lambda: False,
                 now: Callable[[], datetime] = datetime.now,
                 clock: Callable[[], float] = time.monotonic,
                 rng: random.Random | None = None):
        self.state_path = Path(home) / "cache" / "idle.json"
        self.companion = companion
        self._say = say
        self._music = music
        self._level = level
        self._idle = idle
        self._blocked = blocked
        self._busy = busy
        self._playing = playing
        self._now = now
        self._clock = clock
        self._rng = rng or random.Random()
        start = clock()
        self._next_action = start + self._rng.uniform(*ACTION_GAP)
        self._last_action = ""
        self._last_doze = -1e9
        self._quiet_until = -1.0                # a game or a call was on: don't look again until then
        self._last_talk = start                 # when the user last spoke to the companion
        self._upset_until = -1.0
        self._song_due: float | None = None
        self._song_started = -1e9
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._unsubscribe: list[Callable[[], None]] = []

    # --- what the companion hears about ------------------------------------------------------

    def heard(self, text: str = "", **_) -> None:
        """The user said something (the `heard` event): they're not ignoring us, and maybe they're upset."""
        self._last_talk = self._clock()
        if _UPSET.search(text or ""):
            self._upset_until = self._clock() + UPSET_QUIET

    def felt(self, name: str = "", strength: float = 0.0, **_) -> None:
        """Our own `emotion` event: a sad conversation is no time for a grumble."""
        if name == "sad" and strength >= 0.6:
            self._upset_until = self._clock() + UPSET_QUIET

    # --- rates, kept across restarts ----------------------------------------------------------

    def _state(self) -> dict:
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _since(self, key: str) -> float:
        """Seconds since `key` last happened (wall clock, survives a restart); a huge number if never."""
        try:
            return (self._now() - datetime.fromisoformat(self._state()[key])).total_seconds()
        except (KeyError, ValueError, TypeError):
            return 1e12

    def _mark(self, key: str) -> None:
        state = self._state()
        state[key] = self._now().isoformat(timespec="seconds")
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            self.state_path.write_text(json.dumps(state), encoding="utf-8")
        except OSError:
            log.debug("Couldn't save the idle state", exc_info=True)

    # --- the tick -------------------------------------------------------------------------------

    def tick(self) -> list[str]:
        """Look once. Returns what happened: idle_action names, plus "grumble" or "song"."""
        c = self.companion()
        idle = self._idle()
        if idle >= AT_PC_SECONDS or self._busy():
            return []
        t = self._clock()
        if t < self._quiet_until:
            return []
        done: list[str] = []
        level = self._level()
        grumble = self._grumble_due(c, level, idle, t)
        song = self._song_is_due(c, level, t)
        action = t >= self._next_action
        if not (grumble or song or action):
            return []
        if self._blocked():                              # a game, a call, a full-screen app: nothing at all
            self._quiet_until = t + BLOCKED_RECHECK
            self._next_action = t + self._rng.uniform(*ACTION_GAP)
            return []
        if grumble and self._grumble(c):
            done.append("grumble")
            return done                                  # one thing at a time
        if song and self._song(c, t):
            done.append("song")
            return done
        if action:
            name = self._pick_action(c, idle, t)
            self._next_action = t + self._rng.uniform(*ACTION_GAP)
            if name:
                self._last_action = name
                if name == "doze":
                    self._last_doze = t
                events.emit("idle_action", name=name)
                done.append(name)
        return done

    # --- small actions --------------------------------------------------------------------------

    def _pick_action(self, c: Companion, idle: float, t: float) -> str | None:
        pool = []
        for name in ACTIONS:
            if name == self._last_action or not c.allows(GATES[name]):
                continue
            if name == "hum" and not c.likes_music():
                continue
            if name == "doze" and (idle < DOZE_AFTER or t - self._last_doze < 10 * 60):
                continue
            pool.append((name, WEIGHTS[name]))
        if not pool:
            return None
        names, weights = zip(*pool)
        return self._rng.choices(names, weights)[0]

    # --- temper -----------------------------------------------------------------------------------

    def _grumble_due(self, c: Companion, level: str, idle: float, t: float) -> bool:
        if level == "quiet" or not c.allows("grumble"):
            return False
        if idle > WORKING_SECONDS or t < self._upset_until:      # at the keyboard, and not upset
            return False
        if t - self._last_talk < IGNORED_AFTER.get(c.temper, IGNORED_AFTER["medium"]):
            return False
        return self._since("grumble_at") >= GRUMBLE_EVERY

    def _grumble(self, c: Companion) -> bool:
        pool = GRUMBLES.get(c.id, GENERIC_GRUMBLES)
        recent = self._state().get("grumble_line")
        line = self._rng.choice([x for x in pool if x != recent] or pool)
        events.emit("emotion", name="angry", strength=0.5)
        if not self._say(line):
            return False                                          # busy: try again next tick, nothing was spent
        self._mark("grumble_at")
        state = self._state()
        state["grumble_line"] = line
        try:
            self.state_path.write_text(json.dumps(state), encoding="utf-8")
        except OSError:
            pass
        self._last_talk = self._clock()
        log.info("Idle: grumble %r", line)
        return True

    # --- a song of its own ---------------------------------------------------------------------------

    def _song_is_due(self, c: Companion, level: str, t: float) -> bool:
        if self._music is None or level != "companion" or not c.allows("music"):
            self._song_due = None
            return False
        if self._since("song_at") < SONG_EVERY:
            return False
        if self._song_due is None:
            self._song_due = t + self._rng.uniform(*SONG_DELAY)
        return t >= self._song_due

    def _song(self, c: Companion, t: float) -> bool:
        if self._playing():                                       # something is already playing
            self._song_due = t + SONG_RETRY
            return False
        try:
            song = self._music(c)
        except Exception:  # noqa: BLE001 - no song beats a crash
            log.exception("Couldn't choose a song")
            song = None
        if song is None:
            self._song_due = t + SONG_RETRY
            return False
        events.emit("idle_action", name="hum")
        events.emit("emotion", name="happy", strength=0.7)
        if not self._say(song.announce):                          # said first; busy means not now
            self._song_due = t + 60.0
            return False
        try:
            song.play()
        except Exception:  # noqa: BLE001
            log.exception("Couldn't play the song")
        self._mark("song_at")
        self._song_due = None
        self._song_started = self._clock()
        log.info("Idle: song (%s): %s", song.source, song.announce)
        return True

    def song_active(self) -> bool:
        return self._clock() - self._song_started < SONG_STOPPABLE

    def stop_reply(self, text: str, stop: Callable[[], object]) -> str | None:
        """"stop" right after a song of its own: stop it (`stop()` presses the media key) and say so.
        None for anything else, so a bare "stop" elsewhere is left to the usual handling."""
        if not self.song_active() or not _STOP.match(" ".join(text.lower().split()).replace(",", ", ")):
            return None
        self._song_started = -1e9
        try:
            stop()
        except Exception:  # noqa: BLE001
            log.exception("Couldn't stop the song")
        return "Okay, stopped."

    # --- running ---------------------------------------------------------------------------------------

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception:  # noqa: BLE001 - never stop Red over a bit of life
                log.exception("Idle life failed")
            self._stop.wait(POLL)

    def start(self) -> None:
        if self._thread is not None:
            return
        self._unsubscribe = [events.on("heard", self.heard), events.on("emotion", self.felt)]
        self._thread = threading.Thread(target=self._run, name="red-idle", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        for off in self._unsubscribe:
            off()
        self._unsubscribe = []


# --- the real parts --------------------------------------------------------------------------------

def make_music(registry, rng: random.Random | None = None, *, local=None, windows=None) -> Callable[[Companion], Song | None]:
    """Choose a song for the companion: from your Music folder, YouTube (`play_online`) or Spotify when
    it is open. The model is never involved: names come from the lists above and from files that exist."""
    from .executor import run_later
    from .tools.local_music import PlayLocal, title_of
    rng = rng or random.Random()
    local = local or PlayLocal(rng=rng)
    recent: list[Path] = []

    def announce(c: Companion, title: str) -> str:
        return rng.choice(ANNOUNCE.get(c.id, GENERIC_ANNOUNCE)).format(title=title)

    def spotify_open() -> bool:
        try:
            if windows is not None:
                found = windows()
            else:
                from .windows import Win32Desktop
                found = Win32Desktop().windows()
            return any(w.exe == "spotify.exe" for w in found)
        except Exception:  # noqa: BLE001
            return False

    def choose(c: Companion) -> Song | None:
        options = []
        path = local.pick("", avoid=set(recent))
        if path is not None:
            options.append(("local", path))
        if "play_online" in registry:
            options.append(("online", None))
        if "spotify_search" in registry and spotify_open():
            options.append(("spotify", None))
        if not options:
            return None
        source, path = rng.choice(options)
        if source == "local":
            recent.append(path)
            del recent[:-8]
            return Song(announce(c, title_of(path)), lambda: local.play(path), "local")
        title, query = rng.choice(SONGS.get(c.id, GENERIC_SONGS))
        tool_name = "play_online" if source == "online" else "spotify_search"

        def play():
            tool = registry.get(tool_name)
            tool.run(query=query)
            run_later(tool.take_later())            # bring the window to the front, like a command would
        text = announce(c, title) if source == "online" else f"Pulling up {title} on Spotify."
        return Song(text, play, source)
    return choose


def media_playing(windows=None) -> bool:
    """A cheap guess that something is already playing: Spotify's window shows "Artist - Song" while it
    plays, and a YouTube tab's title ends in "- YouTube". Errs on the side of staying quiet."""
    try:
        if windows is not None:
            found = windows()
        else:
            from .windows import Win32Desktop
            found = Win32Desktop().windows()
    except Exception:  # noqa: BLE001
        return False
    for w in found:
        title = (w.title or "").strip()
        if w.exe == "spotify.exe" and " - " in title and not title.lower().startswith("spotify"):
            return True
        if title.endswith("- YouTube") and w.exe not in ("explorer.exe",):
            return True
    return False


def attach_idle(app) -> IdleLife | None:
    """Start idle life for a running VoiceApp (red.__main__). None if it fails: Red works fine without."""
    try:
        from . import companions
        settings = app.settings
        explicit = bool(os.environ.get("RED_CHATTINESS", "").strip())
        home = settings.home

        def busy() -> bool:
            if app._turn.acquire(blocking=False):
                app._turn.release()
                return False
            return True

        life = IdleLife(home, lambda: companions.active(home), app.greet,
                        music=make_music(app.executor.registry), busy=busy, playing=media_playing,
                        level=lambda: effective_chattiness(getattr(settings, "chattiness", "friendly"), explicit,
                                                           companions.active(home)))
        life.start()
        return life
    except Exception:  # noqa: BLE001
        log.exception("Couldn't start idle life")
        return None
