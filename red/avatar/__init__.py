"""The companion on screen: a character who peeks over the bottom edge of the screen.

The pictures are 2D frames pre-rendered from a VRM model (scripts/avatar_render), in
RED_HOME\\models\\companion\\<id>\\ with a frames.json. Two sets:

- peek_*: the upper body, forearms resting on the screen edge. The bottom of each picture is the edge.
- body_*: the whole body, shown while you pick the companion up and carry it somewhere else.

This module holds what can be tested without a screen: which frame to show for a state, an emotion and
the voice's loudness; a guess at the emotion from what Red says; the mouth meter that follows the speech;
and the short "whoa!" clips played when you pick the companion up. The window is red/avatar/window.py.
"""

from __future__ import annotations

import json
import logging
import math
import re
import threading
import time
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np

log = logging.getLogger(__name__)

# The companions that have a look today. The voice is used for the pickup clips; "red" speaks with
# RED_VOICE, the others with their own (docs/architecture.md section 4).
COMPANIONS = {
    "red": {"name": "Red", "voice": None},
    "remy": {"name": "Remy", "voice": "af_bella"},
    "asha": {"name": "Asha", "voice": "af_kore"},
}
DEFAULT_COMPANION = "red"
SIZES = {"small": 240, "medium": 300, "large": 380}   # display pixels per metre
DEFAULT_SIZE = "medium"

EMOTIONS = ("happy", "laugh", "sad", "angry", "surprised", "shy")
SLEEP_AFTER_SECONDS = 300.0
BLINK_EVERY = 4.2          # seconds between blinks (varied a little per blink)
BLINK_LENGTH = 0.14
WAVE_FRAME = 0.16          # seconds per wave frame
DRAG_FRAME = 0.14

PICKUP_LINES = ("Whoa!", "Hey!", "Wheee!", "Ah, careful!")
DROP_LINES = ("Oof.", "Thanks.")


# --------------------------------------------------------------------------
# Frames on disk
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Frame:
    name: str
    set: str                     # "peek" or "body"
    path: Path
    marks: dict                  # where the head, neck, hands and elbows are on the picture (pixels)


@dataclass
class Sprites:
    folder: Path
    px_per_metre: float
    sizes: dict                  # set -> (width, height)
    frames: dict = field(default_factory=dict)
    name: str = ""
    voice: str | None = None     # the Kokoro voice for its pickup clips; None: Red's voice

    def has(self, name: str) -> bool:
        return name in self.frames


def companion_folder(models_dir: Path, companion: str) -> Path:
    return Path(models_dir) / "companion" / companion


def load_sprites(folder: Path) -> Sprites:
    """Read frames.json from a finished sprite folder. Raises FileNotFoundError if it isn't there."""
    folder = Path(folder)
    meta = json.loads((folder / "frames.json").read_text(encoding="utf-8"))
    known = COMPANIONS.get(folder.name, {})
    sprites = Sprites(folder, float(meta["pxPerMetre"]), {},
                      name=meta.get("name") or known.get("name") or folder.name.title(),
                      voice=meta.get("voice") or known.get("voice"))
    for set_name, block in meta["sets"].items():
        sprites.sizes[set_name] = tuple(block["size"])
        for f in block["frames"]:
            path = folder / f"{f['name']}.png"
            if path.exists():
                sprites.frames[f["name"]] = Frame(f["name"], set_name, path, f.get("marks", {}))
    if not sprites.has("peek_idle"):
        raise FileNotFoundError(f"{folder} has no peek_idle frame")
    return sprites


def available_companions(models_dir: Path) -> dict[str, str]:
    """id -> name for every companion whose pictures are installed (scripts/avatar_render/add.py)."""
    found = {}
    root = Path(models_dir) / "companion"
    for meta_path in sorted(root.glob("*/frames.json")) if root.is_dir() else []:
        cid = meta_path.parent.name
        try:
            name = json.loads(meta_path.read_text(encoding="utf-8")).get("name")
        except (OSError, ValueError):
            continue
        found[cid] = name or COMPANIONS.get(cid, {}).get("name") or cid.title()
    return found


# Where the companion sits, and the frame set for it: the bottom edge, a bottom corner, or hanging
# upside down from the top edge.
SIDES = {"edge": "peek", "left": "cornerL", "right": "cornerR", "top": "top",
         "top-left": "topL", "top-right": "topR",
         # the climbing frame: clinging to a side of the screen, or sitting on an app window's top edge
         "side-left": "sideL", "side-right": "sideR", "window-top": "sit"}
SIDE_OF = {prefix: side for side, prefix in SIDES.items()}       # frame set -> placement
TOP_SIDES = ("top", "top-left", "top-right")        # the placements that hang upside down
SIDE_SIDES = ("side-left", "side-right")            # clinging to a side of the screen
# Whole-body sets for climbing (scripts/avatar_render/frames.js): a frame they lack is their own idle,
# never a peek frame (which is a different shape).
CLIMBING_SETS = ("sideL", "sideR", "climbL", "climbR", "bars", "sit")
FRAME_SETS = ("peek", "cornerR", "cornerL", "top", "topL", "topR", "body") + CLIMBING_SETS
# A model without the frames for a placement uses the next best: a top corner is the top edge, then the edge;
# a side is that bottom corner.
FALLBACK = {"topL": "top", "topR": "top", "top": "peek", "cornerL": "peek", "cornerR": "peek",
            "sideL": "cornerL", "sideR": "cornerR", "sit": "peek"}


def frame_for_side(name: str, side: str, available: Callable[[str], bool] = lambda n: True) -> str:
    """A peek_* frame turned into the same frame for a corner, if the model has it."""
    return frame_in_set(name, SIDES.get(side, "peek"), available)


def frame_in_set(name: str, prefix: str, available: Callable[[str], bool] = lambda n: True) -> str:
    """A peek_* frame turned into the same frame of another set (cornerR_idle, sideL_happy...). A corner
    without it keeps the peek frame (as before); a whole-body set falls back to its own idle frame."""
    if prefix == "peek" or not name.startswith("peek_"):
        return name
    wanted = prefix + name[len("peek"):]
    if available(wanted):
        return wanted
    if prefix in CLIMBING_SETS:
        base = wanted.removesuffix("_blink")
        return base if available(base) else f"{prefix}_idle"
    return name


def side_for(x: float, left: float, right: float, snap: float, y: float | None = None,
             top: float | None = None, bottom: float | None = None) -> str:
    """Dropped within `snap` pixels of the top of the screen: hanging from the top edge, or from the top
    corner if it is also near a side. Near a side lower down: that bottom corner, or (given `bottom`, for a
    model that can climb) clinging to that side when it is well above the bottom. Otherwise the bottom edge."""
    if y is not None and top is not None and y <= top + snap:
        if x >= right - snap:
            return "top-right"
        if x <= left + snap:
            return "top-left"
        return "top"
    high = y is not None and bottom is not None and y < bottom - 2 * snap
    if x >= right - snap:
        return "side-right" if high else "right"
    if x <= left + snap:
        return "side-left" if high else "left"
    return "edge"


# --------------------------------------------------------------------------
# Which frame to show
# --------------------------------------------------------------------------

@dataclass
class Look:
    """Everything that decides the frame. The window fills it in; pick_frame() reads it."""
    state: str = "idle"           # an overlay state, or "sleeping" / "notice" / "greeting"
    emotion: str | None = None
    mouth: float = 0.0            # 0..1, the voice's loudness right now
    dragging: bool = False
    falling: bool = False
    since: float = 0.0            # when the state or emotion started (seconds, any clock)
    action: str | None = None     # an idle frame being played: look_left, yawn, ... (red/avatar/idle.py)


def blinking(now: float, seed: float = 0.0) -> bool:
    """True for a short moment every few seconds, not quite regularly."""
    n = math.floor((now + seed) / BLINK_EVERY)
    offset = (math.sin(n * 12.9898) * 43758.5453) % 1.0 * 1.2       # 0..1.2 s of jitter per blink
    t = (now + seed) - n * BLINK_EVERY - offset
    return 0.0 <= t < BLINK_LENGTH


def _talk_frames(emotion: str | None) -> tuple[str, ...]:
    """(closed, half open, open) for the emotion."""
    return {
        "happy": ("peek_happy", "peek_happy_talk_1", "peek_happy_talk_2"),
        "laugh": ("peek_laugh_2", "peek_laugh", "peek_laugh_2"),
        "sad": ("peek_sad", "peek_sad_talk", "peek_sad_talk"),
        "angry": ("peek_angry", "peek_angry_talk", "peek_angry_talk"),
        "surprised": ("peek_surprised", "peek_surprised", "peek_talk_3"),
        "shy": ("peek_shy", "peek_shy", "peek_talk_1"),
    }.get(emotion or "", ("peek_idle", "peek_talk_1", "peek_talk_2"))


def pick_frame(look: Look, now: float, available: Callable[[str], bool] = lambda name: True) -> str:
    """The frame name for this moment. Falls back to peek_idle for frames a model doesn't have."""
    name = _pick(look, now)
    if available(name):
        return name
    base = name.removesuffix("_blink")
    return base if available(base) else "peek_idle"


def _pick(look: Look, now: float) -> str:
    age = max(0.0, now - look.since)
    if look.dragging:
        if look.emotion == "happy":
            return "body_drag_fun"
        return ("body_drag_1", "body_drag_2", "body_drag_3")[int(now / DRAG_FRAME) % 3]
    if look.falling:
        return "body_drop"
    blink = blinking(now)
    state = look.state
    if state == "sleeping":
        return "peek_sleep"
    if state == "greeting":
        return ("peek_wave_1", "peek_wave_2", "peek_wave_3", "peek_wave_2")[int(age / WAVE_FRAME) % 4]
    if state == "speaking":
        closed, half, open_ = _talk_frames(look.emotion)
        if look.mouth < 0.12:
            return closed
        if look.mouth < 0.45:
            return half
        # Now and then an "oh" instead of an "ah", so the mouth doesn't look stuck.
        if look.emotion is None and int(now * 5) % 7 == 0:
            return "peek_talk_3"
        return open_
    if state == "notice":
        return "peek_notice"
    if state == "listening":
        return "peek_listen_blink" if blink else "peek_listen"
    if state in ("thinking", "confirm"):
        return "peek_think_blink" if blink else "peek_think"
    if state == "error":
        return "peek_shy"
    if look.action and not look.emotion:
        return f"peek_{look.action}"
    if look.emotion:
        return {"happy": "peek_happy", "laugh": "peek_laugh_2", "sad": "peek_sad", "angry": "peek_angry",
                "surprised": "peek_surprised", "shy": "peek_shy"}.get(look.emotion, "peek_idle")
    return "peek_idle_blink" if blink else "peek_idle"


# Little marks drawn over the head, anime style, so a feeling reads even at a small size.
MARKS = {
    "sleeping": "zzz",
    "thinking": "dots",
    "confirm": "question",
    "notice": "exclaim",
    "surprised": "exclaim",
    "angry": "anger",
    "sad": "tear",
    "shy": "sweat",
    "error": "sweat",
    "happy": "note",
    "laugh": "note",
}


def mark_for(look: Look) -> str | None:
    if look.dragging or look.falling:
        return None
    if look.state in ("sleeping", "thinking", "confirm", "notice", "error"):
        return MARKS[look.state]
    return MARKS.get(look.emotion or "")


# --------------------------------------------------------------------------
# Emotion from what Red says (until the speech carries emotion tags)
# --------------------------------------------------------------------------

_PATTERNS = (
    ("greeting", r"^\s*(hey|hi|hello|good (morning|afternoon|evening)|morning|welcome back)\b"),
    ("laugh", r"\b(ha(ha)+|heh|lol|lmao)\b|😂|🤣"),
    ("sad", r"\b(sorry|sad|unfortunately|i('m| am) afraid|that's rough|oh no)\b|😢"),
    ("angry", r"\b(ugh|annoying|furious|seriously\?|come on)\b"),
    ("surprised", r"\b(whoa|wow|really\?|no way|what\?!)\b|!\?"),
    ("shy", r"\b(oops|my bad|embarrassing|um+)\b"),
    ("happy", r"\b(great|nice|awesome|done|glad|love|yay|perfect|good news|congrats|happy)\b|[😊🙂😄]"),
)


def emotion_from_text(text: str) -> str | None:
    """A rough feeling for a reply: greeting, laugh, sad, angry, surprised, shy, happy, or None."""
    text = (text or "").lower()
    for name, pattern in _PATTERNS:
        if re.search(pattern, text):
            return name
    return None


# --------------------------------------------------------------------------
# The mouth follows the voice
# --------------------------------------------------------------------------

class MouthMeter:
    """Loudness of the audio being played, 30 times a second, as 0..1 for the mouth."""

    RATE = 30

    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self._clock = clock
        self._lock = threading.Lock()
        self._levels = np.zeros(0, dtype=np.float32)
        self._start = 0.0

    def start(self, audio: np.ndarray, samplerate: int) -> None:
        audio = np.asarray(audio, dtype=np.float32).ravel()
        hop = max(1, int(samplerate / self.RATE))
        n = audio.size // hop
        if n == 0:
            levels = np.zeros(0, dtype=np.float32)
        else:
            rms = np.sqrt(np.mean(audio[: n * hop].reshape(n, hop) ** 2, axis=1))
            peak = float(np.percentile(rms, 95)) or 1.0
            levels = np.clip(rms / peak, 0.0, 1.0) ** 0.7          # quiet syllables still open the mouth
        with self._lock:
            self._levels = levels.astype(np.float32)
            self._start = self._clock()

    def stop(self) -> None:
        with self._lock:
            self._levels = np.zeros(0, dtype=np.float32)

    def level(self) -> float:
        with self._lock:
            i = int((self._clock() - self._start) * self.RATE)
            if 0 <= i < self._levels.size:
                return float(self._levels[i])
            return 0.0

    def playing(self) -> bool:
        """True while a clip handed to start() is still sounding (even in a quiet moment of it)."""
        with self._lock:
            return 0 <= int((self._clock() - self._start) * self.RATE) < self._levels.size


class MouthPlayer:
    """Wraps Red's audio player (red/tts.Player) so the meter sees everything Red says."""

    def __init__(self, inner, meter: MouthMeter):
        self.inner = inner
        self.meter = meter

    def play(self, audio, samplerate: int) -> None:
        self.meter.start(audio, samplerate)
        self.inner.play(audio, samplerate)

    def wait(self) -> None:
        self.inner.wait()

    def stop(self) -> None:
        self.meter.stop()
        self.inner.stop()


def meter_speaker(speaker, meter: MouthMeter) -> None:
    """Put the meter between a Speaker and its player (and its Piper fallback's)."""
    if isinstance(getattr(speaker, "player", None), MouthPlayer):
        return
    wrapped = MouthPlayer(speaker.player, meter)
    speaker.player = wrapped
    fallback = getattr(speaker, "fallback", None)
    if fallback is not None:
        fallback.player = wrapped


# --------------------------------------------------------------------------
# "Whoa!" when you pick it up
# --------------------------------------------------------------------------

def clip_paths(folder: Path, voice: str, kind: str) -> list[Path]:
    """Where the pickup or drop clips for a voice live (one per line)."""
    lines = PICKUP_LINES if kind == "pickup" else DROP_LINES
    return [Path(folder) / "sounds" / f"{kind}-{voice}-{i + 1}.wav" for i in range(len(lines))]


def write_wav(path: Path, audio: np.ndarray, samplerate: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pcm = (np.clip(np.asarray(audio, dtype=np.float32), -1.0, 1.0) * 32767).astype("<i2")
    tmp = path.with_suffix(".part")
    with wave.open(str(tmp), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(samplerate)
        w.writeframes(pcm.tobytes())
    tmp.replace(path)


def make_clips(folder: Path, voice: str, synthesize: Callable[[str, str], tuple[np.ndarray, int]]) -> int:
    """Make any missing pickup/drop clips with `synthesize(text, voice)`. Returns how many were made."""
    made = 0
    for kind, lines in (("pickup", PICKUP_LINES), ("drop", DROP_LINES)):
        for path, line in zip(clip_paths(folder, voice, kind), lines):
            if path.exists():
                continue
            audio, rate = synthesize(line, voice)
            if audio.size:
                write_wav(path, audio, rate)
                made += 1
    return made


def kokoro_synthesizer(speaker) -> Callable[[str, str], tuple[np.ndarray, int]] | None:
    """synthesize(text, voice) from Red's Kokoro speaker, or None if Kokoro isn't the voice."""
    engine = getattr(speaker, "_voice", None)
    create = getattr(engine, "create", None)
    if create is None:
        return None
    rate = 24_000

    def synthesize(text: str, voice: str):
        return create(text, voice, 1.0), rate
    return synthesize


def play_clip(path: Path) -> None:
    """Play a WAV without waiting and without touching Red's own audio stream."""
    try:
        import winsound
        winsound.PlaySound(str(path), winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
    except Exception:  # noqa: BLE001 - a missing sound is never worth an error
        log.debug("Couldn't play %s", path, exc_info=True)


# --------------------------------------------------------------------------
# Microphone off
# --------------------------------------------------------------------------

def mic_control(get_listener: Callable[[], object]) -> Callable[[bool], None]:
    """`muted -> None` for the companion's menu: mute or unmute the listener.

    Uses `Listener.mute(on)` (the microphone-off feature). Until a listener has it, the wake word is
    paused with `pause()` and `resume()` instead (the hotkey still works)."""
    state = {"paused": False}

    def control(muted: bool) -> None:
        listener = get_listener()
        if listener is None:
            raise RuntimeError("Red isn't listening yet")
        mute = getattr(listener, "mute", None)
        if callable(mute):
            mute(muted)
        elif muted and not state["paused"]:
            listener.pause()
            state["paused"] = True
        elif not muted and state["paused"]:
            listener.resume()
            state["paused"] = False
        if getattr(listener, "mute", None) is None:       # no mute() to say so: tell the bus ourselves
            from .. import events
            events.emit("mic", muted=muted)
    return control
