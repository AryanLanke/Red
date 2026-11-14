"""scripts/run_tracks.py: which items are open, and when a track stops. No Claude, no git."""

import importlib.util
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("run_tracks", ROOT / "scripts" / "run_tracks.py")
rt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rt)

PLAN = """# plan
## How a session works
- [ ] not an item

## Flaws I noticed
- [x] (A) fixed already
- [ ] (A) voices
- [ ] (A/B) both tracks
  - [ ] (B) motion leftover
- [ ] untagged flaw

## Track A: brains and voice
- [ ] **A1. Land the leftovers.**
- [x] **A0. done**

## Track B: body
- [ ] **B1. Land the leftovers.**
"""


def test_open_items_per_track():
    assert rt.open_items(PLAN, "A") == ["(A) voices", "(A/B) both tracks", "**A1. Land the leftovers.**"]
    assert rt.open_items(PLAN, "B") == ["(A/B) both tracks", "(B) motion leftover",
                                        "**B1. Land the leftovers.**"]


def test_the_real_plan_parses():
    text = (ROOT / "plan.md").read_text(encoding="utf-8")
    for track in "AB":
        for item in rt.open_items(text, track):
            assert item.startswith(f"**{track}") or re.match(r"\([AB/]+\)", item), item


def test_newest_extension_copy_is_used(tmp_path):
    for v in ("2.1.9", "2.1.325", "2.1.40"):
        exe = tmp_path / ".vscode" / "extensions" / f"anthropic.claude-code-{v}-win32-x64" / \
            "resources" / "native-binary" / "claude.exe"
        exe.parent.mkdir(parents=True)
        exe.write_text("")
    found = rt.find_claude(env={"PATH": ""}, home=tmp_path)
    if rt.shutil.which("claude") is None:
        assert "2.1.325" in found
    assert rt.find_claude(env={"RED_CLAUDE": r"X:\claude.exe"}) == r"X:\claude.exe"


def test_session_command_is_the_pasted_sentence():
    cmd = rt.session_command("claude.exe", "B")
    assert cmd[:3] == ["claude.exe", "-p", "You are track B. Read D:\\RED\\red\\plan.md and do the next part."]
    assert cmd[cmd.index("--model") + 1] == "claude-sonnet-5-5"
    assert cmd[cmd.index("--effort") + 1] == "medium"
    assert cmd[cmd.index("--permission-mode") + 1] == "auto"


class FakeProc:
    def __init__(self, code):
        self.code, self.killed = code, False

    def wait(self, timeout=None):
        if self.code == "hang":
            raise subprocess.TimeoutExpired("claude", timeout)
        return self.code

    def kill(self):
        self.killed = True


def make_runner(tmp_path, plans, codes, results=None, rounds=3, tracks=("A", "B")):
    plans, started = list(plans), []

    def read_plan():
        return plans.pop(0) if len(plans) > 1 else plans[0]

    def start(track, stem):
        started.append(track)
        stem.with_suffix(".json").write_text(json.dumps(
            {"result": (results or {}).get(track, f"{track} did a part"), "num_turns": 12,
             "total_cost_usd": 1.5}), encoding="utf-8")
        return FakeProc(codes[track].pop(0) if isinstance(codes[track], list) else codes[track])

    runner = rt.Runner(list(tracks), rounds, tmp_path / "out", read_plan=read_plan, start=start,
                       stop_file=tmp_path / "STOP", say=lambda s: None)
    return runner, started


def ticked(plan, line):
    return plan.replace(f"- [ ] {line}", f"- [x] {line}")


def test_a_track_keeps_going_while_it_ticks_things(tmp_path):
    p1 = PLAN
    p2 = ticked(p1, "(A) voices")
    p3 = ticked(p2, "(A/B) both tracks")
    runner, started = make_runner(tmp_path, [p1, p2, p2, p3, p3], {"A": 0}, rounds=2, tracks=("A",))
    why = runner.run()
    assert started == ["A", "A"] and why == ["ran 2 rounds"]
    summary = (tmp_path / "out" / "summary.md").read_text(encoding="utf-8")
    assert "A did a part" in summary and "12 turns, $1.50" in summary


def test_a_session_that_ticks_nothing_stops_its_track(tmp_path):
    runner, started = make_runner(tmp_path, [PLAN], {"A": 0}, tracks=("A",))
    assert runner.run() == ["track A: the session ticked nothing; read its summary"]
    assert started == ["A"]


def test_a_failed_session_stops_only_its_track(tmp_path):
    p2 = ticked(PLAN, "(A) voices")
    runner, started = make_runner(tmp_path, [PLAN, p2, p2, ticked(p2, "**A1. Land the leftovers.**")],
                                  {"A": 0, "B": 1}, rounds=2)
    why = runner.run()
    assert started == ["A", "B", "A"]
    assert "track B: the session failed (exit 1)" in why


def test_a_session_past_its_time_is_ended(tmp_path):
    runner, _ = make_runner(tmp_path, [PLAN], {"A": "hang"}, tracks=("A",))
    assert runner.run() == ["track A: the session failed (exit timeout)"]


def test_nothing_left_means_no_session(tmp_path):
    done = PLAN.replace("- [ ]", "- [x]")
    runner, started = make_runner(tmp_path, [done], {"A": 0, "B": 0})
    assert runner.run() == ["track A: nothing left to do", "track B: nothing left to do"]
    assert started == []


def test_the_stop_file_stops_before_a_round(tmp_path):
    (tmp_path / "STOP").write_text("")
    runner, started = make_runner(tmp_path, [PLAN], {"A": 0})
    assert runner.run() == [f"stopped by {tmp_path / 'STOP'}"] and started == []
