"""Replay the wake corpus with different wake-stage settings (night 2, conversation lane).

    python scripts/wake_sweep.py                  baseline, with what was heard in each missed take
    python scripts/wake_sweep.py --sweep          a grid over SPEECH_ON, MIN_CLIP_SECONDS and gain

Never uses the microphone: RED_HOME\\cache\\wake-corpus only. The recordings stay out of git.
"""

from __future__ import annotations

import argparse
import itertools
import logging
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("RED_HOME", r"D:\RED")

from red import wakeword                       # noqa: E402
from red.config import load_settings           # noqa: E402
from red.wake_corpus import corpus_dir, read_wav, replay_file   # noqa: E402


class Lines(logging.Handler):
    def __init__(self):
        super().__init__()
        self.lines = []

    def emit(self, record):
        self.lines.append(record.getMessage())


def run(detector, files, threshold=0.5, show=False):
    handler = Lines()
    lg = logging.getLogger("red.wakeword")
    lg.addHandler(handler)
    lg.setLevel(logging.INFO)
    hits = {"hey-red": [0, 0], "hey-red-cmd": [0, 0]}
    false = 0
    talk_lines = []
    try:
        for path, audio in files:
            handler.lines = []
            wakes = replay_file(detector, audio, threshold)
            name = path.stem
            if name == "talk":
                false = wakes
                talk_lines = [l for l in handler.lines if "score 0.00" not in l and "Wake check" in l]
                continue
            key = name.rsplit("-", 1)[0]
            hits[key][1] += 1
            hits[key][0] += wakes > 0
            if show and not wakes:
                print(f"  missed {name}: " + " | ".join(handler.lines))
    finally:
        lg.removeHandler(handler)
    if show and talk_lines:
        print("  talk matches:", talk_lines)
    return hits, false


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sweep", action="store_true")
    ap.add_argument("--show", action="store_true")
    args = ap.parse_args()
    settings = load_settings()
    paths = sorted(corpus_dir(settings).glob("*.wav"))
    files = [(p, read_wav(p)) for p in paths]
    t0 = time.perf_counter()
    detector = wakeword.HeyRedDetector.create(settings.models_dir / "wakeword")
    print(f"detector loaded in {time.perf_counter() - t0:.1f} s; personal={sorted(detector.personal)}")
    if not args.sweep:
        t0 = time.perf_counter()
        hits, false = run(detector, files, show=True)
        print(hits, "false", false, f"({time.perf_counter() - t0:.0f} s, {detector.evaluations} checks)")
        return
    grid = itertools.product((0.35, 0.3, 0.25), (0.35, 0.25), (0.3, 0.5))
    for on, min_clip, peak in grid:
        wakeword.SPEECH_ON, wakeword.MIN_CLIP_SECONDS, wakeword.TARGET_PEAK = on, min_clip, peak
        wakeword.SPEECH_OFF = min(0.25, on - 0.05)
        wakeword.SOFT_SPEECH = min(0.2, on - 0.1)
        hits, false = run(detector, files, show=args.show)
        print(f"on={on} min={min_clip} peak={peak}: {hits} false {false}", flush=True)


if __name__ == "__main__":
    main()
