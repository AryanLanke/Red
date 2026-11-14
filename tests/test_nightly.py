"""red/nightly.py: the scheduled task, the steps, the report and the morning line. No real schtasks, git,
pytest or PowerShell runs: every command goes to a fake runner."""

from __future__ import annotations

import json
import os
import subprocess
import time
import xml.etree.ElementTree as ET
from datetime import date, datetime
from pathlib import Path

import pytest

from red import nightly

NS = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}


class FakeRunner:
    """Records every command. `outputs` maps a word in the command to (exit code, text written to stdout)."""

    def __init__(self, outputs=None, default=(0, "")):
        self.calls = []
        self.outputs = outputs or {}
        self.default = default

    def __call__(self, argv, **kw):
        self.calls.append((list(argv), kw))
        code, text = self.default
        joined = " ".join(map(str, argv))
        for key, value in self.outputs.items():
            if key in joined:
                code, text = value
                break
        if callable(text):
            text = text(argv, kw)
        out = kw.get("stdout")
        if hasattr(out, "write"):
            out.write(text)
            return subprocess.CompletedProcess(argv, code)
        return subprocess.CompletedProcess(argv, code, stdout=text, stderr="")

    def commands(self, word):
        return [a for a, _ in self.calls if any(word in str(x) for x in a)]


# --------------------------------------------------------------------------
# the task
# --------------------------------------------------------------------------

def test_task_xml_is_valid_and_only_runs_when_idle():
    xml = nightly.task_xml(r"D:\R&D\.venv\Scripts\pythonw.exe", Path(r"D:\R&D\red"), Path(r"D:\R&D"),
                           r"PC\aryan", start=date(2026, 11, 15))
    root = ET.fromstring(xml.encode("utf-16"))
    s = root.find("t:Settings", NS)
    assert s.find("t:RunOnlyIfIdle", NS).text == "true"
    assert s.find("t:WakeToRun", NS).text == "false"
    assert s.find("t:DisallowStartIfOnBatteries", NS).text == "true"
    assert s.find("t:IdleSettings/t:Duration", NS).text == "PT10M"
    assert s.find("t:IdleSettings/t:StopOnIdleEnd", NS).text == "false"
    assert s.find("t:ExecutionTimeLimit", NS).text == "PT12H"
    assert root.find("t:Triggers/t:CalendarTrigger/t:StartBoundary", NS).text == "2026-11-15T03:00:00"
    p = root.find("t:Principals/t:Principal", NS)
    assert p.find("t:RunLevel", NS).text == "LeastPrivilege"
    assert p.find("t:LogonType", NS).text == "InteractiveToken"
    ex = root.find("t:Actions/t:Exec", NS)
    assert ex.find("t:Command", NS).text == r"D:\R&D\.venv\Scripts\pythonw.exe"
    assert ex.find("t:Arguments", NS).text == r'-m red --home D:\R&D nightly run'
    assert ex.find("t:WorkingDirectory", NS).text == r"D:\R&D\red"


def test_task_on_writes_utf16_xml_and_calls_schtasks(tmp_path):
    runner = FakeRunner()
    task = nightly.NightlyTask(tmp_path, runner=runner, python=str(tmp_path / "python.exe"),
                               workdir=tmp_path, user=lambda: r"PC\me")
    msg = task.on()
    assert "03:00" in msg and "idle" in msg
    argv, kw = runner.calls[-1]
    assert argv[:4] == ["schtasks.exe", "/Create", "/TN", "Red nightly"]
    assert "/F" in argv
    xml_path = Path(argv[argv.index("/XML") + 1])
    assert xml_path.read_bytes()[:2] in (b"\xff\xfe", b"\xfe\xff")          # UTF-16 with a BOM
    assert "nightly run" in xml_path.read_text(encoding="utf-16")
    assert kw["timeout"] == 30


def test_task_off_and_status(tmp_path):
    runner = FakeRunner({"/Query": (1, "")})
    task = nightly.NightlyTask(tmp_path, runner=runner, python="python.exe")
    assert "wasn't on" in task.off()
    assert not runner.commands("/Delete")
    assert "off" in task.status()
    runner = FakeRunner()
    task = nightly.NightlyTask(tmp_path, runner=runner, python="python.exe")
    assert task.off() == "The nightly self-test is off."
    assert runner.commands("/Delete")[0][:4] == ["schtasks.exe", "/Delete", "/TN", "Red nightly"]


def test_task_error_is_reported(tmp_path, capsys):
    runner = FakeRunner({"/Create": (1, "ERROR: Access is denied.")})
    task = nightly.NightlyTask(tmp_path, runner=runner, python="python.exe", user=lambda: "me")
    assert nightly.main(["on"], tmp_path, task=task) == 1
    assert "Access is denied" in capsys.readouterr().err


def test_red_nightly_command_dispatches(monkeypatch, tmp_path):
    from red import __main__ as red_main
    seen = {}

    def fake_main(argv, home, task=None):
        seen["argv"], seen["home"] = argv, home
        return 0

    monkeypatch.setenv("RED_HOME", str(tmp_path))
    monkeypatch.setattr(nightly, "main", fake_main)
    assert red_main.main(["nightly", "run", "--only", "unit"]) == 0
    assert seen["argv"] == ["run", "--only", "unit"]
    assert Path(seen["home"]) == tmp_path


# --------------------------------------------------------------------------
# a run
# --------------------------------------------------------------------------

def _tree(tmp_path, replay=True, score=True):
    tree = tmp_path / "tree"
    for f in ["tests/test_x.py", "red/sim/__main__.py", "installer/build.ps1", "installer/sandbox_test.ps1"] + \
             (["tests/test_replay.py"] if replay else []) + (["red/score.py"] if score else []):
        (tree / f).parent.mkdir(parents=True, exist_ok=True)
        (tree / f).write_text("", encoding="utf-8")
    return tree


def _outputs(home, unit="2660 passed, 208 skipped in 312.4s", unit_code=0, score="6.2"):
    def sim(argv, kw):
        out = Path(argv[argv.index("--out") + 1]) / "2026-11-15-nightly"
        out.mkdir(parents=True, exist_ok=True)
        rows = [{"scenario": "good", "passed": True, "turns": [{"first_word": 0.8}]},
                {"scenario": "bad", "passed": False, "category": "chat", "companion": "red",
                 "turns": [{"meant": "write a code for me", "heard": "write a code for me", "reply": "",
                            "first_word": 2.0, "failures": ["dropped"]}]}]
        (out / "results.jsonl").write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
        return "1/2 conversations passed"

    def build(argv, kw):
        exe = home / "cache" / "installer" / "out" / "Red-Setup.exe"
        exe.parent.mkdir(parents=True, exist_ok=True)
        exe.write_bytes(b"x" * (3 * 2**20))
        return "Done"

    def install(argv, kw):
        res = Path(argv[argv.index("-Results") + 1])
        res.mkdir(parents=True, exist_ok=True)
        (res / "result.json").write_text(json.dumps({"mode": "staged", "checks": [
            {"name": "install", "ok": True}, {"name": "doctor", "ok": True}]}), encoding="utf-8-sig")
        return "staged: 2 of 2"

    return {"test_replay.py": (0, "12 passed in 1.0s"), " pytest tests ": (unit_code, unit),
            "red score": (0, f"Red Score: {score}/10"), "red.sim": (0, sim),
            "build.ps1": (0, build), "sandbox_test.ps1": (0, install)}


def _run(tmp_path, runner, idle=3600.0, day=15, **kw):
    home = tmp_path / "home"
    return nightly.run(home, here=True, runner=runner, python=str(tmp_path / "python.exe"),
                       idle=lambda: idle, today=lambda: datetime(2026, 11, day, 3, 0),
                       repo=kw.pop("repo", None) or _tree(tmp_path), **kw), home


def test_full_run_writes_report_and_numbers(tmp_path):
    home = tmp_path / "home"
    runner = FakeRunner(_outputs(home))
    r, home = _run(tmp_path, runner)
    steps = {s["name"]: s for s in r["steps"]}
    assert [s["name"] for s in r["steps"]] == [s.name for s in nightly.STEPS]
    assert all(s["status"] == "ok" for s in r["steps"]), r["steps"]
    assert steps["unit"]["numbers"] == {"passed": 2660, "skipped": 208}
    assert steps["score"]["numbers"] == {"score": 6.2}
    assert steps["sim"]["numbers"]["pass_rate"] == 0.5
    assert steps["installer-build"]["numbers"] == {"setup_mb": 3}
    assert steps["installer-test"]["numbers"]["mode"] == "staged"
    night = home / "cache" / "nightly" / "2026-11-15"
    report = (night / "report.md").read_text(encoding="utf-8")
    assert "all green" in report and "Red Score: 6.2/10" in report
    assert "first run" in report
    assert "write a code for me" in report                           # one of the worst replies
    assert json.loads((night / "results.json").read_text(encoding="utf-8"))["date"] == "2026-11-15"
    assert not (home / "cache" / "nightly" / "running.lock").exists()
    # every step ran from the tree, with RED_HOME and offscreen Qt, and no window
    for argv, kw in runner.calls:
        if "stdout" in kw:
            assert kw["cwd"] == str(tmp_path / "tree")
            assert kw["env"]["RED_HOME"] == str(home) and kw["env"]["QT_QPA_PLATFORM"] == "offscreen"
            assert "timeout" in kw


def test_user_at_the_pc_caps_the_simulator(tmp_path):
    runner = FakeRunner(_outputs(tmp_path / "home"))
    _run(tmp_path, runner, idle=5.0)
    sim = runner.commands("red.sim")[0]
    assert "--limit" in sim and "--big" not in sim


def test_steps_not_built_yet_are_skipped(tmp_path):
    runner = FakeRunner(_outputs(tmp_path / "home"))
    r, _ = _run(tmp_path, runner, repo=_tree(tmp_path, replay=False, score=False))
    steps = {s["name"]: s for s in r["steps"]}
    assert steps["replay"]["status"] == steps["score"]["status"] == "skipped"
    assert steps["replay"]["detail"] == "not built yet"
    assert not runner.commands("red score")


def test_installer_test_needs_the_build(tmp_path):
    out = _outputs(tmp_path / "home")
    out["build.ps1"] = (1, "Inno Setup failed")
    runner = FakeRunner(out)
    r, _ = _run(tmp_path, runner)
    steps = {s["name"]: s for s in r["steps"]}
    assert steps["installer-build"]["status"] == "fail"
    assert steps["installer-test"]["status"] == "skipped"
    assert not runner.commands("sandbox_test.ps1")


def test_only_runs_the_named_steps(tmp_path):
    runner = FakeRunner(_outputs(tmp_path / "home"))
    r, _ = _run(tmp_path, runner, only=["unit"])
    assert [s["name"] for s in r["steps"]] == ["unit"]


def test_a_timeout_fails_the_step_and_the_run_goes_on(tmp_path):
    class Slow(FakeRunner):
        def __call__(self, argv, **kw):
            if "tests" in argv and "pytest" in argv:
                raise subprocess.TimeoutExpired(argv, 1)
            return super().__call__(argv, **kw)
    runner = Slow(_outputs(tmp_path / "home"))
    r, _ = _run(tmp_path, runner)
    steps = {s["name"]: s for s in r["steps"]}
    assert steps["unit"]["status"] == "fail" and "timed out" in steps["unit"]["detail"]
    assert steps["sim"]["status"] == "ok"


def test_second_night_lists_what_got_worse_and_the_morning_line(tmp_path):
    home = tmp_path / "home"
    _run(tmp_path, FakeRunner(_outputs(home)), day=15)
    worse_out = _outputs(home, unit="3 failed, 2657 passed in 300s", unit_code=1, score="5.8")
    r, _ = _run(tmp_path, FakeRunner(worse_out), day=16)
    text = "\n".join(r["worse"])
    assert "unit passed last time and fails now" in text
    assert "3 tests fail (was 0)" in text
    assert "Red Score 5.8/10 (was 6.2)" in text
    report = (home / "cache" / "nightly" / "2026-11-16" / "report.md").read_text(encoding="utf-8")
    assert "## What got worse" in report and "**FAIL**" in report
    line = nightly.morning_line(home, now=datetime.now())
    assert line == "Last night's self-test: score 5.8/10; unit failed."


def test_morning_line_is_empty_when_old_or_missing(tmp_path):
    home = tmp_path / "home"
    assert nightly.morning_line(home) == ""
    _run(tmp_path, FakeRunner(_outputs(home)))
    res = home / "cache" / "nightly" / "2026-11-15" / "results.json"
    assert nightly.morning_line(home) == "Last night's self-test: score 6.2/10; all green."
    old = time.time() - 2 * 86400
    os.utime(res, (old, old))
    assert nightly.morning_line(home) == ""


def test_a_second_run_at_the_same_time_is_refused(tmp_path):
    home = tmp_path / "home"
    lock = home / "cache" / "nightly" / "running.lock"
    lock.parent.mkdir(parents=True)
    lock.write_text("1", encoding="ascii")
    with pytest.raises(nightly.NightlyError):
        _run(tmp_path, FakeRunner())
    assert lock.exists()                                   # someone else's lock is left alone


def test_prepare_tree_uses_a_detached_worktree_of_origin_main(tmp_path):
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    runner = FakeRunner({"rev-parse": (0, "abc1234\n")})
    tree, commit = nightly.prepare_tree(tmp_path / "home", runner, repo)
    assert tree == tmp_path / "home" / "worktrees" / "nightly"
    assert commit == "abc1234"
    gits = [a for a, _ in runner.calls]
    assert gits[0][3:] == ["fetch", "--quiet", "origin"]
    add = next(a for a in gits if "add" in a)
    assert add[-2:] == [str(tree), "origin/main"] and "--detach" in add
    # the user's checkout is never checked out, reset or cleaned
    assert not any(x in a for a in gits for x in ("reset", "clean", "pull"))


def test_prepare_tree_without_git_tests_this_tree(tmp_path):
    tree, commit = nightly.prepare_tree(tmp_path / "home", FakeRunner(), tmp_path)
    assert tree == tmp_path and commit == ""
