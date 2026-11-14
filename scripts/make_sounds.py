"""Build the companions' reaction sound packs: python scripts/make_sounds.py [--only jp-male-1] [--list]

Short Japanese, anime-style reactions (gasps, "kya!", giggles, "hmm", yawns) for picking the
companion up, dropping it, hovering and so on. The packs land in RED_HOME\\sounds\\<pack id>\\ (never
in git: they are build output) with a pack.toml that carries the licence and the source.

Where the sounds come from (plan.md 0.3 lane 1 task 4, the user's order):
  a. VOICEVOX: not used. Its engine is unsigned native code that Smart App Control blocks on this
     PC, and each character's terms (credit format, redistribution of the audio) differ and could
     not be confirmed from the official pages tonight. "If unsure, don't ship it."
  b. Kokoro-82M's Japanese voices (jf_alpha, jf_tebukuro, jm_kumo): Apache-2.0, the model Red already
     speaks with. The reactions are written as Kokoro phonemes here (わっ = wa↗ʔ, えへへ = eheheː),
     so no Japanese text phonemizer (pyopenjtalk, native code) is needed. Trimmed, evened out in
     loudness, and for jp-male-2 pitched up (a modified copy, which Apache-2.0 allows).
  c. CC0 vocal packs: none used (OpenGameArt blocked the page fetch tonight, so no licence could be
     checked). Nothing was ripped from anime, games or paid packs.

Each sound is under 1.5 s and has the same loudness. Kinds (plan.md 0.2): pickup, drop, hover,
surprised, laugh, giggle, sigh, yawn, hmm, annoyed, happy, sleepy; two variants of each.
"""

from __future__ import annotations

import argparse
import datetime
import os
import sys
import wave
from dataclasses import dataclass
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

RATE = 24_000
MAX_SECONDS = 1.4                # packs promise under 1.5 s
TARGET_RMS_DB = -21.0            # every sound the same loudness
PEAK_CEILING = 0.89              # about -1 dBFS

LICENSE = ("Kokoro-82M by hexgrad, Apache-2.0 (https://huggingface.co/hexgrad/Kokoro-82M); "
           "audio synthesised for Red{extra}. Credit: Kokoro-82M (Apache-2.0).")
SOURCE = "Kokoro-82M ONNX v1.0 (thewh1teagle/kokoro-onnx), voice {voice}, phonemes written by hand, scripts/make_sounds.py"

# kind -> two variants: (what it is in Japanese, Kokoro phonemes). ↗ rises, ʔ is the stop of っ.
REACTIONS: dict[str, tuple[tuple[str, str], tuple[str, str]]] = {
    "pickup":    (("きゃっ!", "kʲa↗ʔ!"), ("わっ!", "wa↗ʔ!")),
    "drop":      (("いたっ!", "itaʔ!"), ("あうっ!", "aɯʔ!")),
    "hover":     (("ん?", "ɴ↗?"), ("おっ?", "o↗ʔ?")),
    "surprised": (("えっ!?", "e↗ʔ!?"), ("えー!?", "eː↗!?")),
    "laugh":     (("あはは!", "ahahaha!"), ("ふはは!", "ɸɯhahaha!")),
    "giggle":    (("ふふっ", "ɸɯɸɯʔ"), ("えへへ", "eheheː")),
    "sigh":      (("はぁ…", "haːː…"), ("ふぅ…", "ɸɯːː…")),
    "yawn":      (("ふぁ〜", "ɸaaːː…"), ("ふあぁーん", "ɸɯaaːːɴ…")),
    "hmm":       (("うーん", "ɯːɴ…"), ("んー", "ɴːː…")),
    "annoyed":   (("もう!", "moː!"), ("むぅ…", "mɯː…")),
    "happy":     (("やった!", "jaʔta!"), ("わーい!", "waːi!")),
    "sleepy":    (("ねむ…", "nemɯ…"), ("ふぁ…", "ɸa…")),
}
KINDS = tuple(REACTIONS)


@dataclass(frozen=True)
class PackSpec:
    id: str
    name: str
    gender: str
    voice: str               # Kokoro voice
    semitones: float = 0.0   # pitch shift of the copy (0: as Kokoro made it)
    speed: float = 1.0
    note: str = ""


PACKS = (
    PackSpec("jp-male-1", "Japanese anime, male 1", "male", "jm_kumo", 0.0, 1.05),
    PackSpec("jp-male-2", "Japanese anime, male 2 (higher, younger)", "male", "jm_kumo", 5.0, 1.1,
             "; pitched up 5 semitones"),
    PackSpec("jp-female-1", "Japanese anime, female 1 (bright)", "female", "jf_alpha", 0.0, 1.0),
    PackSpec("jp-female-2", "Japanese anime, female 2 (softer)", "female", "jf_tebukuro", 0.0, 1.05),
)


def home() -> Path:
    return Path(os.environ.get("RED_HOME", r"D:\RED"))


def shift_pitch(audio: np.ndarray, semitones: float) -> np.ndarray:
    """Pitch up by resampling (the sound also gets shorter, like a younger, quicker voice)."""
    if not semitones:
        return audio
    factor = 2 ** (semitones / 12)
    n = int(audio.size / factor)
    return np.interp(np.linspace(0, audio.size - 1, n), np.arange(audio.size), audio).astype(np.float32)


def finish(audio: np.ndarray) -> np.ndarray:
    """Trim, fade, cap at MAX_SECONDS, and set the same loudness for every sound."""
    from red.tts_kokoro import trim
    audio = trim(audio.astype(np.float32), top_db=45.0)
    audio = audio[: int(MAX_SECONDS * RATE)]
    fade_in, fade_out = int(0.004 * RATE), int(0.04 * RATE)
    if audio.size > fade_in + fade_out:
        audio[:fade_in] *= np.linspace(0, 1, fade_in)
        audio[-fade_out:] *= np.linspace(1, 0, fade_out)
    rms = float(np.sqrt(np.mean(audio.astype(np.float64) ** 2))) or 1e-9
    audio = audio * (10 ** (TARGET_RMS_DB / 20) / rms)
    peak = float(np.abs(audio).max())
    if peak > PEAK_CEILING:                      # a loud short pop: lower it, accepting a quieter sound
        audio = audio * (PEAK_CEILING / peak)
    return audio.astype(np.float32)


def write_wav(path: Path, audio: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes((np.clip(audio, -1, 1) * 32767).astype(np.int16).tobytes())


def pack_toml(spec: PackSpec) -> str:
    license_text = LICENSE.format(extra=spec.note)
    lines = [
        f'name = "{spec.name}"',
        f'gender = "{spec.gender}"',
        'style = "anime-ja"',
        f'license = "{license_text}"',
        f'source = "{SOURCE.format(voice=spec.voice)}"',
        f'voice = "{spec.voice}"',
        f'built = "{datetime.date.today().isoformat()}"',
        "kinds = [" + ", ".join(f'"{k}"' for k in KINDS) + "]",
        "",
    ]
    return "\n".join(lines)


def build(specs=PACKS, out: Path | None = None, engine=None) -> dict[str, list[Path]]:
    from red.tts_kokoro import KokoroEngine, MODEL_FILE, VOICES_FILE

    if engine is None:
        folder = home() / "models" / "kokoro"
        engine = KokoroEngine(folder / MODEL_FILE, folder / VOICES_FILE)
    out = out or home() / "sounds"
    made: dict[str, list[Path]] = {}
    for spec in specs:
        folder = out / spec.id
        files: list[Path] = []
        for kind, variants in REACTIONS.items():
            for n, (_label, phonemes) in enumerate(variants, 1):
                audio = engine.create_phonemes(phonemes, spec.voice, spec.speed)
                audio = finish(shift_pitch(audio, spec.semitones))
                path = folder / f"{kind}_{n}.wav"
                write_wav(path, audio)
                files.append(path)
        (folder / "pack.toml").write_text(pack_toml(spec), encoding="utf-8")
        made[spec.id] = files
        print(f"{spec.id}: {len(files)} sounds in {folder}")
    return made


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--only", nargs="*", help="pack ids to build")
    p.add_argument("--list", action="store_true")
    args = p.parse_args()
    if args.list:
        for spec in PACKS:
            print(f"{spec.id}: {spec.name} ({spec.voice})")
        return
    specs = [s for s in PACKS if not args.only or s.id in args.only]
    build(specs)


if __name__ == "__main__":
    main()
