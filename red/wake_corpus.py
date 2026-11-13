"""Record your own "Hey Red" once, then measure the wake word against it offline.

    python -m red wake-test --record   about 5 minutes: "Hey Red" 30 times, "Hey Red, open
                                       YouTube" 10 times, then 2 minutes of normal talk
    python -m red wake-test --replay   runs the real detector over those recordings and prints
                                       how many would wake Red, and how many false wakes the
                                       talk caused
    python -m red wake-test --learn    learns how Whisper hears *your* "Hey Red" from them
                                       ("Headed", "Here at"...), like voice-setup does

The recordings stay in RED_HOME\\cache\\wake-corpus (your voice never goes into git or
anywhere else). Each replay adds one line to RED_HOME\\logs\\wake-replay.jsonl, so a change
to the detector can be judged by its numbers before and after.
"""

from __future__ import annotations

import json
import logging
import time
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np

from .audio import SAMPLE_RATE, to_float32, to_int16

CORPUS_DIR = "wake-corpus"
REPLAY_LOG = "wake-replay.jsonl"

# (file name prefix, what to say, how many takes, seconds per take)
PROMPTS = (
    ("hey-red", "Hey Red", 30, 3.0),
    ("hey-red-cmd", "Hey Red, open YouTube", 10, 4.5),
)
TALK_NAME = "talk"
TALK_SECONDS = 120.0
FRAME = 1280                       # 80 ms, the size the Listener feeds the detector
TAIL_SECONDS = 0.8                 # silence after each take, so a phrase at the very end is checked


def corpus_dir(settings) -> Path:
    return settings.cache_dir / CORPUS_DIR


def write_wav(path: Path, audio: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(to_int16(to_float32(audio)).tobytes())


def read_wav(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as w:
        if w.getframerate() != SAMPLE_RATE or w.getsampwidth() != 2 or w.getnchannels() != 1:
            raise ValueError(f"{path.name}: expected 16 kHz mono 16-bit")
        return to_float32(np.frombuffer(w.readframes(w.getnframes()), np.int16))


def _capture(mic, seconds: float) -> np.ndarray:
    need = int(seconds * SAMPLE_RATE)
    blocks, have = [], 0
    while have < need:
        block = to_float32(mic.read())
        blocks.append(block)
        have += block.size
    return np.concatenate(blocks)[:need]


def record(settings, *, out: Callable[[str], None] = print, microphone: Callable | None = None,
           prompts=PROMPTS, talk_seconds: float = TALK_SECONDS) -> Path:
    """Record the corpus with the real microphone. Overwrites an earlier one."""
    from .audio import Microphone

    folder = corpus_dir(settings)
    for old in folder.glob("*.wav"):
        old.unlink()
    out("Speak the way you normally would, at your normal distance from the PC.")
    with (microphone or (lambda: Microphone(block_seconds=0.08)))() as mic:
        for prefix, phrase, takes, seconds in prompts:
            out(f"\nNext: say \"{phrase}\" once each time you see the prompt.")
            for i in range(1, takes + 1):
                out(f"  [{i}/{takes}] Say \"{phrase}\" now...")
                audio = _capture(mic, seconds)
                write_wav(folder / f"{prefix}-{i:02d}.wav", audio)
                peak = float(np.abs(audio).max()) if audio.size else 0.0
                if peak < 0.05:
                    out(f"         (very quiet: peak {peak:.2f})")
        if talk_seconds > 0:
            out(f"\nLast: talk normally for {talk_seconds:.0f} seconds, or read something aloud, or let a "
                "video play. Don't say \"Hey Red\". Recording...")
            write_wav(folder / f"{TALK_NAME}.wav", _capture(mic, talk_seconds))
    out(f"\nSaved to {folder}. Now run: python -m red wake-test --replay")
    return folder


class _Heard(logging.Handler):
    """Collects the detector's 'Wake check' and 'Wake skip' lines for the file being replayed."""

    def __init__(self):
        super().__init__()
        self.lines: list[str] = []
        self.texts: list[str] = []          # just the words Whisper heard, for --learn

    def emit(self, record: logging.LogRecord) -> None:
        text = record.getMessage()
        if text.startswith("Wake check: "):
            self.lines.append(text[len("Wake check: "):])
            if record.args and isinstance(record.args, tuple) and isinstance(record.args[0], str):
                self.texts.append(record.args[0])
        elif text.startswith("Wake skip: "):
            self.lines.append("skipped, " + text[len("Wake skip: "):])


@dataclass
class Result:
    name: str
    wakes: int
    heard: list[str] = field(default_factory=list)
    texts: list[str] = field(default_factory=list)


def replay_file(detector, audio: np.ndarray, threshold: float) -> int:
    """How many times the detector wakes on this audio (reset after each wake, as the Listener does)."""
    detector.reset()
    audio = np.concatenate([audio, np.zeros(int(TAIL_SECONDS * SAMPLE_RATE), np.float32)])
    wakes = 0
    for i in range(0, audio.size, FRAME):
        if detector.score(audio[i:i + FRAME]) >= threshold:
            wakes += 1
            detector.reset()
    return wakes


def _run_corpus(settings, out: Callable[[str], None], make_detector: Callable | None) -> list[Result] | None:
    """Every recording through the detector, with what it heard. None (and a hint) if there are none."""
    from .wakeword import HeyRedDetector

    folder = corpus_dir(settings)
    files = sorted(folder.glob("*.wav"))
    if not files:
        out(f"No recordings in {folder}. Record them first: python -m red wake-test --record")
        return None
    detector = (make_detector or HeyRedDetector.create)(settings.models_dir / "wakeword")
    heard = _Heard()
    wake_log = logging.getLogger("red.wakeword")
    wake_log.addHandler(heard)
    old_level = wake_log.level
    wake_log.setLevel(logging.INFO)
    results: list[Result] = []
    try:
        for path in files:
            heard.lines, heard.texts = [], []
            wakes = replay_file(detector, read_wav(path), settings.wakeword_threshold)
            results.append(Result(path.stem, wakes, list(heard.lines), list(heard.texts)))
    finally:
        wake_log.removeHandler(heard)
        wake_log.setLevel(old_level)
    return results


def learn(settings, *, out: Callable[[str], None] = print, make_detector: Callable | None = None,
          now=None) -> dict | None:
    """Learn how Whisper hears *your* "Hey Red" from the recordings, like voice-setup does.

    A misheard version ("Headed", "Here at") is added to RED_HOME\\models\\wakeword\\
    hey_red_profile.json only if it came up at least twice, isn't a common word, and never
    started anything you said in the 2 minutes of normal talk (so it can't wake Red by itself).
    """
    from .voice_setup import learn_profile, save_profile
    from .wakeword import load_profile, phrase_key

    results = _run_corpus(settings, out, make_detector)
    if results is None:
        return None
    takes = [phrase_key(t) for r in results if r.name.startswith("hey-red") for t in r.texts]
    talk = {phrase_key(t) for r in results if r.name == TALK_NAME for t in r.texts}
    learned = learn_profile([(t, 0.0) for t in takes if t], now=now)
    risky = sorted(p for p in learned["phrases"] if p in talk)
    model_dir = settings.models_dir / "wakeword"
    profile = load_profile(model_dir)
    before = set(p for p in profile.get("phrases", []) if isinstance(p, str))
    phrases = sorted((before | set(learned["phrases"])) - set(risky))
    profile["phrases"] = phrases
    profile.setdefault("max_clip_seconds", learned["max_clip_seconds"])
    profile["learned_from_recordings"] = learned["created"]
    path = save_profile(model_dir, profile)
    new = sorted(set(phrases) - before)
    out(f"Heard your \"Hey Red\" as: {', '.join(sorted(set(takes))) or 'nothing'}")
    out(("Red will now also wake on: " + ", ".join(f'"{p}"' for p in new)) if new
        else "Nothing new to learn.")
    if risky:
        out("Left out, because you also said them in normal talk: " + ", ".join(f'"{p}"' for p in risky))
    out(f"Saved to {path}. Restart Red to use it, and run: python -m red wake-test --replay")
    return profile


def replay(settings, *, out: Callable[[str], None] = print, make_detector: Callable | None = None,
           now: Callable[[], float] = time.time) -> dict | None:
    """Run the real detector over the recorded corpus and print the score card."""
    results = _run_corpus(settings, out, make_detector)
    if results is None:
        return None
    threshold = settings.wakeword_threshold

    groups: dict[str, list[Result]] = {}
    for r in results:
        key = TALK_NAME if r.name == TALK_NAME else r.name.rsplit("-", 1)[0]
        groups.setdefault(key, []).append(r)
    summary: dict = {"time": round(now(), 1), "threshold": threshold}
    for prefix, phrase, _, _ in PROMPTS:
        rs = groups.get(prefix, [])
        if not rs:
            continue
        hits = sum(1 for r in rs if r.wakes > 0)
        out(f"\n\"{phrase}\": {hits}/{len(rs)} woke Red ({100 * hits / len(rs):.0f}%)")
        for r in rs:
            if r.wakes == 0:
                out(f"  missed {r.name}: " + ("; ".join(r.heard) if r.heard else "never checked (the "
                                               "microphone heard no speech)"))
        summary[prefix] = [hits, len(rs)]
    talk = groups.get(TALK_NAME)
    if talk:
        false = talk[0].wakes
        out(f"\nNormal talk: {false} false wake{'s' if false != 1 else ''}")
        for line in talk[0].heard:
            if line.startswith("heard") and "score 0.00" not in line:
                out(f"  {line}")
        summary["false_wakes"] = false
    try:
        log_path = settings.logs_dir / REPLAY_LOG
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(summary) + "\n")
    except OSError:
        pass
    return summary
