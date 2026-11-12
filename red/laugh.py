"""Real laughter: Red plays a short laugh instead of reading "haha" aloud.

TTS can only read words, so a written laugh ("haha", "heh") would be spoken
literally. Red keeps a few short, licence-clean human laugh recordings
(16 kHz mono WAVs under red/assets/laugh) and, when a reply contains a laugh
word, strips the word and plays one of the clips in its place.

The clips are CC0 / public domain, from the sound-cc0 and
CC0-Public-Domain-Sounds collections and BigSoundBank, resampled to 16 kHz
mono and normalised. More clips can be dropped into the folder as
laugh-N.wav and Red picks them up.
"""

from __future__ import annotations

import logging
import random
import re
import wave
from pathlib import Path
from typing import Callable

import numpy as np

log = logging.getLogger(__name__)

ASSETS_DIR = Path(__file__).with_name("assets") / "laugh"
SAMPLE_RATE = 16_000

# The words the model writes for a laugh. Word boundaries keep "haphazard"
# out; the optional space/hyphen covers "ha ha" and "ha-ha".
_LAUGH_WORD = re.compile(
    r"\b(?:ha(?:[ -]?ha)+h*|ha|heh(?:eh)?|hehe(?:he)?|hihi|tee[ -]?hee|lol+|lmf?ao|rofl)\b",
    re.IGNORECASE,
)
_SPLIT = re.compile(f"({_LAUGH_WORD.pattern})", re.IGNORECASE)


def has_laugh(text: str) -> bool:
    """True when the text contains a laugh word (without loading any clips)."""
    return _LAUGH_WORD.search(text) is not None


def _read(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as w:
        audio = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    return (audio.astype(np.float32) / 32768.0).reshape(-1)


def load_clips(directory: Path = ASSETS_DIR) -> list[np.ndarray]:
    """The bundled laugh clips, 16 kHz mono float32; [] when none can be read."""
    clips = []
    for path in sorted(directory.glob("laugh-*.wav")):
        try:
            clips.append(_read(path))
        except Exception:  # noqa: BLE001 - one bad file must not break the voice
            log.exception("Couldn't read laugh clip %s", path)
    return clips


def split_laughs(text: str, clips: list[np.ndarray],
                 choose: Callable[[list[np.ndarray]], np.ndarray] = random.choice,
                 ) -> list[tuple[str, str | np.ndarray]]:
    """Split `text` into ("text", words) and ("laugh", clip) segments, in order.

    Each run of laugh words ("haha, heh") becomes one clip. Without any clips
    the text comes back whole, so the TTS reads the words as before.
    """
    if not clips or _LAUGH_WORD.search(text) is None:
        return [("text", text)]
    out: list[tuple[str, str | np.ndarray]] = []
    for piece in _SPLIT.split(text):
        if not piece:
            continue
        if _LAUGH_WORD.fullmatch(piece):
            if not out or out[-1][0] != "laugh":
                out.append(("laugh", choose(clips)))
            continue
        stripped = piece.strip(" \t,;:")
        if stripped and re.search(r"\w", stripped):
            out.append(("text", stripped))
    return out
