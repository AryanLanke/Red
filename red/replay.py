"""Replay: every real sentence the user said to Red, labelled once (plan.md 3, part A1).

The lines live in tests/replay/*.toml (see the header of commands.toml for the fields). Two ways to play
them, both through the real turn loop (`VoiceApp._exchange`, via red/sim/harness.py's SimWorld):

- `run_offline(lines)`: no model. A stand-in model answers every route with talk. What it checks is
  everything before and around the model, and is the same every run, so it runs on every commit
  (tests/test_replay.py):
    * the sentence reaches Red: never dropped silently (an editor is in front, Red is listening for a
      follow-up: the case that dropped "write a code for me" five times on 2026-11-14). "For me?" is
      allowed: Red asked, it didn't drop it;
    * a sentence that needs a tool is not sent straight to chat (red/gate.py), where no tool can run;
    * the fast path runs the right tool, and never one for talk or noise;
    * the fixed replies (small talk, switching, dismissal) have no stock lines.
- `run_model(lines, llm)`: the real model. Grades the tool, its arguments and the reply by rule
  (red/sim/rules.py), and times the first word. `python -m red score` uses it.
"""

from __future__ import annotations

import contextlib
import shutil
import statistics
import tempfile
import time
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

REPLAY_DIR = Path(__file__).resolve().parents[1] / "tests" / "replay"
EDITOR_TITLE = "plan.md - red - visual studio code code.exe"     # the window in front while replaying
KINDS = ("talk", "noise", "zip")


@dataclass
class Line:
    said: str
    want: list[str]
    args: str = ""
    forbid: str = ""
    after: str = ""
    note: str = ""
    seen: int = 1
    first: str = ""
    source: str = ""

    @property
    def tools(self) -> list[str]:
        return [w for w in self.want if w not in KINDS]

    @property
    def kind(self) -> str:
        """'tool' when a tool may run, else 'talk', 'noise' or 'zip'."""
        if self.tools:
            return "tool"
        return self.want[0]

    @property
    def for_red(self) -> bool:
        """Must reach Red: everything but noise and "I'm not talking to you"."""
        return self.kind in ("tool", "talk")


def load(folder: Path = REPLAY_DIR) -> list[Line]:
    out: list[Line] = []
    for path in sorted(Path(folder).glob("*.toml")):
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        for row in data.get("line", []):
            want = row["want"]
            want = [want] if isinstance(want, str) else list(want)
            out.append(Line(said=row["said"], want=want, args=row.get("args", ""), forbid=row.get("forbid", ""),
                            after=row.get("after", ""), note=row.get("note", ""), seen=int(row.get("seen", 1)),
                            first=str(row.get("first", "")), source=path.stem))
    return out


def labelled_keys(lines: list[Line]) -> set[str]:
    return {_key(line.said) for line in lines}


def _key(text: str) -> str:
    import re
    return " ".join(re.sub(r"[^\w' ]+", " ", (text or "").lower()).split())


def unlabelled(log_path: Path, lines: list[Line] | None = None) -> list[str]:
    """Sentences in the command log that no replay line covers yet (to label them)."""
    import json
    known = labelled_keys(lines if lines is not None else load())
    new: list[str] = []
    seen: set[str] = set()
    try:
        rows = Path(log_path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    for raw in rows:
        try:
            said = json.loads(raw).get("command", "")
        except ValueError:
            continue
        k = _key(said)
        if k and k not in known and k not in seen:
            seen.add(k)
            new.append(said)
    return new


# --- without a model ---------------------------------------------------------------------------------

class OfflineLLM:
    """Stands in for the model: every route is talk, every reply is "Okay." Counts the calls."""

    def __init__(self):
        self.calls = 0

    def complete_json(self, system, user, schema, *args, **kwargs):
        import json
        self.calls += 1
        if isinstance(schema, dict) and "anyOf" in schema:
            return json.dumps({"tool": "none", "args": {"reply": "Okay."}})
        props = (schema or {}).get("properties", {}) if isinstance(schema, dict) else {}
        key = "reply" if "reply" in props or not props else next(iter(props))
        return json.dumps({key: "Okay."})


@dataclass
class Result:
    line: Line
    outcome: str = ""          # reached | asked | dropped | quiet | zipped
    via: str = ""
    tool: str = "none"
    reply: str = ""
    problems: list[str] = field(default_factory=list)
    first_word: float = 0.0
    failures: list[str] = field(default_factory=list)      # model replay: red/sim/rules.py codes

    @property
    def ok(self) -> bool:
        return not self.problems

    def to_dict(self) -> dict:
        return {"said": self.line.said, "want": self.line.want, "outcome": self.outcome, "via": self.via,
                "tool": self.tool, "reply": self.reply, "problems": self.problems,
                "failures": self.failures, "first_word": round(self.first_word, 3)}


FIXED_STAGES = ("quick", "switch", "dismissed", "name", "stop")


@contextlib.contextmanager
def _editor_in_front(title: str = EDITOR_TITLE):
    from . import __main__ as cli
    from . import conversation
    saved = cli.foreground_title, conversation.foreground_title
    cli.foreground_title = conversation.foreground_title = lambda: title
    try:
        yield
    finally:
        cli.foreground_title, conversation.foreground_title = saved


def _outcome(world, turn) -> str:
    lines = " | ".join(world.capture.lines).lower()
    if turn.spoken == ["For me?"]:
        return "asked"
    if "-> zip" in lines:
        return "zipped"
    if turn.router_calls or turn.chat_calls or turn.via in FIXED_STAGES + ("fast",) or turn.calls:
        return "reached"
    if "not for me" in lines:
        return "dropped"
    if turn.reply or turn.spoken:
        return "reached"
    return "quiet"


def judge_offline(line: Line, world, turn) -> Result:
    from .sim.rules import STOCK, text_problems
    res = Result(line=line, via=turn.via, tool=turn.tool or "none", reply=turn.reply or "")
    res.outcome = _outcome(world, turn)
    p = res.problems
    if line.for_red and res.outcome == "dropped":
        p.append("dropped silently (not for me)")
    if line.for_red and res.outcome == "quiet":
        p.append("ignored without a word (filler)")
    if line.for_red and res.outcome == "zipped":
        p.append("zipped the mouth")
    if line.kind == "zip" and res.outcome != "zipped":
        p.append(f"should zip, got {res.outcome}")
    ran = res.tool if res.tool != "none" else ""
    if line.kind == "tool":
        if res.via == "gate" and not ran:
            p.append("sent straight to chat: no tool can run")
        if ran and ran.split("+")[0] not in line.tools:
            p.append(f"fast path ran {ran}, wanted {'/'.join(line.tools)}")
        if ran and line.args:
            import re
            from .sim.rules import _arg_text
            if not re.search(line.args, _arg_text(turn.args or {}), re.I):
                p.append(f"arguments {turn.args} don't match /{line.args}/")
    elif ran:
        p.append(f"ran {ran} for {line.kind}")
    if res.via in FIXED_STAGES and res.reply:
        for f in text_problems(res.reply):
            if f.code in ("stock", "invented_life", "laughter", "placeholder"):
                p.append(f"fixed reply: {f}")
        if STOCK.search(res.reply) and not any("stock" in x for x in p):
            p.append("fixed reply: stock line")
    return res


def _fresh(world) -> None:
    """Forget the last turn: each line is played on its own (after its `after` line, if any)."""
    world._tool = None
    world._again = False
    world.app._held = ""
    world.app._last_said = ""
    try:
        world.chat.end_debate()
    except Exception:  # noqa: BLE001
        pass
    turns = getattr(world.chat, "turns", None)
    if hasattr(turns, "clear"):
        turns.clear()


def run_offline(lines: list[Line] | None = None, *, title: str = EDITOR_TITLE) -> list[Result]:
    """Every line through the real turn loop, no model. Red is listening for a follow-up with an editor
    in front: the strictest case for "is it for me?"."""
    from .sim.harness import SimWorld
    lines = load() if lines is None else lines
    empty = Path(tempfile.mkdtemp(prefix="red-replay-home-"))
    results: list[Result] = []
    try:
        with _editor_in_front(title):
            world = SimWorld(OfflineLLM(), real_home=empty)
            world.app._echo_guard = lambda: None          # no 0.3 s wait for a room echo: there is no room
            try:
                for line in lines:
                    _fresh(world)
                    if line.after:
                        world.say(line.after, follow_up=True)
                    turn = world.say(line.said, follow_up=True)
                    results.append(judge_offline(line, world, turn))
                    world.app.conversation.unzip()
            finally:
                world.close()
    finally:
        shutil.rmtree(empty, ignore_errors=True)
    return results


# --- with the real model -----------------------------------------------------------------------------

CORRECT_CODES = {"wrong_tool", "missed_command", "spurious_command", "literal_query", "crash", "empty",
                 "placeholder", "no_confirm", "unsafe"}
TEXT_CODES = {"stock", "invented_life", "laughter"}


def expectation(line: Line) -> dict:
    exp: dict = {}
    if line.kind == "tool":
        exp["tool"] = ["none" if w == "talk" else w for w in line.want if w != "noise"]
        if line.args:
            exp["args_match"] = line.args
    elif line.kind == "talk":
        exp["chat"] = True
    else:
        exp["no_tool"] = True
        exp["silent"] = True
    if line.forbid:
        exp["args_forbid"] = [line.forbid]
    return exp


def run_model(lines: list[Line], llm, *, real_home: Path | None = None, on_result=None) -> list[Result]:
    """Every line through the real loop and the real model, each in a fresh world (with its `after` line
    first). Tools run in dry run: nothing happens on the PC."""
    from .sim import rules
    from .sim.harness import SimWorld
    results: list[Result] = []
    for line in lines:
        with SimWorld(llm, real_home=real_home, confirm="no") as world:
            if line.after:
                world.say(line.after)
            turn = world.say(line.said, follow_up=bool(line.after))
            res = Result(line=line, via=turn.via, tool=turn.tool or "none", reply=turn.reply or "",
                         first_word=turn.first_word)
            res.outcome = _outcome(world, turn)
            exp = expectation(line)
            fails = rules.grade(turn, exp)
            res.failures = [str(f) for f in fails if f.code != "slow"]
            if line.kind == "zip" and res.outcome != "zipped":
                res.failures.append(f"wrong_tool: should zip, got {res.outcome}")
            res.problems = [f for f in res.failures if f.split(":", 1)[0] in CORRECT_CODES | TEXT_CODES]
            results.append(res)
            if on_result is not None:
                on_result(res)
    return results


def summarize(offline: list[Result] | None = None, model: list[Result] | None = None) -> dict:
    """The numbers the Red Score uses."""
    out: dict = {}
    if offline is not None:
        for_red = [r for r in offline if r.line.for_red]
        out["offline_lines"] = len(offline)
        out["offline_failures"] = sum(1 for r in offline if not r.ok)
        out["dropped_silently"] = sum(1 for r in for_red if r.outcome in ("dropped", "quiet", "zipped"))
        out["asked_for_me"] = sum(1 for r in for_red if r.outcome == "asked")
        out["skipped_router"] = sum(1 for r in offline if any("straight to chat" in p for p in r.problems))
    if model:
        work = [r for r in model if r.line.kind == "tool"]
        talk = [r for r in model if r.line.kind == "talk"]
        out["model_lines"] = len(model)
        out["requests"] = len(work)
        out["requests_correct"] = sum(1 for r in work if not any(
            f.split(":", 1)[0] in CORRECT_CODES for f in r.failures))
        out["talk_lines"] = len(talk)
        out["talk_first_word_median"] = (statistics.median(r.first_word for r in talk) if talk else None)
        out["stock_lines"] = sum(1 for r in model for f in r.failures if f.split(":", 1)[0] in TEXT_CODES)
        out["model_dropped"] = sum(1 for r in model if r.line.for_red and r.outcome in ("dropped", "quiet"))
    return out


def sample(lines: list[Line], n: int, seed: int = 0) -> list[Line]:
    """`n` lines, about half real requests and half talk, the same every run for a seed."""
    import random
    rng = random.Random(seed)
    work = [l for l in lines if l.kind == "tool"]
    talk = [l for l in lines if l.kind == "talk"]
    rest = [l for l in lines if l.kind not in ("tool", "talk")]
    rng.shuffle(work), rng.shuffle(talk), rng.shuffle(rest)
    half = (n + 1) // 2
    picked = work[:half] + talk[:n - half]
    if len(picked) < n:
        picked += rest[:n - len(picked)]
    return picked[:n]


def timed(fn, *a, **kw):
    start = time.perf_counter()
    out = fn(*a, **kw)
    return out, time.perf_counter() - start
