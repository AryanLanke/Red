"""The Red Score (plan.md 2): the ship measures turned into one 0-10 number.

    python -m red score                 # replay without a model, plus 10 real-model lines (more when away)
    python -m red score --offline       # no model at all
    python -m red score --big           # every replay line on the model (the nightly run; the user is away)
    python -m red score --persona       # also the blind "who said this?" test (scripts/persona_eval.py)

Each measure gets 0 to 1 point: 1 when it meets its v1 target, less the further off it is. A measure
that can't be taken yet (its part isn't built) gets 0, so the score only reaches 8+ when the work is
really done. The report also gives the score over what was measured.

Writes RED_HOME\\cache\\score\\<date>-<time>\\score.md and score.json (every line and reply). Real-model
runs use the hidden Red's Ollama and never start a second one; tools run in dry run.
"""

from __future__ import annotations

import json
import statistics
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AWAY_SECONDS = 600            # no input for 10 minutes: the user is away
BUSY_LINES = 10               # real-model lines at most while the user is at the PC


@dataclass
class Measure:
    key: str
    label: str
    target: str
    kind: str                 # max: value <= goal; min: value >= goal; zero: a count that must be 0
    goal: float
    unit: str = ""
    part: str = ""            # the plan part that makes it measurable
    value: float | None = None
    note: str = ""

    @property
    def measured(self) -> bool:
        return self.value is not None

    @property
    def met(self) -> bool:
        return self.measured and self.points >= 1.0

    @property
    def points(self) -> float:
        v = self.value
        if v is None:
            return 0.0
        if self.kind == "max":
            return 1.0 if v <= self.goal else max(0.0, self.goal / v) if v > 0 else 1.0
        if self.kind == "min":
            return 1.0 if v >= self.goal else max(0.0, v / self.goal)
        return 1.0 if v <= 0 else 1.0 / (1.0 + v)            # zero

    def shown(self) -> str:
        if self.value is None:
            return "not measured"
        if self.unit == "%":
            return f"{self.value:.0f}%"
        if self.unit == "s":
            return f"{self.value:.2f} s"
        return f"{self.value:g}{(' ' + self.unit) if self.unit else ''}"


def measures() -> list[Measure]:
    """The table in plan.md section 2, in order."""
    return [
        Measure("first_word", "First word after you stop (chit-chat), Standard tier", "<= 1.0 s median",
                "max", 1.0, "s", "A2"),
        Measure("first_word_lite", "First word, Lite tier", "<= 2.5 s median", "max", 2.5, "s", "B2"),
        Measure("requests_correct", "Real requests done correctly", ">= 90%", "min", 90, "%", "A1"),
        Measure("dropped", "Requests dropped silently", "0", "zero", 0, "", "A1"),
        Measure("stock", "Stock lines / invented life / written laughter", "0", "zero", 0, "", "A1"),
        Measure("persona_blind", "Blind \"who said this?\" across Red, Remy and Asha", ">= 80%", "min", 80, "%", "A5"),
        Measure("topic_carry", "A new companion continues the old one's topic", "0 times", "zero", 0, "", "A5"),
        Measure("wake_heard", "Wake: \"Hey Red\" and names heard", ">= 95%", "min", 95, "%", "A4"),
        Measure("false_wakes", "False wakes in 1 h of other talk", "<= 1", "max", 1, "", "A4"),
        Measure("on_screen", "Companion on screen after \"Hey Red\"", "<= 1 s", "max", 1.0, "s", "B4"),
        Measure("switch", "Companion switch", "<= 1 s on screen, <= 2 s to talking", "max", 1.0, "s", "B3"),
        Measure("dictation", "Dictation: pasted after you stop (10 s of speech)", "<= 1 s, exactly what was said",
                "max", 1.0, "s", "A6"),
        Measure("hover_sounds", "Sounds on hover", "0", "zero", 0, "", "B3"),
        Measure("size", "Carried vs. on-edge size", "within 10%; hands and feet never cut", "max", 10, "%", "B3"),
        Measure("mishearings", "Mishearings from the user's real clips that still fail", "lower every night",
                "zero", 0, "", "A4"),
        Measure("soak", "Soak: crashes / memory growth over 8 h", "0 / < 10%", "zero", 0, "", "B7"),
        Measure("install", "Clean install -> companion talking", "<= 10 min", "max", 10, "min", "B1"),
    ]


@dataclass
class Score:
    measures: list[Measure]
    when: str = ""
    details: dict = field(default_factory=dict)

    @property
    def total(self) -> float:
        return round(10 * sum(m.points for m in self.measures) / len(self.measures), 1)

    @property
    def of_measured(self) -> float | None:
        done = [m for m in self.measures if m.measured]
        return round(10 * sum(m.points for m in done) / len(done), 1) if done else None

    def get(self, key: str) -> Measure:
        return next(m for m in self.measures if m.key == key)

    def to_dict(self) -> dict:
        return {"when": self.when, "score": self.total, "score_of_measured": self.of_measured,
                "measured": sum(m.measured for m in self.measures), "of": len(self.measures),
                "measures": [asdict(m) | {"points": round(m.points, 3)} for m in self.measures],
                "details": self.details}


def fill_from_replay(score: Score, offline: dict | None, model: dict | None) -> None:
    """Put the replay's numbers (red.replay.summarize) into the measures."""
    if offline:
        m = score.get("dropped")
        m.value = offline["dropped_silently"] + (model or {}).get("model_dropped", 0)
        m.note = (f"{offline['offline_lines']} real lines replayed, an editor in front; "
                  f"\"For me?\" asked on {offline['asked_for_me']}")
    if model:
        if model.get("requests"):
            m = score.get("requests_correct")
            m.value = 100.0 * model["requests_correct"] / model["requests"]
            m.note = f"{model['requests_correct']} of {model['requests']} real requests (replay, real model, tools in dry run)"
        m = score.get("stock")
        m.value = model["stock_lines"]
        m.note = f"in {model['model_lines']} real-model replies"
        if model.get("talk_first_word_median") is not None:
            m = score.get("first_word")
            m.value = model["talk_first_word_median"]
            m.note = (f"median of {model['talk_lines']} talk lines, text mode (from the transcript to the first "
                      "sentence handed to the voice; no Whisper or TTS time)")


def render(score: Score) -> str:
    lines = [f"# Red Score {score.when}", "",
             f"**{score.total} / 10** ({sum(m.measured for m in score.measures)} of {len(score.measures)} "
             f"measures taken; a measure not taken yet counts 0)."]
    if score.of_measured is not None:
        lines.append(f"Over what was measured: {score.of_measured} / 10.")
    lines += ["", "| Measure | v1 target | Now | Points | Notes |", "|---|---|---|---|---|"]
    for m in score.measures:
        note = m.note or (f"comes with {m.part}" if not m.measured else "")
        mark = "met" if m.met else f"{m.points:.2f}"
        lines.append(f"| {m.label} | {m.target} | {m.shown()} | {mark} | {note} |")
    worst = score.details.get("worst") or []
    if worst:
        lines += ["", "## Worst lines", ""]
        for w in worst:
            lines.append(f"- {w['said']!r} (wanted {'/'.join(w['want'])}) -> ran {w['tool']}, "
                         f"said {w['reply'][:120]!r}: {'; '.join(w['failures'] or w['problems'])}")
    return "\n".join(lines) + "\n"


def _persona_blind(port: int, limit: int, out_dir: Path) -> tuple[float | None, str]:
    """scripts/persona_eval.py --suite distinct: the judge's blind guess rate, in %."""
    out = out_dir / "persona.json"
    cmd = [sys.executable, str(ROOT / "scripts" / "persona_eval.py"), "--port", str(port), "--suite", "distinct",
           "--quiet", "--json", str(out)] + (["--limit", str(limit)] if limit else [])
    try:
        subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True, timeout=3600)
        data = json.loads(out.read_text(encoding="utf-8"))
        rate = data["distinct"]["judge"]
        n = sum(1 for r in data["rows"] if "guess" in r)
        return 100.0 * rate, f"the local model guessed who said {n} replies (persona_eval, limit {limit or 'none'})"
    except Exception as e:  # noqa: BLE001 - a failed side measure is "not measured", not a crash
        return None, f"persona_eval failed: {type(e).__name__}"


def run(*, offline_only: bool = False, big: bool = False, persona: bool = False, limit: int | None = None,
        port: int | None = None, home: Path | None = None, idle: float | None = None,
        out_root: Path | None = None, say=print) -> Score:
    from . import replay
    import os
    home = Path(home or os.environ.get("RED_HOME") or r"D:\RED")
    now = datetime.now()
    out_dir = Path(out_root or home / "cache" / "score") / now.strftime("%Y-%m-%d-%H%M")
    out_dir.mkdir(parents=True, exist_ok=True)
    score = Score(measures(), when=now.strftime("%Y-%m-%d %H:%M"))
    lines = replay.load()

    say(f"Replay without a model: {len(lines)} lines...")
    offline = replay.run_offline(lines)
    off_sum = replay.summarize(offline)
    score.details["offline"] = off_sum
    score.details["offline_failures"] = [r.to_dict() for r in offline if not r.ok]
    say(f"  dropped silently {off_sum['dropped_silently']}, \"For me?\" {off_sum['asked_for_me']}, "
        f"failures {off_sum['offline_failures']}")

    model_sum = None
    if not offline_only:
        from .sim import ollama
        if idle is None:
            try:
                from .greeter import idle_seconds
                idle = float(idle_seconds())
            except Exception:  # noqa: BLE001
                idle = 0.0
        away = big or idle >= AWAY_SECONDS
        cap = limit if limit is not None else (None if away else BUSY_LINES)
        if not away and (cap is None or cap > BUSY_LINES):
            cap = BUSY_LINES
        try:
            llm = ollama.client(port)
        except RuntimeError as e:
            llm = None
            say(f"  no model: {e}")
        if llm is not None:
            picked = lines if cap is None else replay.sample(lines, cap)
            say(f"Replay on the real model: {len(picked)} lines"
                f"{'' if cap is None else f' (the user is at the PC: at most {BUSY_LINES})'}...")
            try:
                from .chat import CHAT_SCHEMA
                llm.complete_json("Reply with one short word.", "hi", CHAT_SCHEMA, temperature=0.0, max_tokens=6)
            except Exception as e:  # noqa: BLE001
                say(f"  (warm-up failed: {e})")
            start = time.perf_counter()

            def note(r):
                mark = "ok " if not r.problems else "BAD"
                say(f"  {mark} {r.first_word:5.2f}s {r.line.said[:60]!r} -> {r.tool}"
                    f"{'' if not r.problems else '  ' + '; '.join(r.problems)}")
            model = replay.run_model(picked, llm, real_home=home, on_result=note)
            model_sum = replay.summarize(model=model)
            model_sum["seconds"] = round(time.perf_counter() - start, 1)
            score.details["model"] = model_sum
            score.details["model_lines"] = [r.to_dict() for r in model]
            bad = sorted((r for r in model if r.problems), key=lambda r: -len(r.problems))
            score.details["worst"] = [r.to_dict() for r in bad[:5]]
            if persona or away:
                port_used = int(llm.base_url.rsplit(":", 1)[-1])
                say("Blind persona test...")
                value, why = _persona_blind(port_used, 0 if away else 4, out_dir)
                m = score.get("persona_blind")
                m.value, m.note = value, why
    fill_from_replay(score, off_sum, model_sum)
    (out_dir / "score.json").write_text(json.dumps(score.to_dict(), indent=1, ensure_ascii=False), encoding="utf-8")
    (out_dir / "score.md").write_text(render(score), encoding="utf-8")
    score.details["out_dir"] = str(out_dir)
    return score


def main(argv: list[str] | None = None) -> int:
    import argparse
    p = argparse.ArgumentParser(prog="python -m red score")
    p.add_argument("--offline", action="store_true", help="no model: only the replay's gate checks")
    p.add_argument("--big", action="store_true", help="every line on the model (the user is away)")
    p.add_argument("--persona", action="store_true", help="also the blind persona test")
    p.add_argument("--limit", type=int, default=None, help="at most this many real-model lines")
    p.add_argument("--port", type=int, default=None, help="Red's Ollama port (found automatically)")
    args = p.parse_args(argv)
    score = run(offline_only=args.offline, big=args.big, persona=args.persona, limit=args.limit, port=args.port)
    print()
    print(render(score))
    print(f"Saved in {score.details['out_dir']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
