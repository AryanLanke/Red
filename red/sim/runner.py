"""Runs scenarios and keeps the results.

`run_pair(scenario, companion, llm)` plays one conversation and grades every turn by rule (and by
the judge, when given one). A conversation passes when no turn has a failure.
"""

from __future__ import annotations

import json
import logging
import random
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .. import companions
from . import rules
from .harness import SimWorld
from .judge import Judge
from .scenarios import Scenario, expand
from .simuser import SimUser

log = logging.getLogger(__name__)


@dataclass
class Result:
    scenario: str
    category: str
    companion: str
    kind: str
    turns: list[dict] = field(default_factory=list)       # Turn.to_dict() + "failures" + "judge"
    seconds: float = 0.0
    tags: list[str] = field(default_factory=list)

    @property
    def failures(self) -> list[str]:
        return [f"{f}" for t in self.turns for f in t.get("failures", [])]

    @property
    def codes(self) -> list[str]:
        return [f.split(":", 1)[0] for f in self.failures]

    @property
    def passed(self) -> bool:
        return not self.failures

    def to_dict(self) -> dict:
        return {"scenario": self.scenario, "category": self.category, "companion": self.companion,
                "kind": self.kind, "seconds": round(self.seconds, 2), "passed": self.passed,
                "tags": self.tags, "turns": self.turns}


def companion_names(home: Path) -> dict[str, str]:
    return {cid: c.name for cid, c in companions.load_all(home).items()}


def run_pair(sc: Scenario, companion: str, llm, *, judge: Judge | None = None, seed: int = 0,
             real_home: Path | None = None, budgets: dict | None = None) -> Result:
    start = time.perf_counter()
    result = Result(scenario=sc.id, category=sc.category, companion=companion, kind=sc.kind, tags=list(sc.tags))
    with SimWorld(llm, real_home=real_home, companion=companion, memory_facts=list(sc.memory),
                  confirm=sc.confirm) as world:
        names = companion_names(world.home)
        history: list[tuple[str, str]] = []
        persona_text = ""

        def examples() -> list[str]:
            import re
            system = world.chat.system()
            return [line.split(":", 1)[1].strip() for line in system.splitlines()
                    if re.match(r"^\w+: ", line) and not line.startswith(("User:", "A:"))]
        shared_examples = examples()

        def play(meant: str, heard: str | None, expect: dict) -> None:
            nonlocal persona_text
            turn = world.say(meant, heard)
            failures = rules.grade(turn, expect, names, shared_examples, budgets=budgets)
            row = turn.to_dict()
            row["failures"] = [str(f) for f in failures]
            if judge is not None and turn.reply:
                comp = companions.load(turn.companion_after or companion, world.home)
                verdict = judge.grade(comp.name, comp.persona, list(history), turn.heard, turn.reply,
                                      list(sc.memory))
                row["judge"] = verdict.to_dict() if verdict else None
            result.turns.append(row)
            history.append(("you", turn.heard))
            history.append(("companion", turn.reply))

        if sc.kind == "script":
            for line in sc.lines:
                play(line.say, line.heard, line.expect)
        else:
            rng = random.Random(f"{seed}:{sc.id}:{companion}")
            user = SimUser(llm, sc.persona, rng)
            n = rng.randint(sc.turns_min, sc.turns_max)
            play(sc.opener, None, {})
            for _ in range(n - 1):
                comp_name = names.get(world.active(), "Red")
                line = user.next_line(history, comp_name)
                if not line:
                    break
                play(line, None, {})
    result.seconds = time.perf_counter() - start
    return result


def run_all(scenarios: list[Scenario], llm, *, companions_filter: list[str] | None = None,
            judge: Judge | None = None, out_dir: Path | None = None, real_home: Path | None = None,
            progress=print, budgets: dict | None = None, seed: int = 0,
            max_pairs: int | None = None, should_pause=None) -> list[Result]:
    """Every (scenario, companion) pair, one conversation each. Results are appended to
    out_dir/results.jsonl as they finish, so a stopped run keeps what it did.

    `should_pause()` is called before each conversation; it may sleep (the user came back) or return
    True to stop the run.
    """
    every = companions_filter or list(companions.load_all(real_home).keys())
    pairs = expand(scenarios, every)
    if companions_filter:
        pairs = [(s, c) for s, c in pairs if c in companions_filter]
    if max_pairs:
        pairs = pairs[:max_pairs]
    results: list[Result] = []
    sink = None
    if out_dir is not None:
        out_dir.mkdir(parents=True, exist_ok=True)
        sink = (out_dir / "results.jsonl").open("a", encoding="utf-8")
    try:
        for i, (sc, cid) in enumerate(pairs, 1):
            if should_pause is not None and should_pause():
                progress("stopped: the user is back and the budget for this run is used")
                break
            try:
                res = run_pair(sc, cid, llm, judge=judge, seed=seed, real_home=real_home, budgets=budgets)
            except Exception as e:  # noqa: BLE001 - one broken scenario must not end the night
                log.exception("Scenario %s (%s) crashed", sc.id, cid)
                res = Result(scenario=sc.id, category=sc.category, companion=cid, kind=sc.kind, tags=list(sc.tags))
                res.turns = [{"meant": "", "heard": "", "reply": "", "failures": [f"crash: {type(e).__name__}: {e}"],
                              "first_word": 0.0, "total": 0.0, "tool": "none", "via": "", "companion": cid}]
            results.append(res)
            if sink is not None:
                sink.write(json.dumps(res.to_dict(), ensure_ascii=False, default=str) + "\n")
                sink.flush()
            mark = "ok  " if res.passed else "FAIL"
            progress(f"[{i}/{len(pairs)}] {mark} {sc.id} ({cid}) {res.seconds:.1f}s"
                     + ("" if res.passed else "  " + "; ".join(res.failures[:3])))
    finally:
        if sink is not None:
            sink.close()
    return results


def load_results(path: Path) -> list[dict]:
    rows = []
    with Path(path).open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def new_run_dir(root: Path, label: str = "") -> Path:
    stamp = datetime.now().strftime("%Y-%m-%d")
    base = root / stamp
    name = base if not label else base.with_name(f"{stamp}-{label}")
    if name.exists() and (name / "results.jsonl").exists():
        i = 2
        while (name.with_name(f"{name.name}-{i}")).exists():
            i += 1
        name = name.with_name(f"{name.name}-{i}")
    name.mkdir(parents=True, exist_ok=True)
    return name
