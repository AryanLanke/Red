"""Score every 'Wake check' transcript in red.log again with today's match rules (no audio, no model).

    python scripts/wake_text_check.py [--since 2026-11-08]

Prints the texts whose verdict changes: newly woken (possible false wakes, or recovered misses) and
newly asleep. Corpus replays (minutes with more than 40 wake lines) are left out.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("RED_HOME", r"D:\RED")

from red import wakeword  # noqa: E402

LINE = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d):\d\d,\d+ red\.wakeword INFO Wake check: heard (['\"])(.*?)\2 "
                  r"\(score ([\d.]+)(?:, ([^,)]+))?")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="2026-11-08")
    ap.add_argument("--log", default=r"D:\RED\logs\red.log")
    args = ap.parse_args()
    wakeword.add_names(wakeword.companion_names(Path(os.environ["RED_HOME"])))
    rows = []
    for raw in Path(args.log).read_text(encoding="utf-8", errors="replace").splitlines():
        m = LINE.match(raw)
        if m and m.group(1) >= args.since:
            rows.append((m.group(1), m.group(3), float(m.group(4)), (m.group(5) or "").strip()))
    per_minute = Counter(r[0] for r in rows)
    rows = [r for r in rows if per_minute[r[0]] <= 40]
    profile = wakeword.load_profile(Path(os.environ["RED_HOME"]) / "models" / "wakeword")
    personal = frozenset(profile.get("phrases", []))
    woke, slept = [], []
    for minute, text, old, mode in rows:
        new = wakeword.match_score(text, personal, head=mode.startswith("start"))
        if old < 0.5 <= new:
            woke.append((minute, text, new))
        elif new < 0.5 <= old:
            slept.append((minute, text, old))
    print(f"{len(rows)} wake checks since {args.since} (replays left out)")
    print(f"newly woken: {len(woke)}")
    for w in woke:
        print("   ", w)
    print(f"newly asleep: {len(slept)}")
    for s in slept:
        print("   ", s)


if __name__ == "__main__":
    main()
