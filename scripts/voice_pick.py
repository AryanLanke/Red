"""Compare Kokoro voices by measurement: pitch, loudness, pace and how well Whisper understands them.

    python scripts/voice_pick.py [--prefix am_ bm_] [--out DIR]

Renders three of Red's lines with every voice (the WAVs go to RED_HOME\\cache\\voice-picks, never
git) and prints one row per voice:
  f0     median pitch in Hz of the voiced frames (a man's voice should be under 165 Hz)
  range  pitch spread in semitones (a flat voice reads as bored, a huge one as theatrical)
  dB     loudness (RMS of the speech, dBFS); the speaker evens these out, but it shows quiet voices
  peak   highest sample (near 1.0 means clipping)
  secs   total duration of the three lines; chars/s is the pace
  WER    word errors when Whisper (base.en) listens back: a voice it cannot understand is a poor pick
"""

from __future__ import annotations

import argparse
import os
import re
import statistics
import sys
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Red's kind of line: dry, short, a question back, a bit of an edge.
RED_LINES = (
    "Sure, opening that now. Anything else, or is that it?",
    "Honestly? Not much. You've been quiet for a while, though.",
    "That's the third time you've asked. Fine, here you go.",
)
RATE = 24_000


def home() -> Path:
    return Path(os.environ.get("RED_HOME", r"D:\RED"))


def median_f0(audio: np.ndarray, rate: int = RATE) -> tuple[float, float]:
    """(median pitch in Hz, spread in semitones) of the voiced frames, by autocorrelation."""
    frame, hop = int(0.04 * rate), int(0.01 * rate)
    lo, hi = int(rate / 400), int(rate / 60)             # 60 to 400 Hz
    pitches: list[float] = []
    loud = np.sqrt(np.mean(audio.astype(np.float64) ** 2)) or 1e-9
    for start in range(0, audio.size - frame, hop):
        chunk = audio[start:start + frame].astype(np.float64)
        if np.sqrt(np.mean(chunk ** 2)) < 0.4 * loud:      # quiet: not voiced
            continue
        chunk = chunk - chunk.mean()
        corr = np.correlate(chunk, chunk, "full")[chunk.size - 1:]
        if corr[0] <= 0:
            continue
        corr = corr / corr[0]
        lag = lo + int(np.argmax(corr[lo:hi]))
        if corr[lag] > 0.5:                                  # clearly periodic
            pitches.append(rate / lag)
    if len(pitches) < 10:
        return 0.0, 0.0
    semis = 12 * np.log2(np.array(pitches) / np.median(pitches))
    return float(np.median(pitches)), float(np.percentile(semis, 90) - np.percentile(semis, 10))


def write_wav(path: Path, audio: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes((np.clip(audio, -1, 1) * 32767).astype(np.int16).tobytes())


def words(text: str) -> list[str]:
    return re.sub(r"[^a-z0-9' ]", " ", text.lower()).split()


def errors(reference: str, heard: str) -> int:
    ref, hyp = words(reference), words(heard)
    prev = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        cur = [i]
        for j, h in enumerate(hyp, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (r != h)))
        prev = cur
    return prev[-1]


def measure(voices: list[str], lines=RED_LINES, out: Path | None = None) -> list[dict]:
    from red.audio import resample
    from red.stt import Transcriber
    from red.tts_kokoro import KokoroEngine, MODEL_FILE, VOICES_FILE

    folder = home() / "models" / "kokoro"
    engine = KokoroEngine(folder / MODEL_FILE, folder / VOICES_FILE)
    whisper = Transcriber(home() / "models" / "whisper", "base.en", "cpu", beam_size=1)
    rows = []
    for voice in voices:
        clips = [engine.create(line, voice) for line in lines]
        joined = np.concatenate([np.concatenate([c, np.zeros(int(0.3 * RATE), np.float32)]) for c in clips])
        f0, spread = median_f0(joined)
        speech = np.concatenate(clips)
        rms = float(np.sqrt(np.mean(speech.astype(np.float64) ** 2)))
        err = sum(errors(line, whisper.transcribe(resample(c, RATE, 16_000))) for line, c in zip(lines, clips))
        n_words = sum(len(words(line)) for line in lines)
        chars = sum(len(line) for line in lines)
        rows.append({"voice": voice, "f0": f0, "range": spread, "db": 20 * np.log10(rms + 1e-9),
                     "peak": float(np.abs(speech).max()), "secs": speech.size / RATE,
                     "cps": chars / (speech.size / RATE), "wer": err / n_words * 100})
        if out is not None:
            for i, clip in enumerate(clips, 1):
                write_wav(out / f"{voice}_{i}.wav", clip)
    return rows


def main() -> None:
    from red.tts_kokoro import VOICES

    p = argparse.ArgumentParser()
    p.add_argument("--prefix", nargs="*", default=["am_", "bm_"])
    p.add_argument("--out", type=Path, default=None)
    args = p.parse_args()
    voices = [v for v in VOICES if v.startswith(tuple(args.prefix))]
    out = args.out or home() / "cache" / "voice-picks"
    rows = measure(voices, out=out)
    print(f"{'voice':12s} {'f0 Hz':>6s} {'range':>6s} {'dB':>6s} {'peak':>5s} {'secs':>5s} {'chars/s':>7s} {'WER%':>5s}")
    for r in sorted(rows, key=lambda r: r["f0"]):
        print(f"{r['voice']:12s} {r['f0']:6.0f} {r['range']:6.1f} {r['db']:6.1f} {r['peak']:5.2f} {r['secs']:5.1f} "
              f"{r['cps']:7.1f} {r['wer']:5.1f}")
    print(f"median of medians: {statistics.median(r['f0'] for r in rows):.0f} Hz; clips in {out}")


if __name__ == "__main__":
    main()
