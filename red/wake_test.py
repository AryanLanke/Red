"""python -m red wake-test: see what Red's wake word hears from your microphone.

Runs the real "Hey Red" detector for 30 seconds and prints each check as it
happens: the words Whisper heard, the score, how loud you were, and whether
that would wake Red. Say "Hey Red", then "Hey Red, open YouTube", then
something else. If the loudness is under 0.05, the microphone is too quiet:
raise its level in Windows Settings > System > Sound > Input.

A hidden Red is paused while this runs (they can't both use the microphone)
and started again afterwards.
"""

from __future__ import annotations

import logging
import time
from typing import Callable

SECONDS = 30.0
QUIET_PEAK = 0.05


class _Show(logging.Handler):
    """Prints the detector's 'Wake check' log lines, with a verdict."""

    def __init__(self, threshold: float, out: Callable[[str], None]):
        super().__init__()
        self.threshold, self.out = threshold, out
        self.checks = 0
        self.woke = 0
        self.quiet = 0

    def emit(self, record: logging.LogRecord) -> None:
        text = record.getMessage()
        if text.startswith("Wake skip: "):
            self.out(f"  skipped: {text[len('Wake skip: '):]}")
            return
        if not text.startswith("Wake check:"):
            return
        import re
        m = re.search(r"score ([0-9.]+).*peak ([0-9.]+)", text)
        score, peak = (float(m.group(1)), float(m.group(2))) if m else (0.0, 0.0)
        self.checks += 1
        verdict = "WAKES RED" if score >= self.threshold else "ignored"
        if score >= self.threshold:
            self.woke += 1
        if peak < QUIET_PEAK:
            self.quiet += 1
        self.out(f"  {text[len('Wake check: '):]}  ->  {verdict}")


def run(settings, *, seconds: float = SECONDS, out: Callable[[str], None] = print,
        make_detector: Callable | None = None, microphone: Callable | None = None,
        clock: Callable[[], float] = time.monotonic) -> int:
    """Listen for `seconds` and print every wake check. Returns 0."""
    from .audio import Microphone, to_int16
    from .wakeword import HeyRedDetector

    detector = (make_detector or HeyRedDetector.create)(settings.models_dir / "wakeword")
    show = _Show(settings.wakeword_threshold, out)
    logging.getLogger("red.wakeword").addHandler(show)
    logging.getLogger("red.wakeword").setLevel(logging.INFO)
    out(f"Say \"Hey Red\", \"Hey Red, open YouTube\", then something else. Listening for {seconds:.0f} s...")
    end = clock() + seconds
    try:
        with (microphone or (lambda: Microphone(block_seconds=0.08)))() as mic:
            while clock() < end:
                detector.score(to_int16(mic.read()))
    finally:
        logging.getLogger("red.wakeword").removeHandler(show)
    out(f"\nDone. {show.checks} phrases checked, {show.woke} would wake Red.")
    if show.checks == 0:
        out("Nothing was checked. Either nobody spoke, or the microphone is very quiet or the wrong one "
            "(Windows Settings > System > Sound > Input; RED_MIC_DEVICE in .env).")
    elif show.quiet:
        out(f"{show.quiet} of them were quiet (peak under {QUIET_PEAK}): raise the microphone's level "
            "in Windows Settings > System > Sound > Input.")
    return 0


def main(settings, mode: str = "live") -> int:
    """Pauses the hidden Red while using the microphone. mode: live, record or replay."""
    from . import background

    if mode == "replay":                 # no microphone: the hidden Red can keep running
        from .wake_corpus import replay
        return 0 if replay(settings) is not None else 1
    if mode == "learn":
        from .wake_corpus import learn
        return 0 if learn(settings) is not None else 1
    was_running = background.stop(settings.home)
    if was_running:
        print("Paused the Red running in the background while we listen.")
    try:
        if mode == "record":
            from .wake_corpus import record
            record(settings)
            return 0
        return run(settings)
    finally:
        if was_running:
            background.start(settings.home)
            print("Red is running in the background again.")
