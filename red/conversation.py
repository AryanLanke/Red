"""Conversation mode, the zipped mouth, and who a sentence is for (night 2, lane "conversation").

**Conversation mode** works like Windows Copilot's voice: click the companion's microphone (or press
Ctrl+Alt+R, or pick "Talk to me"), a rising chime plays, and everything you say is for Red, with no wake
word, one turn after another. It ends when you click again, press the hotkey again, say "that's all",
"stop listening", "bye", "not you" or a zip phrase, or after RED_CONVERSATION_IDLE seconds (60) with
nothing said. Then a falling chime, and the mouth zips.

**Zipped** ("zip it", "not now", "I'm not talking to you", or a click while Red listens): Red stays deaf
to conversation (no follow-ups, no conversation mode) until the button is clicked again or you say
"Hey Red". Unlike Microphone off, the wake word still works. Remembered in RED_HOME\\cache\\mic.json.

**Not for me.** Red stays quiet when:
- another app has the microphone (Wispr Flow, Windows voice typing, a call): the wake word and
  conversation mode pause, and the companion shows "paused" (`OtherAppGuard`, one registry read a
  second, 0.17 ms each);
- the sentence starts by naming someone else: "Claude, ...", "Hey ChatGPT", "Copilot", "Siri", "Alexa",
  or one of your contacts (`addressed_elsewhere`);
- in conversation mode, it sounds like dictation (long instruction prose, "make the button blue", "and
  now I want you to install...") while an editor, a terminal or a chat box is in front
  (`dictation_like`). Saying "Red" in it overrides this. The bubble shows "not for me?" for 3 s.
Word rules and the window title only: no model call.

Events: `conversation(on, reason)`, `zipped(on)`, `paused(on)`, `not_for_me(text)`.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from pathlib import Path
from typing import Callable, Iterable

from . import events

log = logging.getLogger(__name__)

IDLE_SECONDS = 60.0            # RED_CONVERSATION_IDLE: conversation mode ends after this long with nothing said
ECHO_GUARD_SECONDS = 0.3       # the microphone opens this long after Red stops talking (room echo, speaker tail)
NOT_FOR_ME_SECONDS = 3.0       # how long the bubble shows "not for me?"
GUARD_EVERY_SECONDS = 1.0      # how often OtherAppGuard looks at who has the microphone


def _norm(text: str) -> str:
    text = (text or "").lower().replace("’", "'").replace("‘", "'")
    text = re.sub(r"[^\w' ]+", " ", text)
    return " ".join(text.split()).strip("' ")


# --- ending and zipping -----------------------------------------------------------------------

_TAIL = r"(?: (?:red|remy|asha|please|thanks|thank you|now|for now|okay|ok))*"
_ZIP = re.compile(
    r"(?:(?:okay|ok|red|hey red|no) )?"
    r"(?:zip it|zip your mouth|zip up|zip|not now|not right now|shh+|hush|"
    r"i'?m not talking to you|i am not talking to you|not talking to you|i wasn'?t talking to you|"
    r"i was not talking to you|that wasn'?t for you|that was not for you|not for you)" + _TAIL)
_END = re.compile(
    r"(?:(?:okay|ok|no|alright|all right|red) )?"
    r"(?:that'?s all|that is all|that'?s it|that is it|stop listening|you can stop listening|"
    r"bye|bye bye|goodbye|good bye|see you|see you later|not you|i'?m done|i am done|we'?re done|"
    r"that'?ll be all|that will be all|end conversation|stop the conversation|go to sleep)" + _TAIL)


def end_phrase(text: str) -> str | None:
    """'zip' for "zip it" / "not now" / "I'm not talking to you", 'end' for "that's all", "bye",
    "stop listening", "not you"; None otherwise. The whole sentence must be the phrase, so "not now,
    but remind me later" or "say bye to Tom" are not taken for it."""
    said = _norm(text)
    if not said:
        return None
    if _ZIP.fullmatch(said):
        return "zip"
    if _END.fullmatch(said):
        return "end"
    return None


# --- who a sentence is for --------------------------------------------------------------------

# Other assistants, and how Whisper writes them. Only at the start of a sentence, as a name: "Claude,
# make the button blue", "Hey ChatGPT ...", "OK Google ...".
OTHER_ASSISTANTS = {
    "claude": "claude", "cloud": "claude", "claud": "claude", "clod": "claude", "chatgpt": "chatgpt",
    "chat gpt": "chatgpt", "chat g p t": "chatgpt", "chad gpt": "chatgpt", "gpt": "chatgpt",
    "copilot": "copilot", "co pilot": "copilot", "siri": "siri", "seri": "siri", "alexa": "alexa",
    "alexis": "alexa", "google": "google", "ok google": "google", "okay google": "google",
    "gemini": "gemini", "cortana": "cortana", "wispr": "wispr", "whisper": "wispr", "cursor": "cursor",
    "codex": "codex", "grok": "grok", "perplexity": "perplexity",
}
_VOCATIVE_LEAD = r"^(?:hey|hi|ok|okay|yo|so|um|uh|and)?[ ,]*"


def _leading_name(text: str, names: Iterable[str]) -> str | None:
    """The name a sentence opens with ("Claude, ...", "Hey Siri ...", "OK Google, ..."), if it is one of
    `names`: said as a name, so set off by a comma or after "hey", or the whole sentence."""
    raw = (text or "").strip().lower().replace("’", "'")
    for name in sorted(names, key=len, reverse=True):
        n = re.escape(name).replace(r"\ ", r"[ -]?")
        # "Claude, ...", "Claude. ...", "Hey Claude ...", "Hey, Claude, ..."
        if re.match(_VOCATIVE_LEAD + n + r"\s*[,.!?:;-]", raw) or \
                re.match(r"^(?:hey|hi|ok|okay|yo)[ ,]+" + n + r"\b", raw) or \
                re.fullmatch(_VOCATIVE_LEAD + n + r"\W*", raw):
            return name
    return None


def addressed_elsewhere(text: str, contacts: Iterable[str] = (), own_names: Iterable[str] = ("red",)) -> str | None:
    """Who else the sentence is for, if it opens by naming someone else: another assistant or one of
    your contacts. None when it's for Red (or doesn't say)."""
    if _leading_name(text, [n.lower() for n in own_names]):
        return None
    names = dict(OTHER_ASSISTANTS)
    names.update({c.lower(): c.lower() for c in contacts if c and len(c) >= 3})
    found = _leading_name(text, names)
    return names[found] if found else None


# Windows where people dictate: editors, terminals, chat boxes (window titles, lower case).
DICTATION_WINDOWS = (
    "visual studio code", "cursor", "claude", "chatgpt", "copilot", "gemini", "notepad", "word",
    "google docs", "terminal", "powershell", "command prompt", "cmd.exe", "windows terminal", "slack",
    "discord", "whatsapp", "teams", "telegram", "messenger", "gmail", "outlook", "obsidian", "notion",
    "pycharm", "jetbrains", "sublime", "vim", "wispr",
)
_INSTRUCTION_START = re.compile(
    r"^(?:(?:and|but|so|also|then|okay|ok|now|alright|all right)[ ,]+)*"
    r"(?:(?:i want you to|i need you to|i'd like you to|can you|could you|please|you should|you need to|"
    r"we need to|we should|let's|lets|make sure|go ahead and)\s+)?"
    r"(?:write|make|add|create|fix|change|implement|refactor|build|update|remove|delete|rename|install|"
    r"commit|push|merge|rebase|deploy|test|debug|start the|finish|continue|replace|set up|setup|configure|"
    r"clean up|split|wire|hook|ship|draft|review|work on|go through)\b")
# How people start a request to Red itself ("open YouTube", "remind me...", "what's on my screen"): these
# are never taken for dictation unless very long.
_RED_START = re.compile(
    r"^(?:(?:hey|okay|ok|so|um|please|can you|could you|would you|will you)[ ,]+)*"
    r"(?:open|play|pause|resume|stop|remind|set a|set an|search|look up|google|find|tell me|show me|what|"
    r"what's|whats|who|who's|why|how|when|where|which|is it|are you|do you|did you|turn|mute|unmute|lock|"
    r"take a|read|check|switch|close|minimize|maximise|maximize|call|text|send|email|mail|reply|good|hi|hello|"
    r"hey|thanks|thank you|i'm|i am|you're|you are|you so|let's talk|let's chat)\b")
_LONG_WORDS = 14
_DEV_WORDS = re.compile(
    r"\b(?:functions?|methods?|class(?:es)?|buttons?|files?|folders?|code|codebase|tests?|testing|components?|"
    r"pages?|repos?|branch(?:es)?|main|bugs?|commit(?:s|ted)?|push(?:ed)?|merge[ds]?|features?|sessions?|"
    r"tasks?|plans?|scripts?|modules?|variables?|api|endpoints?|errors?|logs?|database|server|model|prompts?|"
    r"config|settings?|ui|css|html|python|typescript|javascript|json|readme|pull request|pr|issues?|lanes?|"
    r"worktrees?|terminal|installer|project|report|paragraph|sentences|commands|edits?|changes|"
    r"wake word|companions)\b")
_MODAL = re.compile(r"\b\w+ (?:should|must|needs to|has to|have to) (?:be|go|have|use|run|work|look|say|show|"
                    r"stay|do|get|make|keep|start|stop)\b")
_CONTINUATION = re.compile(r"^(?:and|but|also|then|so|because|or|which|that)\b")


def foreground_title() -> str:
    """The title of the window in front, lower case ('' if unknown)."""
    try:
        from .screen import foreground_window
        title, app = foreground_window()
        return f"{title} {app}".lower()
    except Exception:  # noqa: BLE001 - not Windows, or no window: unknown
        return ""


def dictation_window(title: str) -> bool:
    title = (title or "").lower()
    return any(w in title for w in DICTATION_WINDOWS)


def dictation_like(text: str, title: str, own_names: Iterable[str] = ("red",)) -> bool:
    """Does this sound like dictation to another app rather than talk to Red?

    Only while an editor, a terminal or a chat box is in front (`title`), and only for prose that reads
    like an instruction to someone else: long (12+ words), or 6+ words that start like an instruction
    ("write a function that...", "make the button blue and...") or talk about code, or a fragment that
    carries on a dictated sentence ("and now I want you to install..."). Saying Red's name overrides it.
    """
    if not dictation_window(title):
        return False
    said = _norm(text)
    words = said.split()
    if not words:
        return False
    if any(re.search(rf"\b{re.escape(n.lower())}\b", said) for n in own_names):
        return False
    if len(words) >= _LONG_WORDS:
        return True
    if _RED_START.match(said):
        return False
    if len(words) >= 10 and not _CONTINUATION.match(said) and _DEV_WORDS.search(said) is None:
        return False                                       # a long sentence about anything else
    instruction = _INSTRUCTION_START.match(said) is not None or (
        len(words) >= 8 and _MODAL.search(said) is not None)
    dev = _DEV_WORDS.search(said) is not None
    if len(words) >= 6 and (instruction or dev):
        return True
    if len(words) >= 4 and instruction and dev:            # "make this project faster"
        return True
    if len(words) >= 3 and _CONTINUATION.match(said) and (instruction or dev or len(words) >= 5):
        return True
    return False


# --- Red's own voice ----------------------------------------------------------------------------

def is_echo(heard: str, said: str) -> bool:
    """Is `heard` just Red's own last reply (`said`) coming back through the microphone?

    Three or more words, and nearly all of them (85%) are, in order, words of the reply."""
    h = _norm(heard).split()
    s = _norm(said).split()
    if len(h) < 3 or not s:
        return False
    i = hits = 0
    for word in h:
        j = i
        while j < len(s) and s[j] != word:
            j += 1
        if j < len(s):
            hits += 1
            i = j + 1
    return hits / len(h) >= 0.85


# --- the state --------------------------------------------------------------------------------

def read_state(path: Path | None) -> dict:
    if path is None:
        return {}
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def write_state(path: Path | None, **values) -> None:
    """Merge `values` into mic.json (it also holds "muted": Microphone off)."""
    if path is None:
        return
    data = read_state(path)
    data.update(values)
    try:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps(data), encoding="utf-8")
    except OSError:
        log.warning("Couldn't save the conversation state to %s", path, exc_info=True)


class Conversation:
    """Conversation mode and the zipped mouth. Thread-safe; the voice loop and the button share it.

    `sound(kind)` plays "start" (a rising chime), "end" (a falling chime and the zipper) or "zip" (the
    zipper alone); it is called outside the lock and must not raise.
    """

    def __init__(self, state_path: Path | None = None, *, idle_seconds: float = IDLE_SECONDS,
                 sound: Callable[[str], None] | None = None, clock: Callable[[], float] = time.monotonic):
        self.state_path = Path(state_path) if state_path else None
        self.idle_seconds = idle_seconds
        self._sound = sound
        self._clock = clock
        self._lock = threading.RLock()
        self.active = False
        self.zipped = bool(read_state(self.state_path).get("zipped"))
        self.paused = False                 # another app has the microphone
        self.last_speech = clock()
        self.started_at = 0.0
        self.end_reason = ""
        self.start_requested = False        # the button was clicked while a turn was running
        self.stop = threading.Event()       # set: stop the recording that is running now
        self.turns = 0

    # --- conversation mode ---

    def begin(self, source: str = "button") -> bool:
        """Conversation mode on. False if it already was."""
        with self._lock:
            self.start_requested = False
            if self.active:
                return False
            was_zipped = self.zipped
            self.active, self.zipped, self.end_reason, self.turns = True, False, "", 0
            self.started_at = self.last_speech = self._clock()
            self.stop.clear()
        if was_zipped:
            write_state(self.state_path, zipped=False)
            events.emit("zipped", on=False)
        log.info("Conversation mode on (%s)", source)
        self._play("start")
        events.emit("conversation", on=True, reason=source)
        return True

    def end(self, reason: str, zip_mouth: bool = True) -> bool:
        """Conversation mode off: the falling chime, and the mouth zips. False if it wasn't on."""
        with self._lock:
            if not self.active:
                return False
            self.active = False
            self.end_reason = reason
            self.stop.set()
            if zip_mouth:
                self.zipped = True
        log.info("Conversation mode off (%s) after %d turns, %.0f s", reason, self.turns,
                 self._clock() - self.started_at)
        if zip_mouth:
            write_state(self.state_path, zipped=True)
        self._play("end" if zip_mouth else "end-quiet")
        events.emit("conversation", on=False, reason=reason)
        if zip_mouth:
            events.emit("zipped", on=True)
        return True

    def request_start(self) -> None:
        """The button was clicked while Red was busy: go into conversation mode when this turn ends."""
        with self._lock:
            self.start_requested = True

    def heard(self) -> None:
        """Something real was said: the idle clock starts again."""
        with self._lock:
            self.last_speech = self._clock()
            self.turns += 1

    def idle_left(self) -> float:
        """Seconds of silence left before conversation mode ends by itself."""
        return self.idle_seconds - (self._clock() - self.last_speech)

    # --- the zipped mouth ---

    def zip(self, reason: str = "button") -> None:
        """Zip the mouth (not in conversation mode): stop listening now, stay deaf to conversation."""
        if self.active:
            self.end(reason)
            return
        with self._lock:
            self.stop.set()
            already = self.zipped
            self.zipped = True
        if not already:
            write_state(self.state_path, zipped=True)
            log.info("Zipped (%s)", reason)
            self._play("zip")
            events.emit("zipped", on=True)

    def unzip(self) -> None:
        with self._lock:
            if not self.zipped:
                return
            self.zipped = False
        write_state(self.state_path, zipped=False)
        log.info("Unzipped")
        events.emit("zipped", on=False)

    # --- another app has the microphone ---

    def set_paused(self, on: bool) -> bool:
        with self._lock:
            if on == self.paused:
                return False
            self.paused = on
            if on:
                self.stop.set()
        log.info("Listening %s: another app %s the microphone", "paused" if on else "resumed",
                 "has" if on else "let go of")
        events.emit("paused", on=on)
        return True

    def _play(self, kind: str) -> None:
        if self._sound is None:
            return
        try:
            self._sound(kind)
        except Exception:  # noqa: BLE001 - a sound is never worth breaking the conversation
            log.debug("Conversation sound %r failed", kind, exc_info=True)


class OtherAppGuard:
    """Pauses the wake word and conversation mode while another app has the microphone.

    `check()` is greeter.mic_in_use_by_others (one registry walk: 0.17 ms, measured 2026-11-14), every
    `every` seconds on its own thread. `pause()` / `resume()` are the listener's.
    """

    def __init__(self, conversation: Conversation, pause: Callable[[], None], resume: Callable[[], None], *,
                 check: Callable[[], bool] | None = None, every: float = GUARD_EVERY_SECONDS):
        if check is None:
            from .greeter import mic_in_use_by_others as check
        self.conversation = conversation
        self._pause, self._resume, self._check = pause, resume, check
        self.every = every
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.paused = False
        self.checks = 0
        self.check_seconds = 0.0

    def tick(self) -> bool:
        """Look once. Returns whether listening is paused now."""
        t0 = time.perf_counter()
        try:
            busy = bool(self._check())
        except Exception:  # noqa: BLE001 - unknown means "nobody else"
            busy = False
        self.checks += 1
        self.check_seconds += time.perf_counter() - t0
        if busy and not self.paused:
            self.paused = True
            self.conversation.set_paused(True)
            # On a thread of its own: pause() waits for the wake word's microphone to close.
            threading.Thread(target=self._pause, name="red-guard-pause", daemon=True).start()
        elif not busy and self.paused:
            self.paused = False
            self.conversation.set_paused(False)
            self._resume()
        return self.paused

    def start(self) -> "OtherAppGuard":
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="red-mic-guard", daemon=True)
            self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        if self.paused:
            self.paused = False
            self.conversation.set_paused(False)
            self._resume()

    def _run(self) -> None:
        while not self._stop.wait(self.every):
            self.tick()


# --- sounds -----------------------------------------------------------------------------------

def zipper_tone(seconds: float = 0.32, rate: int = 22_050, volume: float = 0.12, seed: int = 7):
    """A short zipper: a fast run of clicks that speeds up, with a little noise. Made here, no file
    (so no licence to track); a sound pack's own `zip` clip wins over it (red.sounds)."""
    import numpy as np

    rng = np.random.default_rng(seed)
    n = int(seconds * rate)
    out = np.zeros(n, np.float32)
    t, gap = 0.0, 0.016
    while t < seconds - 0.004:
        i = int(t * rate)
        click = rng.standard_normal(int(0.003 * rate)).astype(np.float32)
        click *= np.exp(-np.linspace(0, 6, click.size)).astype(np.float32)
        out[i:i + click.size] += click[: max(0, n - i)]
        t += gap
        gap = max(0.006, gap * 0.93)
    out += 0.08 * rng.standard_normal(n).astype(np.float32) * np.linspace(0.3, 1.0, n).astype(np.float32)
    fade = np.minimum(1.0, np.minimum(np.arange(n), n - np.arange(n)) / (0.01 * rate))
    out *= fade.astype(np.float32)
    peak = float(np.abs(out).max()) or 1.0
    return (volume * out / peak).astype(np.float32), rate


def play_sound(kind: str, pack: str | None = None, home: Path | None = None) -> None:
    """The real sounds: "start" a rising chime, "end" a falling chime then the zipper, "zip" the zipper.
    On a stream of their own, so they never cut off Red's voice. Blocks for about 0.3-0.6 s."""
    from .audio import soft_chime

    if kind in ("start", "end", "end-quiet"):
        soft_chime(muted=kind != "start", volume=0.08)
    if kind in ("end", "zip"):
        clip = None
        try:
            from . import sounds
            clip = sounds.pick(pack, "zip", home=home) if pack else None
        except Exception:  # noqa: BLE001 - no pack or no zip clip: the made one
            clip = None
        if clip is not None:
            from . import sounds
            sounds.play(clip)
            return
        import sounddevice as sd
        tone, rate = zipper_tone()
        with sd.OutputStream(samplerate=rate, channels=1, dtype="float32") as stream:
            stream.write(tone.reshape(-1, 1))
