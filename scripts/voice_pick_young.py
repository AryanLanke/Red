"""Pick young, natural and clearly different Kokoro voices for Red, Remy and Asha, by measurement.

    python scripts/voice_pick_young.py [--prefix af_ am_ bm_ bf_] [--blends a+b c+d] [--speeds 1.0 1.05 1.1]

For each voice and speed: median f0 (Hz), pitch spread (semitones), spectral centroid (Hz, the
"brightness" of the voice; higher reads younger and lighter), pace (characters per second of
speech), peak (clipping check) and Whisper's word errors reading it back. The WAVs go to
RED_HOME\\cache\\voice-picks-young\\ (never git) so the user can hear them in two minutes.
Blends are written "af_bella:0.6+af_sky:0.4" (a weighted mix of the two voices' style vectors).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from voice_pick import RATE, errors, median_f0, words, write_wav  # noqa: E402

LINES = (
    "Hey, it's me. Want me to put on something good, or are we working?",
    "Okay, that's done. Anything else? I'm right here if you need me.",
)


def home() -> Path:
    return Path(os.environ.get("RED_HOME", r"D:\RED"))


def centroid(audio: np.ndarray, rate: int = RATE) -> float:
    """Energy-weighted mean spectral centroid (Hz) of the louder frames."""
    frame, hop = 1024, 512
    win = np.hanning(frame)
    freqs = np.fft.rfftfreq(frame, 1 / rate)
    loud = np.sqrt(np.mean(audio.astype(np.float64) ** 2)) or 1e-9
    num = den = 0.0
    for s in range(0, audio.size - frame, hop):
        chunk = audio[s:s + frame].astype(np.float64)
        if np.sqrt(np.mean(chunk ** 2)) < 0.5 * loud:
            continue
        mag = np.abs(np.fft.rfft(chunk * win))
        num += float((freqs * mag).sum())
        den += float(mag.sum())
    return num / den if den else 0.0


def measure(engine, whisper, voice: str, speed: float, out: Path | None) -> dict:
    from red.audio import resample
    clips = [engine.create(line, voice, speed) for line in LINES]
    gap = np.zeros(int(0.3 * RATE), np.float32)
    joined = np.concatenate([np.concatenate([c, gap]) for c in clips])
    speech = np.concatenate(clips)
    f0, spread = median_f0(joined)
    err = sum(errors(line, whisper.transcribe(resample(c, RATE, 16_000))) for line, c in zip(LINES, clips))
    n_words = sum(len(words(line)) for line in LINES)
    row = {"voice": voice, "speed": speed, "f0": round(f0), "range": round(spread, 1),
           "centroid": round(centroid(speech)), "peak": round(float(np.abs(speech).max()), 2),
           "cps": round(sum(len(line) for line in LINES) / (speech.size / RATE), 1),
           "wer": round(err / n_words * 100, 1)}
    if out is not None:
        safe = voice.replace(":", "").replace("+", "_")
        write_wav(out / f"{safe}_x{speed}.wav", joined)
    return row


def main() -> None:
    from red.stt import Transcriber
    from red.tts_kokoro import KokoroEngine, MODEL_FILE, VOICES, VOICES_FILE

    p = argparse.ArgumentParser()
    p.add_argument("--prefix", nargs="*", default=["af_", "am_", "bf_", "bm_"])
    p.add_argument("--voices", nargs="*", help="exact voices (and blends) instead of --prefix")
    p.add_argument("--speeds", nargs="*", type=float, default=[1.0, 1.05, 1.1])
    p.add_argument("--out", type=Path, default=home() / "cache" / "voice-picks-young")
    p.add_argument("--json", type=Path, default=None)
    args = p.parse_args()
    voices = args.voices or [v for v in VOICES if v.startswith(tuple(args.prefix))]
    folder = home() / "models" / "kokoro"
    engine = KokoroEngine(folder / MODEL_FILE, folder / VOICES_FILE)
    whisper = Transcriber(home() / "models" / "whisper", "base.en", "cpu", beam_size=1)
    rows = []
    print(f"{'voice':28s} {'speed':>5s} {'f0':>5s} {'range':>5s} {'bright':>6s} {'chars/s':>7s} {'peak':>5s} {'WER%':>5s}")
    for voice in voices:
        for speed in args.speeds:
            r = measure(engine, whisper, voice, speed, args.out)
            rows.append(r)
            print(f"{r['voice']:28s} {r['speed']:5.2f} {r['f0']:5d} {r['range']:5.1f} {r['centroid']:6d} "
                  f"{r['cps']:7.1f} {r['peak']:5.2f} {r['wer']:5.1f}", flush=True)
    if args.json:
        args.json.write_text(json.dumps(rows, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
