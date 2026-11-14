"""Run plan.md's track sessions back to back, so nobody has to paste the prompt.

    python scripts\\run_tracks.py                   # tracks A and B side by side, 3 rounds at most
    python scripts\\run_tracks.py --tracks A --rounds 5
    python scripts\\run_tracks.py --dry-run         # show what would run, start nothing

Each round starts one headless Claude Code session per track (Sonnet 5.5, medium
effort, auto permission mode, in D:\\RED) with the same sentence the user used to
paste: "You are track A. Read D:\\RED\\red\\plan.md and do the next part." When
they finish it reads plan.md on origin/main again. A track stops when it has no
open item left, when its session failed, or when the session ticked nothing (it is
stuck or needs the user: read its summary). Everything goes to
RED_HOME\\cache\\tracks\\<date>\\: one JSON file per session and summary.md with each
session's closing lines. Create RED_HOME\\cache\\tracks\\STOP to stop after the
sessions that are running now.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Callable

PROMPT = "You are track {track}. Read D:\\RED\\red\\plan.md and do the next part."
MODEL = "claude-sonnet-5-5"
EFFORT = "medium"
SESSION_TIMEOUT_MINUTES = 150


def open_items(plan_text: str, track: str) -> list[str]:
    """The unchecked lines that belong to `track`: its flaws (tagged "(A)", "(A/B)") and its parts."""
    items, section = [], ""
    for line in plan_text.splitlines():
        if line.startswith("## "):
            section = line[3:].strip()
            continue
        m = re.match(r"\s*- \[ \] (.*)", line)
        if not m:
            continue
        text = m.group(1).strip()
        if section.startswith("Flaws"):
            tag = re.match(r"\(([AB/ ]+)\)", text)
            if tag and track in tag.group(1).replace(" ", "").split("/"):
                items.append(text)
        elif section.startswith(f"Track {track}"):
            items.append(text)
    return items


def _version(path: Path) -> tuple[int, ...]:
    m = re.search(r"claude-code-(\d+(?:\.\d+)*)", str(path))
    return tuple(int(x) for x in m.group(1).split(".")) if m else ()


def find_claude(env: dict[str, str] | None = None, home: Path | None = None) -> str | None:
    """RED_CLAUDE, `claude` on PATH, or the newest copy the VS Code extension ships."""
    env = os.environ if env is None else env
    if env.get("RED_CLAUDE"):
        return env["RED_CLAUDE"]
    on_path = shutil.which("claude")
    if on_path:
        return on_path
    home = home or Path.home()
    found = sorted((home / ".vscode" / "extensions").glob(
        "anthropic.claude-code-*/resources/native-binary/claude.exe"), key=_version)
    return str(found[-1]) if found else None


def session_command(claude: str, track: str) -> list[str]:
    return [claude, "-p", PROMPT.format(track=track), "--model", MODEL, "--effort", EFFORT,
            "--permission-mode", "auto", "--output-format", "json"]


def read_result(path: Path) -> tuple[str, str]:
    """(closing text, one-line facts) from a session's --output-format json file."""
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError):
        return "(no result: see the .err file)", ""
    facts = []
    if data.get("num_turns") is not None:
        facts.append(f"{data['num_turns']} turns")
    if data.get("total_cost_usd") is not None:
        facts.append(f"${data['total_cost_usd']:.2f}")
    if data.get("is_error"):
        facts.append("error")
    return str(data.get("result") or "").strip(), ", ".join(facts)


class Runner:
    """The round loop. Everything outside (git, Claude, the clock) is injected, for tests."""

    def __init__(self, tracks: list[str], rounds: int, out_dir: Path, *,
                 read_plan: Callable[[], str],
                 start: Callable[[str, Path], subprocess.Popen],
                 stop_file: Path, timeout_s: float = SESSION_TIMEOUT_MINUTES * 60,
                 say: Callable[[str], None] = print):
        self.tracks, self.rounds, self.out_dir = list(tracks), rounds, out_dir
        self.read_plan, self.start, self.stop_file = read_plan, start, stop_file
        self.timeout_s, self.say = timeout_s, say
        self.summary = out_dir / "summary.md"

    def _note(self, text: str) -> None:
        self.say(text)
        with self.summary.open("a", encoding="utf-8") as f:
            f.write(text + "\n")

    def run(self) -> list[str]:
        """Returns why each track stopped."""
        self.out_dir.mkdir(parents=True, exist_ok=True)
        active, why = list(self.tracks), []
        for n in range(1, self.rounds + 1):
            if self.stop_file.exists():
                why.append(f"stopped by {self.stop_file}")
                break
            plan = self.read_plan()
            for t in list(active):
                if not open_items(plan, t):
                    active.remove(t)
                    why.append(f"track {t}: nothing left to do")
            if not active:
                break
            before = {t: open_items(plan, t) for t in active}
            stamp = datetime.now().strftime("%H%M")
            self._note(f"\n# Round {n}, {datetime.now():%Y-%m-%d %H:%M}: tracks {', '.join(active)}")
            running = {}
            for t in active:
                self._note(f"- track {t} starts on: {before[t][0][:120]}")
                running[t] = (self.start(t, self.out_dir / f"{stamp}-{t}"), time.monotonic())
            codes = {}
            for t, (proc, began) in running.items():
                try:
                    codes[t] = proc.wait(timeout=max(1.0, self.timeout_s - (time.monotonic() - began)))
                except subprocess.TimeoutExpired:
                    proc.kill()
                    codes[t] = "timeout"
            plan = self.read_plan()
            for t in list(active):
                text, facts = read_result(self.out_dir / f"{stamp}-{t}.json")
                self._note(f"\n## Track {t} (exit {codes[t]}{', ' + facts if facts else ''})\n\n{text}\n")
                if codes[t] != 0:
                    active.remove(t)
                    why.append(f"track {t}: the session failed (exit {codes[t]})")
                elif open_items(plan, t) == before[t]:
                    active.remove(t)
                    why.append(f"track {t}: the session ticked nothing; read its summary")
            if not active:
                break
        else:
            why.append(f"ran {self.rounds} rounds")
        self._note("\nStopped: " + "; ".join(why))
        return why


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--tracks", default="A,B", help="A, B or A,B (default)")
    ap.add_argument("--rounds", type=int, default=3, help="sessions per track at most (default 3)")
    ap.add_argument("--dry-run", action="store_true", help="show the plan's next items and the command")
    args = ap.parse_args(argv)

    home = Path(os.environ.get("RED_HOME", r"D:\RED"))
    repo = home / "red"
    tracks = [t.strip().upper() for t in args.tracks.split(",") if t.strip()]
    claude = find_claude()
    if not claude:
        print("error: no claude.exe found. Set RED_CLAUDE to its path.", file=sys.stderr)
        return 2

    def read_plan() -> str:
        subprocess.run(["git", "-C", str(repo), "fetch", "-q"], check=False)
        out = subprocess.run(["git", "-C", str(repo), "show", "origin/main:plan.md"],
                             capture_output=True, text=True, encoding="utf-8")
        return out.stdout

    if args.dry_run:
        plan = read_plan()
        for t in tracks:
            items = open_items(plan, t)
            print(f"track {t}: {len(items)} open; next: {items[0][:120] if items else '(none)'}")
        print("command:", " ".join(session_command(claude, "A")))
        return 0

    tracks_dir = home / "cache" / "tracks"
    stop_file = tracks_dir / "STOP"
    if stop_file.exists():
        stop_file.unlink()
        print(f"Removed an old {stop_file}.")
    env = {**os.environ, "RED_HOME": str(home)}

    def start(track: str, stem: Path) -> subprocess.Popen:
        with open(stem.with_suffix(".json"), "wb") as out, open(stem.with_suffix(".err"), "wb") as err:
            return subprocess.Popen(session_command(claude, track), cwd=str(home), env=env,
                                    stdout=out, stderr=err, stdin=subprocess.DEVNULL)

    out_dir = tracks_dir / datetime.now().strftime("%Y-%m-%d")
    print(f"Running tracks {', '.join(tracks)}; summary in {out_dir / 'summary.md'}. "
          f"To stop after the current sessions, create {stop_file}.")
    Runner(tracks, args.rounds, out_dir, read_plan=read_plan, start=start, stop_file=stop_file).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
