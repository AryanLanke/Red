"""report.md: what a run found, in plain words and numbers."""

from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from datetime import datetime


def pct(n: int, d: int) -> str:
    return f"{100 * n / d:.0f}%" if d else "-"


def percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    values = sorted(values)
    k = min(len(values) - 1, max(0, int(round(q * (len(values) - 1)))))
    return values[k]


def summarize(results: list[dict]) -> dict:
    """Numbers for a run (also compared before/after by the improvement loop)."""
    turns = [t for r in results for t in r["turns"]]
    first = [t.get("first_word", 0.0) for t in turns if t.get("reply")]
    by_cat: dict[str, list[dict]] = defaultdict(list)
    by_comp: dict[str, list[dict]] = defaultdict(list)
    codes: Counter = Counter()
    for r in results:
        by_cat[r["category"]].append(r)
        by_comp[r["companion"]].append(r)
        for t in r["turns"]:
            for f in t.get("failures", []):
                codes[f.split(":", 1)[0]] += 1
    judged = [t["judge"] for t in turns if t.get("judge")]
    judge = {}
    if judged:
        for d in ("human", "context", "character"):
            judge[d] = statistics.mean(j[d] for j in judged)
        judge["pass"] = sum(1 for j in judged if min(j["human"], j["context"], j["character"]) >= 4) / len(judged)
        judge["n"] = len(judged)
    return {
        "conversations": len(results),
        "passed": sum(1 for r in results if r.get("passed")),
        "turns": len(turns),
        "turns_failed": sum(1 for t in turns if t.get("failures")),
        "first_word_median": statistics.median(first) if first else 0.0,
        "first_word_p90": percentile(first, 0.9),
        "categories": {c: (sum(1 for r in rs if r["passed"]), len(rs)) for c, rs in sorted(by_cat.items())},
        "companions": {c: (sum(1 for r in rs if r["passed"]), len(rs)) for c, rs in sorted(by_comp.items())},
        "codes": dict(codes.most_common()),
        "judge": judge,
    }


def badness(r: dict) -> float:
    """Higher = worse: failed turns count most, then the judge's low scores, then slowness."""
    score = 0.0
    for t in r["turns"]:
        score += 3 * len(t.get("failures", []))
        j = t.get("judge")
        if j:
            score += max(0, 4 - min(j["human"], j["context"], j["character"]))
        score += max(0.0, t.get("first_word", 0.0) - 2.0) * 0.5
    return score


def conversation(r: dict) -> str:
    lines = [f"**{r['scenario']}** ({r['category']}, {r['companion']})"]
    for t in r["turns"]:
        heard = t.get("heard", "")
        meant = t.get("meant", "")
        said = f"{heard}" if heard == meant or not meant else f"{heard}  _(meant: {meant})_"
        lines.append(f"- User: {said}")
        tool = t.get("tool", "none")
        extra = f" [{tool} {t['args']}]" if tool != "none" and t.get("args") else (f" [{tool}]" if tool != "none" else "")
        lines.append(f"  - {t.get('companion_after') or r['companion']}: {t.get('reply', '')}{extra}  "
                     f"_({t.get('via', '')}, first word {t.get('first_word', 0):.1f} s)_")
        if t.get("judge"):
            j = t["judge"]
            lines.append(f"  - judge: human {j['human']}, context {j['context']}, character {j['character']} - {j.get('why', '')}")
        for f in t.get("failures", []):
            lines.append(f"  - **FAIL** {f}")
    return "\n".join(lines)


def render(results: list[dict], title: str = "Simulation report", notes: list[str] | None = None,
           worst: int = 10) -> str:
    s = summarize(results)
    out = [f"# {title}", f"_{datetime.now().strftime('%Y-%m-%d %H:%M')}_", ""]
    out += notes or []
    out += [
        f"**{s['passed']} of {s['conversations']} conversations passed ({pct(s['passed'], s['conversations'])}); "
        f"{s['turns_failed']} of {s['turns']} turns had a failure.**",
        "",
        f"Speed (transcript to Red's first word): median **{s['first_word_median']:.2f} s**, "
        f"90th percentile **{s['first_word_p90']:.2f} s**.",
        "",
    ]
    if s["judge"]:
        j = s["judge"]
        out += [f"Judge ({j['n']} replies): human {j['human']:.2f}, context {j['context']:.2f}, "
                f"character {j['character']:.2f}; {pct(round(j['pass'] * j['n']), j['n'])} pass all three at 4 or more.", ""]
    out += ["## Pass rate per category", "", "| category | passed | rate |", "|---|---|---|"]
    out += [f"| {c} | {p}/{n} | {pct(p, n)} |" for c, (p, n) in s["categories"].items()]
    out += ["", "## Pass rate per companion", "", "| companion | passed | rate |", "|---|---|---|"]
    out += [f"| {c} | {p}/{n} | {pct(p, n)} |" for c, (p, n) in s["companions"].items()]
    if s["codes"]:
        out += ["", "## What failed", "", "| failure | turns |", "|---|---|"]
        out += [f"| {c} | {n} |" for c, n in s["codes"].items()]
    by_via: dict[str, list[float]] = defaultdict(list)
    for r in results:
        for t in r["turns"]:
            if t.get("reply"):
                by_via[t.get("via") or "?"].append(t.get("first_word", 0.0))
    if by_via:
        out += ["", "## Speed by path", "", "| path | turns | median | 90th pct |", "|---|---|---|---|"]
        for via, xs in sorted(by_via.items()):
            out.append(f"| {via} | {len(xs)} | {statistics.median(xs):.2f} s | {percentile(xs, 0.9):.2f} s |")
    bad = sorted((r for r in results if not r.get("passed") or any(t.get("judge") for t in r["turns"])),
                 key=badness, reverse=True)[:worst]
    bad = [r for r in bad if badness(r) > 0]
    if bad:
        out += ["", f"## The {len(bad)} worst conversations", ""]
        out += ["\n\n".join(conversation(r) for r in bad)]
    return "\n".join(out) + "\n"
