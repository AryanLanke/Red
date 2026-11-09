"""Teach Red your voice: python -m red voice-setup

Like setting up "Hey Siri" or "Hey Google": you say "Hey Red" a few times
after a beep. Red runs each recording through the same small Whisper model
the wake word detector uses and notes how it hears *your* "Hey Red" (an
accent or a microphone can turn it into "hey rat" or "hey ret"). Those
versions are saved in RED_HOME\\models\\wakeword\\hey_red_profile.json and
count as "Hey Red" from then on. It also learns how long you take to say
it, so a slower "Hey Red" isn't cut off.

What it doesn't do yet: tell your voice apart from other people's. Anyone
who says "Hey Red" the same way still wakes Red.

The recordings themselves are never saved, only the words Whisper heard.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Callable

from .audio import SAMPLE_RATE
from .wakeword import MAX_CLIP_SECONDS, PROFILE_NAME, _words, match_score, phrase_key

SAMPLES = 6
MAX_ATTEMPTS = 10
RECORD_SECONDS = 4.0
END_SILENCE = 0.6
START_TIMEOUT = 6.0

# Phrases too common to ever count as "Hey Red", however Whisper heard you.
RISKY = {"hey there", "hey you", "hi there", "hey guys", "hey man", "thank you", "okay", "yeah",
         "hello", "hey", "hi", "yes", "no", "the", "a", "and", "i", "you", "it", "is", "what"}
COMMON = {"the", "a", "an", "i", "you", "it", "is", "to", "and", "of", "there", "that", "this",
          "what", "okay", "ok", "yes", "no", "so", "oh", "um", "uh"}


def usable_phrase(key: str) -> bool:
    words = key.split()
    if not words or key in RISKY:
        return False
    if all(w in COMMON for w in words):
        return False
    if len(words) == 1 and len(words[0]) < 4:
        return False
    return True


def learn_profile(samples: list[tuple[str, float]], now: datetime | None = None) -> dict:
    """Build the profile from (what Whisper heard, seconds of speech) per sample.

    A misheard version is added only when it came up at least twice, so one
    odd recording can't teach Red to wake on something random.
    """
    heard = [text for text, _ in samples]
    already = sum(1 for text in heard if match_score(text) >= 0.5)
    keys = Counter(phrase_key(text) for text in heard
                   if 0 < len(_words(text)) <= 4 and match_score(text) < 0.5)
    phrases = sorted(k for k, n in keys.items() if n >= 2 and usable_phrase(k))
    longest = max((seconds for _, seconds in samples), default=0.0)
    max_clip = round(min(2.6, max(MAX_CLIP_SECONDS, longest + 0.4)), 2)
    covered = sum(1 for text in heard
                  if match_score(text) >= 0.5 or phrase_key(text) in phrases)
    return {
        "phrases": phrases,
        "max_clip_seconds": max_clip,
        "samples": len(samples),
        "recognized": covered,
        "heard": heard,
        "created": (now or datetime.now()).isoformat(timespec="seconds"),
    }


def profile_path(model_dir: Path) -> Path:
    return Path(model_dir) / PROFILE_NAME


def save_profile(model_dir: Path, profile: dict) -> Path:
    path = profile_path(model_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(profile, indent=2), encoding="utf-8")
    return path


def run_setup(model_dir: Path, *, record: Callable[..., object], transcribe: Callable[[object], str],
              say: Callable[[str], None], chime: Callable[[], None],
              out: Callable[[str], None] = print, samples: int = SAMPLES,
              max_attempts: int = MAX_ATTEMPTS) -> dict | None:
    """Record `samples` "Hey Red"s, learn the profile and save it. None if too few were heard."""
    intro = (f"Let's teach me your voice. After each beep, say \"Hey Red\" the way you "
             f"normally would. We'll do it {samples} times.")
    out(intro)
    say(intro)
    got: list[tuple[str, float]] = []
    attempts = 0
    while len(got) < samples and attempts < max_attempts:
        attempts += 1
        out(f"\n[{len(got) + 1}/{samples}] Say \"Hey Red\" after the beep...")
        chime()
        audio = record(max_seconds=RECORD_SECONDS, silence_seconds=END_SILENCE,
                       start_timeout=START_TIMEOUT)
        size = getattr(audio, "size", 0)
        if size == 0:
            out("  I didn't hear anything. Let's try that one again.")
            continue
        text = (transcribe(audio) or "").strip()
        seconds = max(0.0, size / SAMPLE_RATE - END_SILENCE)
        mark = "OK" if match_score(text) >= 0.5 else "learning"
        out(f"  Heard: \"{text}\" ({seconds:.1f} s) [{mark}]")
        got.append((text, seconds))
    if len(got) < max(3, samples // 2):
        msg = "I couldn't hear you well enough. Check your microphone and try again."
        out(msg)
        say(msg)
        return None
    profile = learn_profile(got)
    path = save_profile(model_dir, profile)
    out(f"\nSaved your voice profile to {path}")
    if profile["phrases"]:
        out("I'll also answer to how I heard you: " + ", ".join(f'"{p}"' for p in profile["phrases"]))
    out(f"Recognized {profile['recognized']} of {profile['samples']} tries.")
    if profile["recognized"] >= profile["samples"] - 1:
        done = "All set. I know how you say Hey Red now."
    else:
        done = ("Done, but I didn't recognize every try. Run voice setup again in a quieter "
                "place, or use Control Alt R.")
    out(done)
    say(done)
    return profile


def main(settings) -> int:
    """python -m red voice-setup: stops a hidden Red while recording, then starts it again."""
    from . import background
    from .audio import chime, record_command
    from .tts import Speaker
    from .wakeword import make_wake_transcriber

    model_dir = settings.models_dir / "wakeword"
    was_running = background.stop(settings.home)
    if was_running:
        print("Paused the Red running in the background while we record.")
    print("Loading the speech models...")
    whisper = make_wake_transcriber(model_dir)
    whisper.load()
    speaker = Speaker(settings.models_dir / "piper", settings.piper_voice)
    try:
        speaker.load()
        say = lambda text: speaker.say(text, block=True)  # noqa: E731
    except Exception:  # noqa: BLE001 - no voice model: the console still shows everything
        say = lambda text: None  # noqa: E731
    try:
        profile = run_setup(model_dir, record=record_command, transcribe=whisper.transcribe,
                            say=say, chime=chime)
    finally:
        if was_running:
            background.start(settings.home)
            print("Red is running in the background again.")
    return 0 if profile is not None else 1
