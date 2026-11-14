"""Download and measure the candidate clips (dev tool; audio stays in RED_HOME\\cache, never git).

    python scripts/sound_measure.py D:\\RED\\cache\\sound-work\\cands.json

Per clip: duration, RMS and peak (dBFS), leading/trailing silence, median f0 (a man is under about
165 Hz, a young woman 190-300), the share of the clip that is voiced, and what Whisper hears (a
sanity check for "hey", "ow", "whoa"; non-speech sounds come back as nothing or as a guess).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

RATE = 24_000


def decode(path: Path, rate: int = RATE) -> np.ndarray:
    """Any audio file as mono float32 at `rate` (PyAV, which faster-whisper already needs)."""
    import av
    chunks = []
    with av.open(str(path)) as container:
        stream = container.streams.audio[0]
        resampler = av.AudioResampler(format="flt", layout="mono", rate=rate)
        for frame in container.decode(stream):
            for f in resampler.resample(frame):
                chunks.append(f.to_ndarray().reshape(-1))
        for f in resampler.resample(None) or []:
            chunks.append(f.to_ndarray().reshape(-1))
    return np.concatenate(chunks).astype(np.float32) if chunks else np.zeros(0, np.float32)


def db(x: float) -> float:
    return 20 * float(np.log10(max(x, 1e-9)))


def silence_edges(audio: np.ndarray, rate: int = RATE, floor_db: float = -40.0) -> tuple[float, float]:
    """Seconds of near-silence at the start and at the end (relative to the clip's peak)."""
    if audio.size == 0:
        return 0.0, 0.0
    hop = int(0.01 * rate)
    n = audio.size // hop
    if n == 0:
        return 0.0, 0.0
    env = np.sqrt(np.mean(audio[: n * hop].reshape(n, hop).astype(np.float64) ** 2, axis=1))
    loud = np.nonzero(env > env.max() * 10 ** (floor_db / 20))[0]
    if loud.size == 0:
        return n * 0.01, 0.0
    return loud[0] * 0.01, (n - 1 - loud[-1]) * 0.01


def measure_audio(audio: np.ndarray, rate: int = RATE) -> dict:
    from voice_pick import median_f0
    peak = float(np.abs(audio).max()) if audio.size else 0.0
    rms = float(np.sqrt(np.mean(audio.astype(np.float64) ** 2))) if audio.size else 0.0
    head, tail = silence_edges(audio, rate)
    f0, spread = median_f0(audio, rate)
    return {"secs": round(audio.size / rate, 3), "rms_db": round(db(rms), 1), "peak_db": round(db(peak), 1),
            "head_s": round(head, 2), "tail_s": round(tail, 2), "f0": round(f0), "f0_range": round(spread, 1)}


def main() -> None:
    from red.audio import resample
    from red.stt import Transcriber
    from sound_search import fetch

    p = argparse.ArgumentParser()
    p.add_argument("cands")
    p.add_argument("--dl", default=r"D:\RED\cache\sound-work\dl")
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--no-whisper", action="store_true", help="skip the slow read-back (do it later with --heard)")
    p.add_argument("--heard", nargs="*", help="only add what Whisper hears to these ids (already measured)")
    args = p.parse_args()
    cands_path = Path(args.cands)
    cands = json.loads(cands_path.read_text(encoding="utf-8"))
    meas_path = cands_path.with_name("meas.json")
    meas = json.loads(meas_path.read_text(encoding="utf-8")) if meas_path.is_file() else {}
    dl = Path(args.dl)
    dl.mkdir(parents=True, exist_ok=True)
    whisper = None if args.no_whisper else Transcriber(Path(r"D:\RED\models\whisper"), "base.en", "cpu", beam_size=1)
    if args.heard is not None:
        whisper = Transcriber(Path(r"D:\RED\models\whisper"), "base.en", "cpu", beam_size=1)
        for sid in args.heard:
            audio = decode(dl / f"{sid}.mp3")
            meas.setdefault(sid, {})["heard"] = whisper.transcribe(resample(audio, RATE, 16_000)).strip()
        meas_path.write_text(json.dumps(meas, indent=1), encoding="utf-8")
        print(len(args.heard), "read back")
        return
    done = 0
    for sid, c in cands.items():
        if sid in meas:
            continue
        if args.limit and done >= args.limit:
            break
        url = c["mp3"].replace("-lq.", "-hq.")
        f = dl / f"{sid}.mp3"
        try:
            if not f.is_file():
                f.write_bytes(fetch(url, binary=True, pause=0.15))
            audio = decode(f)
            m = measure_audio(audio)
            if whisper is not None:
                m["heard"] = whisper.transcribe(resample(audio, RATE, 16_000)).strip() if audio.size > 1600 else ""
        except Exception as e:  # noqa: BLE001
            m = {"error": str(e)[:120]}
        meas[sid] = m
        done += 1
        if done % 25 == 0:
            meas_path.write_text(json.dumps(meas, indent=1), encoding="utf-8")
            print(done, "measured", flush=True)
    meas_path.write_text(json.dumps(meas, indent=1), encoding="utf-8")
    print(len(meas), "clips measured ->", meas_path)


if __name__ == "__main__":
    main()
