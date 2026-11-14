"""Count missed wakes, lost follow-ups and unintended wakes in red.log (night 2, conversation lane).

    python scripts/conv_stats.py [--since 2026-11-13] [--log PATH] [--show]

Definitions (all from the 'Wake check', 'Wake skip' and 'Timing' lines):
- wake: a Wake check with score >= 0.5.
- missed attempt: a Wake skip (too faint / too short) or a short Wake check that scored below 0.5, in the
  12 s before a wake, with no command being handled in between. The user repeated "Hey Red".
  (--since 2026-11-13; replays of the wake corpus, which log the same lines, are dropped.)
- missed wake (percent): missed attempts / (missed attempts + wakes).
- lost follow-up: after a Timing line (Red finished a reply), the user spoke within the next 20 s but not
  inside the follow-up window: a wake came 7-20 s after it, or speech the wake stage heard and dropped.
- unintended wake: a wake that no command followed (no Timing line within 90 s).
"""

from __future__ import annotations

import argparse
import re
from datetime import datetime
from pathlib import Path

LINE = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d),\d+ (\S+) (\w+) (.*)$")
CHECK = re.compile(r"Wake check: heard (.*?) \(score ([\d.]+)(?:, ([^,]+), peak ([\d.]+))?\)")
HEYISH = re.compile(r"\b(?:hey|hay|hi|a|eh|ay)\b[ ,.!-]*(?:red|rad|read|rid|redd|bread|bed|head|ready)\b", re.I)


def parse(path: Path, since: str):
    events = []
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = LINE.match(raw)
        if not m or m.group(1) < since:
            continue
        t = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S").timestamp()
        body = m.group(4)
        if body.startswith("Wake check"):
            c = CHECK.match(body)
            if c:
                events.append(("check", t, c.group(1).strip("'\""), float(c.group(2)), c.group(3) or ""))
        elif body.startswith("Wake skip"):
            events.append(("skip", t, body[len("Wake skip: "):], 0.0, ""))
        elif body.startswith("Timing"):
            events.append(("timing", t, body[:60], 0.0, ""))
        elif body.startswith("Startup: listening"):
            events.append(("start", t, body, 0.0, ""))
    return drop_replays(events)


def drop_replays(events, per_minute: int = 40):
    """`wake-test --replay` runs the detector over recordings in seconds and logs the same lines: a
    minute with more than `per_minute` wake lines is a replay, not the user talking."""
    from collections import Counter
    busy = Counter(int(e[1]) // 60 for e in events if e[0] in ("check", "skip"))
    return [e for e in events if busy.get(int(e[1]) // 60, 0) <= per_minute]


def analyse(events, threshold: float = 0.5, show: bool = False) -> dict:
    wakes = [e for e in events if e[0] == "check" and e[3] >= threshold]
    timings = [e for e in events if e[0] == "timing"]
    missed_attempts = 0
    missed_groups = 0
    lines = []
    for w in wakes:
        prior = [e for e in events if w[1] - 12 <= e[1] < w[1] and e is not w]
        # a command in between means the wake stage was paused, so those lines are not attempts
        last_timing = max((e[1] for e in prior if e[0] == "timing"), default=0)
        attempts = [e for e in prior if e[1] > last_timing and (
            e[0] == "skip" and ("faint" in e[2] or "too short" in e[2]) or
            e[0] == "check" and e[3] < threshold and (HEYISH.search(e[2]) or len(e[2].split()) <= 2))]
        if attempts:
            missed_attempts += len(attempts)
            missed_groups += 1
            lines.append(f"{datetime.fromtimestamp(w[1]):%m-%d %H:%M:%S} woke after {len(attempts)} missed: "
                         + "; ".join(e[2][:40] for e in attempts))
    # explicit near-misses the user did not repeat: 'Hey rad', 'hey read' with a low score
    near = [e for e in events if e[0] == "check" and e[3] < threshold and HEYISH.search(e[2])]
    lost_rewake = lost_speech = 0
    for t in timings:
        window = [e for e in events if t[1] < e[1] <= t[1] + 20 and e[0] in ("check", "skip")]
        if any(e[0] == "check" and e[3] >= threshold and e[1] - t[1] >= 7 for e in window):
            lost_rewake += 1
            lines.append(f"{datetime.fromtimestamp(t[1]):%m-%d %H:%M:%S} re-woke within 20 s of a reply")
        elif any(e[0] == "check" and e[3] < threshold and e[1] - t[1] >= 1 and len(e[2].split()) >= 2
                 and not HEYISH.search(e[2]) for e in window):
            lost_speech += 1
    unintended = 0
    for w in wakes:
        if not any(w[1] <= t[1] <= w[1] + 90 for t in timings):     # Timing is logged after the reply
            unintended += 1
            lines.append(f"{datetime.fromtimestamp(w[1]):%m-%d %H:%M:%S} wake with no command after it: {w[2][:40]}")
    hours = 0.0
    if events:
        # active time: gaps over 10 minutes are the user being away
        ts = sorted(e[1] for e in events)
        hours = sum(min(b - a, 600) for a, b in zip(ts, ts[1:])) / 3600
    result = {
        "wakes": len(wakes), "missed_attempts": missed_attempts, "wakes_after_misses": missed_groups,
        "missed_percent": round(100 * missed_attempts / max(1, missed_attempts + len(wakes)), 1),
        "near_misses_low_score": len(near),
        "commands": len(timings), "lost_follow_up_rewake": lost_rewake, "lost_follow_up_speech_dropped": lost_speech,
        "unintended_wakes": unintended, "active_hours": round(hours, 2),
    }
    if show:
        print("\n".join(lines))
    return result


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="2026-11-13")
    ap.add_argument("--log", default=r"D:\RED\logs\red.log")
    ap.add_argument("--show", action="store_true")
    args = ap.parse_args()
    ev = parse(Path(args.log), args.since)
    result = analyse(ev, show=args.show)
    for k, v in result.items():
        print(f"{k}: {v}")
    if result["active_hours"]:
        print(f"unintended_wakes_per_hour: {result['unintended_wakes'] / result['active_hours']:.2f}")


if __name__ == "__main__":
    main()
