"""Scenarios are data (red/sim/scenarios/*.toml), not code.

    [[scenario]]
    id = "whatever-song"
    category = "music-choice"          # what the report groups by
    tags = ["user-failure", "regress"] # "regress" puts it in the fixed regression set
    companion = "red"                  # a companion id, a list of ids, or "*" (all of them)
    memory = ["The user's name is Aryan."]      # facts in the temporary memory (optional)
    confirm = "no"                     # what the user answers when Red asks "Shut down?"
    turns = [
      { say = "It's on you, whatever song you wanna play", expect = { tool = "play_online" } },
      { say = "switch to Rennel", heard = "Switch to Rennel.", expect = { companion = "remy" } },
    ]

`say` is what the user meant; `heard` (optional) is what Whisper made of it. Only `heard` goes into
the pipeline. `expect` is graded by red/sim/rules.py (see `grade`).

A simulated-user scenario has no fixed lines after the opener; the local model plays the person:

    [[scenario]]
    id = "bored-evening"
    category = "chat-bored"
    kind = "sim"
    persona = { mood = "bored", goal = "wants something fun to do", style = "short, lazy, lowercase" }
    opener = "man I'm so bored"
    turns_min = 4
    turns_max = 6
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

DIR = Path(__file__).resolve().parent / "scenarios"


@dataclass
class Line:
    say: str
    heard: str | None = None
    expect: dict = field(default_factory=dict)


@dataclass
class Scenario:
    id: str
    category: str
    lines: list[Line] = field(default_factory=list)
    tags: tuple[str, ...] = ()
    companions: tuple[str, ...] = ("red",)       # "*" is expanded by `expand`
    memory: tuple[str, ...] = ()
    confirm: str = "no"
    kind: str = "script"                         # script | sim
    persona: dict = field(default_factory=dict)
    opener: str = ""
    turns_min: int = 3
    turns_max: int = 6
    source: str = ""

    @property
    def regress(self) -> bool:
        return "regress" in self.tags


def _companions(value) -> tuple[str, ...]:
    if value is None:
        return ("red",)
    if isinstance(value, str):
        return (value,)
    return tuple(value)


def parse(data: dict, source: str = "") -> list[Scenario]:
    out = []
    for item in data.get("scenario", []):
        lines = [Line(say=t["say"], heard=t.get("heard"), expect=dict(t.get("expect", {})))
                 for t in item.get("turns", []) if isinstance(t, dict)]
        sc = Scenario(
            id=item["id"], category=item.get("category", "misc"), lines=lines,
            tags=tuple(item.get("tags", ())), companions=_companions(item.get("companion")),
            memory=tuple(item.get("memory", ())), confirm=item.get("confirm", "no"),
            kind=item.get("kind", "script"), persona=dict(item.get("persona", {})),
            opener=item.get("opener", ""), turns_min=int(item.get("turns_min", 3)),
            turns_max=int(item.get("turns_max", 6)), source=source)
        if sc.kind == "sim" and not sc.opener:
            raise ValueError(f"scenario {sc.id}: a sim scenario needs an opener")
        if sc.kind == "script" and not sc.lines:
            raise ValueError(f"scenario {sc.id}: no turns")
        out.append(sc)
    return out


def load(path: Path | str | None = None) -> list[Scenario]:
    """Every scenario in a file, or in every *.toml of a folder (default: red/sim/scenarios)."""
    path = Path(path) if path else DIR
    files = sorted(path.glob("*.toml")) if path.is_dir() else [path]
    scenarios: list[Scenario] = []
    seen: set[str] = set()
    for f in files:
        with f.open("rb") as fh:
            for sc in parse(tomllib.load(fh), f.name):
                if sc.id in seen:
                    raise ValueError(f"duplicate scenario id {sc.id!r} ({f.name})")
                seen.add(sc.id)
                scenarios.append(sc)
    return scenarios


def expand(scenarios: list[Scenario], every_companion: list[str]) -> list[tuple[Scenario, str]]:
    """(scenario, companion id) pairs: "*" runs the scenario once per companion."""
    pairs = []
    for sc in scenarios:
        ids = every_companion if "*" in sc.companions else list(sc.companions)
        pairs += [(sc, cid) for cid in ids]
    return pairs


def select(scenarios: list[Scenario], *, only: str | None = None, category: str | None = None,
           tag: str | None = None, regress: bool = False) -> list[Scenario]:
    out = scenarios
    if only:
        out = [s for s in out if any(part and part in s.id for part in only.split(","))]
    if category:
        out = [s for s in out if s.category == category or s.category.startswith(category + "-")]
    if tag:
        out = [s for s in out if tag in s.tags]
    if regress:
        out = [s for s in out if s.regress]
    return out
