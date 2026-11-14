"""python -m red.sim <command>   (also: python -m red selftest)

    run         play scenarios on the real model and write D:\\RED\\cache\\sim\\<date>\\report.md
    list        what scenarios there are
    judge-gold  how often the judge agrees with tests/fixtures/sim_gold.jsonl
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GOLD = ROOT / "tests" / "fixtures" / "sim_gold.jsonl"
AWAY_SECONDS = 600           # no input for 10 minutes: the user is away, big batches are fine
BUSY_LIMIT = 10              # conversations at most while the user is at the PC


def _home() -> Path:
    import os
    return Path(os.environ.get("RED_HOME") or r"D:\RED")


def _idle() -> float:
    try:
        from ..greeter import idle_seconds
        return float(idle_seconds())
    except Exception:  # noqa: BLE001 - unknown: assume the user is here
        return 0.0


def _persona_text(cid: str) -> str:
    from .. import companions
    try:
        return companions.load(cid).persona
    except Exception:  # noqa: BLE001
        return ""


def cmd_list(args) -> int:
    from . import scenarios
    found = scenarios.load()
    by_cat: dict[str, int] = {}
    for s in found:
        by_cat[s.category] = by_cat.get(s.category, 0) + 1
    for c, n in sorted(by_cat.items()):
        print(f"{n:4d}  {c}")
    print(f"{len(found)} scenarios, {sum(1 for s in found if s.regress)} in the regression set")
    return 0


def cmd_run(args) -> int:
    from . import ollama, report, runner, scenarios
    from .judge import Judge
    llm = ollama.client(args.port, args.model, args.num_ctx)
    found = scenarios.select(scenarios.load(args.dir), only=args.only, category=args.category,
                             tag=args.tag, regress=args.regress)
    if args.kind:
        found = [s for s in found if s.kind == args.kind]
    if not found:
        print("no scenarios match")
        return 2
    idle = _idle()
    away = idle >= AWAY_SECONDS or args.big
    cap = args.limit or (None if away else BUSY_LIMIT)
    if not away and (args.limit is None or args.limit > BUSY_LIMIT):
        cap = BUSY_LIMIT
        print(f"The user is at the PC (idle {idle:.0f} s): at most {BUSY_LIMIT} conversations. "
              "(Run again after 10 minutes without input, or pass --big.)")
    judge = Judge(llm) if args.judge else None
    out = runner.new_run_dir(Path(args.out) if args.out else _home() / "cache" / "sim", args.label)
    wanted = args.companions.split(",") if args.companions else None
    started = time.time()

    def pause() -> bool:
        return bool(args.minutes and time.time() - started > args.minutes * 60)

    results = runner.run_all(found, llm, companions_filter=wanted, judge=judge, out_dir=out,
                             real_home=_home(), max_pairs=cap, should_pause=pause, seed=args.seed)
    rows = [r.to_dict() for r in results]
    text = report.render(rows, title=f"Simulation report {out.name}", worst=10)
    (out / "report.md").write_text(text, encoding="utf-8")
    s = report.summarize(rows)
    print(f"\n{s['passed']}/{s['conversations']} conversations passed; first word median "
          f"{s['first_word_median']:.2f} s, p90 {s['first_word_p90']:.2f} s; report: {out / 'report.md'}")
    return 0 if s["passed"] == s["conversations"] else 1


def cmd_judge_gold(args) -> int:
    from . import judge as judge_mod
    from . import ollama
    llm = ollama.client(args.port, args.model, args.num_ctx)
    gold = judge_mod.load_gold(GOLD)
    result = judge_mod.agreement(judge_mod.Judge(llm), gold, persona_of=_persona_text)
    for d, s in result["dimensions"].items():
        print(f"{d:10s} agree {s['agree']}/{s['n']} = {s['rate']:.0%}   exact {s['exact']}   within 1: {s['near']}")
    print(f"overall (human pass/fail): {result['overall']:.0%}  ({'usable' if result['overall'] >= 0.8 else 'NOT trusted below 80%'})")
    for m in result["misses"]:
        print(f"  miss: gold {m['gold']} judge {m['judge']} | {m['said']!r} -> {m['reply']!r} | {m['why']}")
    return 0 if result["overall"] >= 0.8 else 1


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m red.sim")
    sub = p.add_subparsers(dest="cmd", required=True)

    def model_args(sp):
        sp.add_argument("--port", type=int, default=None, help="Red's Ollama port (found automatically)")
        sp.add_argument("--model", default="qwen3.5:4b-q4_K_M")
        sp.add_argument("--num-ctx", type=int, default=None, help="default: what the model is loaded with now")

    sp = sub.add_parser("list")
    sp.set_defaults(fn=cmd_list)
    sp = sub.add_parser("run")
    model_args(sp)
    sp.add_argument("--dir", default=None, help="a scenario file or folder (default: red/sim/scenarios)")
    sp.add_argument("--only", default=None, help="scenario ids containing any of these (comma-separated)")
    sp.add_argument("--category", default=None)
    sp.add_argument("--tag", default=None)
    sp.add_argument("--kind", choices=("script", "sim"), default=None)
    sp.add_argument("--regress", action="store_true", help="only the fixed regression set")
    sp.add_argument("--companions", default=None, help="comma-separated ids (default: each scenario's own)")
    sp.add_argument("--judge", action="store_true", help="also grade every reply with the judge")
    sp.add_argument("--limit", type=int, default=None, help="at most this many conversations")
    sp.add_argument("--big", action="store_true", help="the user is away: no cap")
    sp.add_argument("--minutes", type=float, default=None, help="stop starting conversations after this long")
    sp.add_argument("--label", default="")
    sp.add_argument("--out", default=None)
    sp.add_argument("--seed", type=int, default=0)
    sp.set_defaults(fn=cmd_run)
    sp = sub.add_parser("judge-gold")
    model_args(sp)
    sp.set_defaults(fn=cmd_judge_gold)
    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
