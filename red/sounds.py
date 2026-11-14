"""Reaction sounds: short vocal clips (a gasp, "kya!", a giggle, a yawn) for the companion.

A sound pack is a folder `RED_HOME\\sounds\\<pack id>\\` with a `pack.toml` and short WAVs named
`<kind>_<n>.wav`, with the kinds below (plan.md 0.2). `scripts/make_sounds.py` builds the packs
that Red ships (jp-male-1, jp-male-2, jp-female-1, jp-female-2); a companion's `sounds` field
(companion.toml) names the pack it uses.

    packs()                    -> {id: Pack}   every installed pack that has a licence and a source
    pick("jp-male-1", "giggle") -> Path | None  a random variant of that kind
    play(path)                 -> bool          starts it and returns at once; False if Red is talking
    preview_voice("af_bella", "Hi, I'm Remy.") -> Path   a WAV of that Kokoro voice, for the app

Nothing ships without a licence: a pack whose pack.toml lacks `license` or `source` is ignored.
`play` never plays over Red's own voice: the voice loop tells it how to tell (`watch_voice`).
"""

from __future__ import annotations

import hashlib
import logging
import random
import threading
import tomllib
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

log = logging.getLogger(__name__)

KINDS = ("pickup", "drop", "hover", "surprised", "laugh", "giggle", "sigh", "yawn", "hmm",
         "annoyed", "happy", "sleepy")
MAX_SECONDS = 1.5

_voice_busy: Callable[[], bool] | None = None


def watch_voice(is_speaking: Callable[[], bool] | None) -> None:
    """Tell `play` how to know that Red is talking (the speaker's `speaking`). None: never busy."""
    global _voice_busy
    _voice_busy = is_speaking


def red_speaking() -> bool:
    try:
        return bool(_voice_busy()) if _voice_busy is not None else False
    except Exception:  # noqa: BLE001 - a broken check must not mute the sounds for good
        return False


def sounds_dir(home: Path | str | None = None) -> Path:
    from .config import red_home
    return Path(home or red_home()) / "sounds"


@dataclass(frozen=True)
class Pack:
    id: str
    name: str
    gender: str                     # male | female
    style: str
    license: str
    source: str
    path: Path
    kinds: dict[str, tuple[Path, ...]] = field(default_factory=dict)

    def variants(self, kind: str) -> tuple[Path, ...]:
        return self.kinds.get(kind, ())


def _read_pack(folder: Path) -> Pack | None:
    try:
        data = tomllib.loads((folder / "pack.toml").read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as e:
        log.warning("Sound pack %s: can't read pack.toml (%s)", folder.name, e)
        return None
    license_text, source = str(data.get("license", "")).strip(), str(data.get("source", "")).strip()
    if not license_text or not source:
        log.warning("Sound pack %s has no licence or source in pack.toml: not used", folder.name)
        return None
    kinds: dict[str, tuple[Path, ...]] = {}
    for kind in KINDS:
        files = sorted(p for p in folder.glob(f"{kind}_*.wav") if p.is_file())
        if files:
            kinds[kind] = tuple(files)
    if not kinds:
        return None
    gender = str(data.get("gender", "")).lower()
    return Pack(id=folder.name, name=str(data.get("name", folder.name)),
                gender=gender if gender in ("male", "female") else "", style=str(data.get("style", "")),
                license=license_text, source=source, path=folder, kinds=kinds)


def packs(home: Path | str | None = None) -> dict[str, Pack]:
    """Every installed sound pack, by id (a folder under RED_HOME\\sounds with a valid pack.toml)."""
    found: dict[str, Pack] = {}
    root = sounds_dir(home)
    try:
        folders = sorted(p for p in root.iterdir() if p.is_dir())
    except OSError:
        return found
    for folder in folders:
        pack = _read_pack(folder)
        if pack is not None:
            found[pack.id] = pack
    return found


def pick(pack_id: str, kind: str, home: Path | str | None = None,
         rng: random.Random | None = None, avoid: Path | None = None) -> Path | None:
    """A random variant of `kind` from the pack, or None (no such pack or kind). `avoid`: the last
    one played, so the same sound doesn't come twice in a row when there is another."""
    pack = packs(home).get(pack_id or "")
    if pack is None:
        return None
    choices = list(pack.variants(kind))
    if avoid is not None and len(choices) > 1:
        choices = [c for c in choices if c != avoid] or choices
    return (rng or random).choice(choices) if choices else None


def _winsound_play(path: Path) -> None:
    import winsound
    winsound.PlaySound(str(path), winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)


def play(path: Path | str | None, *, player: Callable[[Path], None] = _winsound_play,
         force: bool = False) -> bool:
    """Start the sound and return at once. False when there is nothing to play or Red is talking
    (a reaction never cuts across the voice). Plays on Windows' own sound call, so it never touches
    Red's speech stream."""
    if path is None:
        return False
    path = Path(path)
    if not force and red_speaking():
        return False
    if not path.is_file():
        return False
    try:
        player(path)
    except Exception:  # noqa: BLE001 - a missing sound is never worth an error
        log.debug("Couldn't play %s", path, exc_info=True)
        return False
    return True


# --- voice previews, for the app -------------------------------------------------------------------

_engines: dict[str, object] = {}
_engine_lock = threading.Lock()


def _kokoro_engine(home: Path):
    from .tts_kokoro import MODEL_FILE, VOICES_FILE, KokoroEngine
    folder = home / "models" / "kokoro"
    key = str(folder)
    with _engine_lock:
        engine = _engines.get(key)
        if engine is None:
            if not (folder / MODEL_FILE).is_file() or not (folder / VOICES_FILE).is_file():
                raise FileNotFoundError("Kokoro's files aren't downloaded yet (python -m red setup)")
            engine = _engines[key] = KokoroEngine(folder / MODEL_FILE, folder / VOICES_FILE)
    return engine


def preview_voice(voice_id: str, text: str, home: Path | str | None = None, *,
                  engine=None, speed: float = 1.0) -> Path:
    """A WAV (24 kHz mono) of `text` in the Kokoro voice `voice_id`, for the app's play button.

    Kept in RED_HOME\\cache\\voice-preview, so the same voice and text are made once. Raises ValueError
    for an unknown voice or empty text and FileNotFoundError if Kokoro isn't installed.
    """
    import numpy as np
    from .config import red_home
    from .tts_kokoro import SAMPLE_RATE, VOICES, speakable

    if voice_id not in VOICES:
        raise ValueError(f"{voice_id!r} isn't a Kokoro voice")
    text = " ".join((text or "").split())
    if not text:
        raise ValueError("Nothing to say")
    home = Path(home or red_home())
    key = hashlib.sha1(f"{text}|{speed}".encode("utf-8")).hexdigest()[:10]
    out = home / "cache" / "voice-preview" / f"{voice_id}-{key}.wav"
    if out.is_file():
        return out
    engine = engine or _kokoro_engine(home)
    audio = engine.create(speakable(text), voice_id, speed)
    audio = np.concatenate([audio, np.zeros(int(0.15 * SAMPLE_RATE), np.float32)]) if audio.size else audio
    out.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(out), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes((np.clip(audio, -1, 1) * 32767).astype(np.int16).tobytes())
    return out


__all__ = ["KINDS", "Pack", "packs", "pick", "play", "preview_voice", "red_speaking", "sounds_dir", "watch_voice"]
