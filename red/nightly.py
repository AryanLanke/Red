"""The nightly self-test: every automated test layer, run at night while the PC is idle.

    python -m red nightly on       a scheduled task "Red nightly": 03:00, only once the PC has been idle 10 min
    python -m red nightly off      remove it
    python -m red nightly          is it on, and what did the last run say
    python -m red nightly run      run it now (--force even with the user at the PC, --only unit,installer,
                                   --here to test this tree instead of a fresh origin/main)

What a run does (plan.md section 3), each step logged to RED_HOME\\cache\\nightly\\<date>\\<step>.log:
  unit             the full pytest suite (fakes only: no mic, speakers, windows or hotkeys)
  replay           tests/test_replay.py, the user's real sentences (once it exists)
  score            python -m red score: the Red Score (once it exists; prints "Red Score: 6.2/10")
  sim              the text simulator on Red's own Ollama; no cap at night (python -m red.sim run --big)
  installer-build  installer\\build.ps1 into RED_HOME\\cache\\installer
  installer-test   installer\\sandbox_test.ps1 -Mode auto: Windows Sandbox if this Windows has it, else the
                   staged copy (Smart App Control blocks the unsigned Red-Setup.exe on this PC)
Then report.md (what got worse since the last run, the 5 worst replies) and results.json, which the next
run compares against and `morning_line()` turns into one line for the morning greeting.

It tests origin/main in its own detached worktree (RED_HOME\\worktrees\\nightly), so the user's checkout
and the hidden Red are never touched. It starts no Ollama: the simulator uses the one that is running.
To add a test layer (the voice simulator, the soak), add a Step to STEPS.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable
from xml.sax.saxutils import escape

TASK_NAME = "Red nightly"
START_AT = "03:00"
IDLE_MINUTES = 10              # the task starts only after this long without input
IDLE_WAIT_HOURS = 4            # ...and gives up for the night if the PC never gets idle by then
TIME_LIMIT_HOURS = 12          # room for the 8 h soak (Day 7)
AWAY_SECONDS = 600             # a manual run with less idle than this caps the simulator at 10 conversations
REPO = Path(__file__).resolve().parents[1]
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

Runner = Callable[..., "subprocess.CompletedProcess"]


class NightlyError(RuntimeError):
    pass


# --------------------------------------------------------------------------
# The scheduled task
# --------------------------------------------------------------------------

def _pythonw(python: str | None = None) -> str:
    exe = Path(python or sys.executable)
    w = exe.with_name("pythonw.exe")
    return str(w if w.is_file() else exe)


def _console_python(python: str | None = None) -> str:
    exe = Path(python or sys.executable)
    if exe.name.lower() == "pythonw.exe" and exe.with_name("python.exe").is_file():
        return str(exe.with_name("python.exe"))
    return str(exe)


def _user() -> str:
    domain = os.environ.get("USERDOMAIN", "")
    name = os.environ.get("USERNAME") or getpass.getuser()
    return f"{domain}\\{name}" if domain else name


def task_xml(python: str, workdir: Path, home: Path, user: str, start: date | None = None) -> str:
    """Task Scheduler XML: daily at 03:00, only when idle, never wakes the PC, never on battery, runs as the
    signed-in user with no admin rights and no window."""
    start = start or date.today() + timedelta(days=1)
    args = subprocess.list2cmdline(["-m", "red", "--home", str(home), "nightly", "run"])
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>Red's nightly self-test: unit, replay, simulator and installer tests while the PC is idle. Turn it off with: python -m red nightly off</Description>
    <URI>\\{escape(TASK_NAME)}</URI>
  </RegistrationInfo>
  <Triggers>
    <CalendarTrigger>
      <StartBoundary>{start.isoformat()}T{START_AT}:00</StartBoundary>
      <Enabled>true</Enabled>
      <ScheduleByDay><DaysInterval>1</DaysInterval></ScheduleByDay>
    </CalendarTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>{escape(user)}</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>true</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>true</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <IdleSettings>
      <Duration>PT{IDLE_MINUTES}M</Duration>
      <WaitTimeout>PT{IDLE_WAIT_HOURS}H</WaitTimeout>
      <StopOnIdleEnd>false</StopOnIdleEnd>
      <RestartOnIdle>false</RestartOnIdle>
    </IdleSettings>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <RunOnlyIfIdle>true</RunOnlyIfIdle>
    <WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>PT{TIME_LIMIT_HOURS}H</ExecutionTimeLimit>
    <Priority>7</Priority>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{escape(python)}</Command>
      <Arguments>{escape(args)}</Arguments>
      <WorkingDirectory>{escape(str(workdir))}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"""


class NightlyTask:
    """`schtasks` with an XML file: no admin, no password (runs only while the user is signed in)."""

    def __init__(self, home: Path, runner: Runner = subprocess.run, python: str | None = None,
                 workdir: Path = REPO, user: Callable[[], str] = _user):
        self.home = Path(home)
        self._run = runner
        self.python = _pythonw(python)
        self.workdir = Path(workdir)
        self._user = user

    def _schtasks(self, *args: str) -> subprocess.CompletedProcess:
        try:
            return self._run(["schtasks.exe", *args], capture_output=True, text=True, timeout=30,
                             creationflags=NO_WINDOW)
        except (OSError, subprocess.SubprocessError) as e:
            raise NightlyError(f"schtasks failed: {e}") from e

    def is_on(self) -> bool:
        return self._schtasks("/Query", "/TN", TASK_NAME).returncode == 0

    def on(self) -> str:
        folder = self.home / "cache" / "nightly"
        folder.mkdir(parents=True, exist_ok=True)
        xml = folder / "task.xml"
        xml.write_text(task_xml(self.python, self.workdir, self.home, self._user()), encoding="utf-16")
        r = self._schtasks("/Create", "/TN", TASK_NAME, "/XML", str(xml), "/F")
        if r.returncode != 0:
            raise NightlyError(f"Couldn't create the task: {' '.join((r.stderr or r.stdout or '').split())[:200]}")
        return (f"The nightly self-test runs at {START_AT} once the PC has been idle {IDLE_MINUTES} minutes "
                f"(never on battery, never waking the PC). Reports: {folder}\\<date>\\report.md")

    def off(self) -> str:
        if not self.is_on():
            return "The nightly self-test wasn't on."
        r = self._schtasks("/Delete", "/TN", TASK_NAME, "/F")
        if r.returncode != 0:
            raise NightlyError(f"Couldn't remove the task: {' '.join((r.stderr or r.stdout or '').split())[:200]}")
        return "The nightly self-test is off."

    def status(self) -> str:
        state = ("on: " + START_AT + " when the PC is idle") if self.is_on() else \
            "off (turn it on with: python -m red nightly on)"
        line = morning_line(self.home, max_age_hours=24 * 365)
        return f"The nightly self-test is {state}." + (f"\n{line}" if line else "")


# --------------------------------------------------------------------------
# The steps
# --------------------------------------------------------------------------

@dataclass
class Context:
    tree: Path                     # the source tree under test
    home: Path                     # RED_HOME
    night: Path                    # RED_HOME\cache\nightly\<date>
    python: str                    # a console python.exe with Red's packages
    away: bool                     # the user is away: no cap on real-model runs
    results: dict = field(default_factory=dict)

    @property
    def installer(self) -> Path:
        return self.home / "cache" / "installer"


@dataclass
class Step:
    name: str
    what: str
    command: Callable[[Context], list[str] | None]    # None: skipped (not built yet)
    timeout_minutes: int = 60
    needs: str = ""                                    # another step that must have passed
    numbers: Callable[[Context, str], dict] = lambda ctx, log: {}


def _pytest_counts(log: str) -> dict:
    tail = "\n".join(log.strip().splitlines()[-5:])
    return {k if k != "error" else "errors": int(n)
            for n, k in re.findall(r"(\d+) (passed|failed|errors?|skipped|xfailed|xpassed)", tail)}


def _pytest(ctx: Context, *targets: str) -> list[str]:
    return [ctx.python, "-m", "pytest", *targets, "-q", "-p", "no:cacheprovider",
            f"--basetemp={ctx.night / 'pytest-tmp'}"]


def _cmd_replay(ctx: Context) -> list[str] | None:
    return _pytest(ctx, "tests/test_replay.py") if (ctx.tree / "tests" / "test_replay.py").is_file() else None


def _cmd_score(ctx: Context) -> list[str] | None:
    return [ctx.python, "-m", "red", "score"] if (ctx.tree / "red" / "score.py").is_file() else None


def _score_numbers(ctx: Context, log: str) -> dict:
    m = re.findall(r"Red Score\D{0,10}(\d+(?:\.\d+)?)\s*/\s*10", log)
    return {"score": float(m[-1])} if m else {}


def _cmd_sim(ctx: Context) -> list[str] | None:
    if not (ctx.tree / "red" / "sim" / "__main__.py").is_file():
        return None
    cap = ["--big", "--minutes", "150"] if ctx.away else ["--limit", "10"]
    return [ctx.python, "-m", "red.sim", "run", *cap, "--label", "nightly", "--out", str(ctx.night / "sim")]


def _sim_numbers(ctx: Context, log: str) -> dict:
    rows = _sim_rows(ctx.night)
    if not rows:
        return {}
    firsts = sorted(t["first_word"] for r in rows for t in r.get("turns", [])
                    if isinstance(t.get("first_word"), (int, float)))
    passed = sum(1 for r in rows if r.get("passed"))
    out = {"conversations": len(rows), "passed": passed, "pass_rate": round(passed / len(rows), 3)}
    if firsts:
        out["first_word_median"] = round(firsts[len(firsts) // 2], 2)
    return out


def _sim_rows(night: Path) -> list[dict]:
    found = sorted((night / "sim").glob("*/results.jsonl"))
    if not found:
        return []
    rows = []
    for line in found[-1].read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    return rows


def _powershell() -> str:
    root = os.environ.get("SystemRoot", r"C:\Windows")
    ps = Path(root) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    return str(ps) if ps.is_file() else "powershell.exe"


def _cmd_build(ctx: Context) -> list[str] | None:
    script = ctx.tree / "installer" / "build.ps1"
    if not script.is_file():
        return None
    return [_powershell(), "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script),
            "-Python", ctx.python, "-Work", str(ctx.installer / "work"), "-Out", str(ctx.installer / "out")]


def _build_numbers(ctx: Context, log: str) -> dict:
    exe = ctx.installer / "out" / "Red-Setup.exe"
    return {"setup_mb": round(exe.stat().st_size / 2**20)} if exe.is_file() else {}


def _cmd_install_test(ctx: Context) -> list[str] | None:
    script = ctx.tree / "installer" / "sandbox_test.ps1"
    if not script.is_file():
        return None
    return [_powershell(), "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script), "-Mode", "auto",
            "-Setup", str(ctx.installer / "out" / "Red-Setup.exe"), "-Stage", str(ctx.installer / "work" / "stage"),
            "-Results", str(ctx.night / "installer")]


def _install_numbers(ctx: Context, log: str) -> dict:
    path = ctx.night / "installer" / "result.json"
    try:
        r = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}
    checks = r.get("checks") or []
    return {"mode": r.get("mode"), "checks": len(checks),
            "failed_checks": [c.get("name") for c in checks if not c.get("ok")]}


STEPS: list[Step] = [
    Step("unit", "the full unit suite", lambda ctx: _pytest(ctx, "tests"), 90,
         numbers=lambda ctx, log: _pytest_counts(log)),
    Step("replay", "the user's real sentences", _cmd_replay, 20, numbers=lambda ctx, log: _pytest_counts(log)),
    Step("score", "the Red Score", _cmd_score, 120, numbers=_score_numbers),
    Step("sim", "the text simulator on the real model", _cmd_sim, 180, numbers=_sim_numbers),
    Step("installer-build", "Red-Setup.exe builds", _cmd_build, 45, numbers=_build_numbers),
    Step("installer-test", "install, red doctor, uninstall", _cmd_install_test, 40, needs="installer-build",
         numbers=_install_numbers),
]


# --------------------------------------------------------------------------
# Running
# --------------------------------------------------------------------------

def _idle_seconds() -> float:
    try:
        from .greeter import idle_seconds
        return float(idle_seconds())
    except Exception:  # noqa: BLE001 - unknown: assume the user is here
        return 0.0


def _git(runner: Runner, *args: str, cwd: Path = REPO) -> subprocess.CompletedProcess:
    return runner(["git", "-C", str(cwd), *args], capture_output=True, text=True, timeout=300,
                  creationflags=NO_WINDOW)


def prepare_tree(home: Path, runner: Runner = subprocess.run, repo: Path = REPO) -> tuple[Path, str]:
    """A detached worktree at origin/main (fetched now). Returns (tree, commit). Without git: this tree."""
    if not (repo / ".git").exists():
        return repo, ""
    tree = home / "worktrees" / "nightly"
    if _git(runner, "fetch", "--quiet", "origin", cwd=repo).returncode != 0:
        raise NightlyError("git fetch failed")
    if (tree / ".git").exists():
        r = _git(runner, "checkout", "--quiet", "--detach", "--force", "origin/main", cwd=tree)
    else:
        _git(runner, "worktree", "prune", cwd=repo)
        r = _git(runner, "worktree", "add", "--quiet", "--detach", str(tree), "origin/main", cwd=repo)
    if r.returncode != 0:
        raise NightlyError(f"couldn't check out origin/main in {tree}: {' '.join((r.stderr or '').split())[:200]}")
    head = _git(runner, "rev-parse", "--short", "HEAD", cwd=tree)
    return tree, (head.stdout or "").strip()


def _env(ctx: Context) -> dict:
    env = dict(os.environ)
    env.update(RED_HOME=str(ctx.home), QT_QPA_PLATFORM="offscreen", PYTHONIOENCODING="utf-8",
               RED_NIGHTLY_DIR=str(ctx.night))
    fonts = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "Fonts"
    if fonts.is_dir():
        env["QT_QPA_FONTDIR"] = str(fonts)
    return env


def run_step(step: Step, ctx: Context, runner: Runner = subprocess.run) -> dict:
    out = {"name": step.name, "what": step.what, "status": "skipped", "seconds": 0, "detail": ""}
    if step.needs and ctx.results.get(step.needs, {}).get("status") != "ok":
        out["detail"] = f"{step.needs} did not pass"
        return out
    argv = step.command(ctx)
    if argv is None:
        out["detail"] = "not built yet"
        return out
    log_path = ctx.night / f"{step.name}.log"
    started = time.monotonic()
    try:
        with open(log_path, "w", encoding="utf-8", errors="replace") as log:
            r = runner(argv, cwd=str(ctx.tree), env=_env(ctx), stdout=log, stderr=subprocess.STDOUT,
                       timeout=step.timeout_minutes * 60, creationflags=NO_WINDOW)
        code = r.returncode
        out["status"] = "ok" if code == 0 else "fail"
        out["detail"] = "" if code == 0 else f"exit {code}"
    except subprocess.TimeoutExpired:
        out["status"], out["detail"] = "fail", f"timed out after {step.timeout_minutes} min"
    except OSError as e:
        out["status"], out["detail"] = "fail", str(e)[:200]
    out["seconds"] = round(time.monotonic() - started)
    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        text = ""
    try:
        out["numbers"] = step.numbers(ctx, text)
    except Exception as e:  # noqa: BLE001 - a number we can't read must not lose the step
        out["numbers"] = {"error": str(e)[:120]}
    return out


def nightly_root(home: Path) -> Path:
    return Path(home) / "cache" / "nightly"


def previous_results(home: Path, before: str) -> dict | None:
    for d in sorted(nightly_root(home).glob("20??-??-??*"), reverse=True):
        if d.name < before and (d / "results.json").is_file():
            try:
                return json.loads((d / "results.json").read_text(encoding="utf-8"))
            except ValueError:
                continue
    return None


def worse(now: dict, before: dict | None) -> list[str]:
    """What got worse since the last run, one line each."""
    if not before:
        return []
    old = {s["name"]: s for s in before.get("steps", [])}
    lines = []
    for s in now.get("steps", []):
        o = old.get(s["name"])
        if not o:
            continue
        n, p = s.get("numbers") or {}, o.get("numbers") or {}
        if s["status"] == "fail" and o["status"] == "ok":
            lines.append(f"{s['name']} passed last time and fails now ({s['detail']})")
        if n.get("failed", 0) + n.get("errors", 0) > p.get("failed", 0) + p.get("errors", 0):
            lines.append(f"{s['name']}: {n.get('failed', 0) + n.get('errors', 0)} tests fail "
                         f"(was {p.get('failed', 0) + p.get('errors', 0)})")
        if "score" in n and "score" in p and n["score"] < p["score"]:
            lines.append(f"Red Score {n['score']:g}/10 (was {p['score']:g})")
        if "pass_rate" in n and "pass_rate" in p and n["pass_rate"] < p["pass_rate"] - 0.02:
            lines.append(f"simulator {n['pass_rate']:.0%} passed (was {p['pass_rate']:.0%})")
        if "first_word_median" in n and "first_word_median" in p and \
                n["first_word_median"] > p["first_word_median"] * 1.1 + 0.05:
            lines.append(f"first word {n['first_word_median']:.2f} s median (was {p['first_word_median']:.2f} s)")
        if "setup_mb" in n and "setup_mb" in p and n["setup_mb"] > p["setup_mb"] * 1.05:
            lines.append(f"Red-Setup.exe {n['setup_mb']} MB (was {p['setup_mb']} MB)")
    return lines


def _worst_replies(night: Path, n: int = 5) -> list[str]:
    rows = [r for r in _sim_rows(night) if not r.get("passed")]
    if not rows:
        return []
    try:
        from .sim.report import badness, conversation
    except ImportError:
        return [f"- {r.get('scenario')}" for r in rows[:n]]
    return [conversation(r) for r in sorted(rows, key=badness, reverse=True)[:n]]


def _number_text(numbers: dict) -> str:
    parts = []
    for k, v in numbers.items():
        if k == "failed_checks":
            if v:
                parts.append("failed: " + ", ".join(v))
        elif isinstance(v, float) and k == "pass_rate":
            parts.append(f"{v:.0%} passed")
        else:
            parts.append(f"{k.replace('_', ' ')} {v}")
    return "; ".join(parts)


def render(results: dict, night: Path) -> str:
    steps = results["steps"]
    bad = [s for s in steps if s["status"] == "fail"]
    head = "all green" if not bad else f"{len(bad)} of {sum(s['status'] != 'skipped' for s in steps)} steps failed"
    lines = [f"# Red nightly, {results['date']}", "",
             f"_{results['started']} to {results['finished']}; origin/main at `{results.get('commit') or '?'}`; "
             f"user away: {'yes' if results['away'] else 'no (simulator capped at 10)'}_", "",
             f"**{head}.**", ""]
    score = next((s["numbers"]["score"] for s in steps if (s.get("numbers") or {}).get("score") is not None), None)
    if score is not None:
        lines += [f"**Red Score: {score:g}/10**", ""]
    lines += ["| step | result | time | numbers |", "|---|---|---|---|"]
    for s in steps:
        mark = {"ok": "ok", "fail": "**FAIL**", "skipped": "skipped"}[s["status"]]
        detail = f" ({s['detail']})" if s["detail"] else ""
        lines.append(f"| {s['name']}: {s['what']} | {mark}{detail} | {s['seconds'] // 60}:{s['seconds'] % 60:02d} | "
                     f"{_number_text(s.get('numbers') or {})} |")
    got_worse = results.get("worse") or []
    lines += ["", "## What got worse", ""] + ([f"- {w}" for w in got_worse] or
                                              ["- nothing" if results.get("compared") else "- (first run: nothing to compare)"])
    worst = _worst_replies(night)
    if worst:
        lines += ["", f"## The {len(worst)} worst replies", ""] + worst
    lines += ["", f"Logs: `{night}\\<step>.log`"]
    return "\n".join(lines) + "\n"


def run(home: Path, only: list[str] | None = None, force: bool = False, here: bool = False,
        runner: Runner = subprocess.run, python: str | None = None, idle: Callable[[], float] = _idle_seconds,
        today: Callable[[], datetime] = datetime.now, repo: Path = REPO) -> dict:
    home = Path(home)
    now = today()
    night = nightly_root(home) / now.strftime("%Y-%m-%d")
    night.mkdir(parents=True, exist_ok=True)
    lock = nightly_root(home) / "running.lock"
    if lock.exists() and time.time() - lock.stat().st_mtime < TIME_LIMIT_HOURS * 3600 and not force:
        raise NightlyError(f"another nightly run is going ({lock}); --force runs anyway")
    lock.write_text(str(os.getpid()), encoding="ascii")
    try:
        tree, commit = (repo, "") if here else prepare_tree(home, runner, repo)
        if here:
            head = _git(runner, "rev-parse", "--short", "HEAD", cwd=repo)
            commit = (head.stdout or "").strip() + " (this tree)"
        ctx = Context(tree=tree, home=home, night=night, python=_console_python(python),
                      away=idle() >= AWAY_SECONDS)
        results = {"date": night.name, "started": now.strftime("%H:%M"), "commit": commit, "away": ctx.away,
                   "tree": str(tree), "steps": []}
        for step in STEPS:
            if only and step.name not in only:
                continue
            r = run_step(step, ctx, runner)
            ctx.results[step.name] = r
            results["steps"].append(r)
        results["finished"] = today().strftime("%H:%M")
        before = previous_results(home, night.name)
        results["compared"] = before is not None
        results["worse"] = worse(results, before)
        (night / "results.json").write_text(json.dumps(results, indent=1), encoding="utf-8")
        (night / "report.md").write_text(render(results, night), encoding="utf-8")
        return results
    finally:
        try:
            lock.unlink()
        except OSError:
            pass


def morning_line(home: Path, now: datetime | None = None, max_age_hours: float = 18) -> str:
    """One line for the morning greeting about the last run, or "" if there's none from last night."""
    now = now or datetime.now()
    for d in sorted(nightly_root(home).glob("20??-??-??"), reverse=True):
        path = d / "results.json"
        if not path.is_file():
            continue
        if (now.timestamp() - path.stat().st_mtime) > max_age_hours * 3600:
            return ""
        try:
            r = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            return ""
        steps = r.get("steps", [])
        failed = [s["name"] for s in steps if s["status"] == "fail"]
        score = next((s["numbers"]["score"] for s in steps if (s.get("numbers") or {}).get("score") is not None),
                     None)
        bits = [f"score {score:g}/10"] if score is not None else []
        if failed:
            bits.append(f"{', '.join(failed)} failed")
        elif r.get("worse"):
            bits.append(f"{len(r['worse'])} thing{'s' if len(r['worse']) != 1 else ''} got worse")
        else:
            bits.append("all green")
        return "Last night's self-test: " + "; ".join(bits) + "."
    return ""


def main(argv: list[str], home: Path, task: NightlyTask | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m red nightly")
    p.add_argument("action", nargs="?", choices=("on", "off", "run", "status"), default="status")
    p.add_argument("--only", default="", help="comma-separated steps: " + ",".join(s.name for s in STEPS))
    p.add_argument("--force", action="store_true", help="run even if another run seems to be going")
    p.add_argument("--here", action="store_true", help="test this tree as it is, not a fresh origin/main")
    a = p.parse_args(argv)
    try:
        if a.action == "run":
            only = [s.strip() for s in a.only.split(",") if s.strip()] or None
            unknown = set(only or []) - {s.name for s in STEPS}
            if unknown:
                print(f"error: unknown step(s): {', '.join(sorted(unknown))}", file=sys.stderr)
                return 2
            r = run(home, only=only, force=a.force, here=a.here)
            night = nightly_root(home) / r["date"]
            print(render(r, night))
            return 0 if all(s["status"] != "fail" for s in r["steps"]) else 1
        task = task or NightlyTask(home)
        print({"on": task.on, "off": task.off}.get(a.action, task.status)())
    except NightlyError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0
