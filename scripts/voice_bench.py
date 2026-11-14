"""Measure how well and how fast Red hears: word errors and time per transcription.

    python scripts/voice_bench.py render             make the test clips (Kokoro voices; kept in RED_HOME\\cache\\voice-bench)
    python scripts/voice_bench.py run [options]      transcribe them and print the numbers

The sentences are in tests/fixtures/voice/sentences.json: "said" is what is spoken (with ums and
self-corrections), "meant" what the user wants Red to understand. The wake corpus clips ("Hey Red,
open YouTube", the user's own voice, never in git) are measured too when they exist.

Options for run:
    --model base.en|small|tiny.en   --beam 1|5   --threads N   --window on|off   --prompt none|names
    --clean on|off                  --noisy      --corpus off

Prints word error rates against `said` (what the transcript should say word for word) and against
`meant` (after the clean-up of fillers and self-corrections, red/transcript.py), and the median time.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SENTENCES = ROOT / "tests" / "fixtures" / "voice" / "sentences.json"
VOICES = ("am_michael", "af_bella", "bm_george", "bf_emma", "am_adam", "af_nicole", "am_puck", "af_sarah")
NAMES = "Aryan, Red, Remy, Asha, Bruno, Winston, Spotify, Chrome, Edge, Notepad, Visual Studio Code, YouTube"


def home() -> Path:
    return Path(os.environ.get("RED_HOME", r"D:\RED"))


def bench_dir() -> Path:
    return home() / "cache" / "voice-bench"


_NUMBERS = ("zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen "
            "sixteen seventeen eighteen nineteen twenty").split()


def words(text: str) -> list[str]:
    """Lowercase words; "10" and "ten" count as the same word (Whisper writes digits)."""
    out = re.sub(r"[^a-z0-9' ]", " ", text.lower().replace("-", " ")).split()
    return [_NUMBERS[int(w)] if w.isdigit() and int(w) < len(_NUMBERS) else w for w in out]


def word_errors(reference: str, heard: str) -> tuple[int, int]:
    """(edits, reference words) between two texts, word by word."""
    ref, hyp = words(reference), words(heard)
    prev = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        cur = [i]
        for j, h in enumerate(hyp, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (r != h)))
        prev = cur
    return prev[-1], len(ref)


def render() -> None:
    from red.audio import resample, to_int16
    from red.tts_kokoro import KOKORO_FILES, KokoroEngine, MODEL_FILE, VOICES_FILE
    from red.wake_corpus import write_wav

    folder = home() / "models" / "kokoro"
    engine = KokoroEngine(folder / MODEL_FILE, folder / VOICES_FILE)
    out = bench_dir()
    out.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(7)
    items = json.loads(SENTENCES.read_text(encoding="utf-8"))
    for i, item in enumerate(items):
        voice = VOICES[i % len(VOICES)]
        speed = (0.95, 1.0, 1.08)[i % 3]
        audio = resample(engine.create(item["said"], voice, speed), 24_000, 16_000)
        lead = np.zeros(int(0.45 * 16_000), np.float32)
        clip = np.concatenate([lead, audio, lead])
        write_wav(out / f"{i:02d}.wav", clip)
        # The same clip with room noise at about 20 dB under the speech.
        level = float(np.sqrt(np.mean(audio ** 2))) / 10.0
        noisy = clip + rng.normal(0, level, clip.size).astype(np.float32)
        write_wav(out / f"{i:02d}-noisy.wav", noisy)
        print(f"{i:02d} {voice:11s} {item['said']}")
    (out / "items.json").write_text(json.dumps(items, indent=1), encoding="utf-8")


def run(args) -> None:
    from red.stt import Transcriber
    from red.wake_corpus import read_wav

    clean = None
    if args.clean == "on":
        from red.transcript import clean_transcript as clean

    if args.min_window:
        import red.stt as stt
        stt.MIN_WINDOW_SECONDS = args.min_window
    t = Transcriber(home() / "models" / "whisper", args.model, "cpu", beam_size=args.beam,
                    hotwords=NAMES if args.prompt == "names" else None, fit_window=args.window == "on",
                    cpu_threads=args.threads)
    t.load()
    items = json.loads((bench_dir() / "items.json").read_text(encoding="utf-8"))
    suffix = "-noisy" if args.noisy else ""
    times: list[float] = []
    said_err = said_n = meant_err = meant_n = 0
    shown = 0
    for i, item in enumerate(items):
        audio = read_wav(bench_dir() / f"{i:02d}{suffix}.wav")
        t.transcribe(audio) if i == 0 else None            # warm up
        t0 = time.perf_counter()
        text = t.transcribe(audio)
        times.append(time.perf_counter() - t0)
        e, n = word_errors(item["said"], text)
        said_err, said_n = said_err + e, said_n + n
        final = clean(text) if clean else text
        e2, n2 = word_errors(item["meant"], final)
        meant_err, meant_n = meant_err + e2, meant_n + n2
        if args.verbose and (e or e2) and shown < 60:
            shown += 1
            print(f"  said : {item['said']}\n  heard: {text}\n  clean: {final}")
    line = (f"{args.model} beam={args.beam} threads={args.threads} window={args.window} prompt={args.prompt} "
            f"clean={args.clean}{' noisy' if args.noisy else ''}: "
            f"{len(items)} clips, median {statistics.median(times) * 1000:.0f} ms, "
            f"WER vs said {said_err / said_n * 100:.1f}% ({said_err}/{said_n}), "
            f"WER vs meant {meant_err / meant_n * 100:.1f}% ({meant_err}/{meant_n})")
    print(line)
    corpus = home() / "cache" / "wake-corpus"
    if args.corpus == "on" and corpus.exists():
        files = sorted(corpus.glob("hey-red-cmd-*.wav"))
        err = n = 0
        ts: list[float] = []
        for f in files:
            audio = read_wav(f)
            t0 = time.perf_counter()
            text = t.transcribe(audio)
            ts.append(time.perf_counter() - t0)
            e, k = word_errors("Hey Red, open YouTube.", text)
            err, n = err + e, n + k
            if args.verbose:
                print(f"  corpus: {text}")
        if files:
            print(f"  wake corpus 'Hey Red, open YouTube' x{len(files)}: median {statistics.median(ts) * 1000:.0f} ms, "
                  f"WER {err / n * 100:.1f}% ({err}/{n})")


class RealtimeMic:
    """Plays a clip into record_command at the speed of speech, then quiet room noise."""

    def __init__(self, clip: np.ndarray, tail_seconds: float = 4.0):
        self.audio = np.concatenate([clip, np.random.default_rng(3).normal(0, 0.002, int(tail_seconds * 16_000))
                                     .astype(np.float32)])
        self.pos = 0

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return None

    def read(self, timeout: float = 2.0) -> np.ndarray:
        time.sleep(0.03)
        block = self.audio[self.pos:self.pos + 480]
        self.pos += 480
        return block


def endpoint(args) -> None:
    """How long after you stop talking is the text ready, and how long is the pause? Real Whisper, real time."""
    from red.audio import record_command
    from red.smalltalk import sounds_finished
    from red.stt import Transcriber
    from red.wake_corpus import read_wav

    t = Transcriber(home() / "models" / "whisper", args.model, "cpu", beam_size=args.beam,
                    fit_window=args.window == "on", cpu_threads=args.threads)
    t.load()
    t.transcribe(read_wav(bench_dir() / "00.wav"))
    quick, spec = (0.8, 0.0) if args.old else (args.quick, args.speculate)
    items = json.loads((bench_dir() / "items.json").read_text(encoding="utf-8"))
    pauses, readies, wrong = [], [], 0
    for i, item in enumerate(items[:args.count]):
        clip = read_wav(bench_dir() / f"{i:02d}-noisy.wav")[: -int(0.45 * 16_000)]      # no trailing silence
        heard: dict = {}
        stats: dict = {}

        def check(audio):
            start = time.perf_counter()
            text = t.transcribe(audio)
            heard.update(text=text, seconds=time.perf_counter() - start, size=audio.size)
            return sounds_finished(text) and (True if len(text.split()) >= 3 else 0.8)

        out = record_command(max_seconds=20, silence_seconds=1.5, quick_silence=quick, speculate_after=spec,
                             is_complete=check, mic=RealtimeMic(clip), stats=stats)
        quiet = stats["quiet"]
        # Old way: the check starts after the pause and Whisper's time is waited on top.
        pause = quiet + (0.0 if spec else heard.get("seconds", 0.0))
        ready = stats.get("ready", pause)
        pauses.append(pause)
        readies.append(ready)
        full = word_errors(item["said"], heard.get("text", ""))[0] if heard.get("size") == out.size else -1
        print(f"  {i:02d} pause {pause:.2f} s, text ready {ready:.2f} s  {heard.get('text', '')!r}")
    print(f"{'old way' if args.old else 'new way'} (quick {quick}, speculate {spec}): median pause {statistics.median(pauses):.2f} s, "
          f"median text ready {statistics.median(readies):.2f} s, max ready {max(readies):.2f} s")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("action", choices=("render", "run", "endpoint"))
    p.add_argument("--old", action="store_true")
    p.add_argument("--quick", type=float, default=0.5)
    p.add_argument("--speculate", type=float, default=0.15)
    p.add_argument("--count", type=int, default=16)
    p.add_argument("--model", default="base.en")
    p.add_argument("--beam", type=int, default=5)
    p.add_argument("--threads", type=int, default=0)
    p.add_argument("--window", choices=("on", "off"), default="on")
    p.add_argument("--prompt", choices=("none", "names"), default="none")
    p.add_argument("--clean", choices=("on", "off"), default="off")
    p.add_argument("--min-window", type=float, default=None)
    p.add_argument("--noisy", action="store_true")
    p.add_argument("--corpus", choices=("on", "off"), default="on")
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()
    {"render": lambda: render(), "run": lambda: run(args), "endpoint": lambda: endpoint(args)}[args.action]()


if __name__ == "__main__":
    main()
