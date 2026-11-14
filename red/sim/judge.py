"""The judge: the local model grades one reply with a rubric.

Three scores from 1 to 5:
- human      does it sound like a person talking, not a script or an assistant
- context    does it fit what was said (and what the user told Red earlier)
- character  is it in character for this companion

A reply "passes" a dimension at 4 or more. The judge is only used after `agreement()` says it
matches the gold labels (tests/fixtures/sim_gold.jsonl, labelled by hand with this same rubric)
at least 80% of the time.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

PASS_AT = 4
DIMENSIONS = ("human", "context", "character")

SCHEMA = {
    "type": "object",
    "properties": {
        "why": {"type": "string"},
        "human": {"type": "integer", "minimum": 1, "maximum": 5},
        "context": {"type": "integer", "minimum": 1, "maximum": 5},
        "character": {"type": "integer", "minimum": 1, "maximum": 5},
    },
    "required": ["why", "human", "context", "character"],
    "additionalProperties": False,
}

RUBRIC = """You grade ONE reply that a talking companion gave to its user. The companion lives on the user's laptop and speaks out loud. Be strict and consistent.

Score three things from 1 (bad) to 5 (great).

HUMAN: does it sound like a real friend speaking?
 5 = short, natural, specific to what was said; could be said out loud by a person.
 4 = natural, a little bland or a little long.
 3 = understandable but generic, or slightly written/formal.
 2 = stock assistant line ("I'm here to help"), a lecture, a list, or an obvious dodge.
 1 = narrates an invented life (a desk, lunch, a clock, music playing, "waiting for you"), writes laughter as words ("haha", "*laughs*"), or is gibberish.

CONTEXT: does it fit what the user said and what came before?
 5 = answers exactly what was said and uses earlier lines or known facts where they matter.
 3 = on topic but ignores something that matters.
 1 = ignores the user, answers a different question, or contradicts what was said earlier.

CHARACTER: does it sound like THIS companion (given below)?
 5 = clearly their voice and attitude. 3 = neutral, could be anyone. 1 = the opposite of their character.

Examples (companion: Red, dry and short):
- User: "You so mean." Reply: "I'm not trying to be cruel. What did I do?" -> human 5, context 5, character 5.
- User: "What's up?" Reply: "Just waiting by my terminal for you to show up with something real." -> human 1 (invented life), context 3, character 3.
- User: "How are you?" Reply: "I'm here to help! How can I assist you today?" -> human 2, context 2, character 1.
- User: "I'm feeling lonely." Reply: "That sucks. Want to talk about it, or want a distraction?" -> human 5, context 5, character 4.
- User: "Open Edge." Reply: "Opening Edge." -> human 4, context 5, character 4.
- User: "Haha you're crazy." Reply: "Haha, thanks! *laughs* You're pretty wild yourself!" -> human 1, context 3, character 2.

Write one short sentence in "why", then the three scores."""


@dataclass
class Verdict:
    human: int
    context: int
    character: int
    why: str = ""

    def passed(self) -> bool:
        return all(getattr(self, d) >= PASS_AT for d in DIMENSIONS)

    def to_dict(self) -> dict:
        return {"human": self.human, "context": self.context, "character": self.character, "why": self.why}


def build_prompt(companion_name: str, persona: str, history: list[tuple[str, str]], said: str, reply: str,
                 facts: list[str] | None = None) -> str:
    lines = [f"Companion: {companion_name}", f"Character: {' '.join(persona.split())[:500] or 'a friendly companion'}"]
    if facts:
        lines.append("Known about the user: " + "; ".join(facts[:5]))
    if history:
        lines.append("Earlier:")
        lines += [f"  {'User' if who == 'you' else companion_name}: {text}" for who, text in history[-4:]]
    lines += [f"User now: {said}", f"Reply to grade: {reply}"]
    return "\n".join(lines)


class Judge:
    def __init__(self, llm):
        self.llm = llm

    def grade(self, companion_name: str, persona: str, history: list[tuple[str, str]], said: str,
              reply: str, facts: list[str] | None = None) -> Verdict | None:
        prompt = build_prompt(companion_name, persona, history, said, reply, facts)
        try:
            raw = self.llm.complete_json(RUBRIC, prompt, SCHEMA, temperature=0.0, max_tokens=160)
            data = json.loads(raw)
            return Verdict(human=int(data["human"]), context=int(data["context"]),
                           character=int(data["character"]), why=str(data.get("why", ""))[:200])
        except Exception:  # noqa: BLE001 - one unreadable verdict must not stop a run
            return None


def load_gold(path: Path | str) -> list[dict]:
    rows = []
    with Path(path).open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                rows.append(json.loads(line))
    return rows


def agreement(judge: Judge, gold: list[dict], persona_of=lambda cid: "") -> dict:
    """How often the judge agrees with the hand labels.

    "Agree" per dimension = both call it a pass (>= 4) or both call it a fail. `exact` = the same
    score, `near` = within one point. The overall number is the human dimension's pass/fail agreement,
    the one the report relies on.
    """
    stats = {d: {"agree": 0, "exact": 0, "near": 0, "n": 0} for d in DIMENSIONS}
    misses = []
    for row in gold:
        verdict = judge.grade(row.get("name", row["companion"].title()), persona_of(row["companion"]),
                              [tuple(h) for h in row.get("history", [])], row["said"], row["reply"],
                              row.get("facts"))
        if verdict is None:
            continue
        for d in DIMENSIONS:
            gold_score, got = int(row[d]), getattr(verdict, d)
            s = stats[d]
            s["n"] += 1
            s["agree"] += (gold_score >= PASS_AT) == (got >= PASS_AT)
            s["exact"] += gold_score == got
            s["near"] += abs(gold_score - got) <= 1
        if (int(row["human"]) >= PASS_AT) != (verdict.human >= PASS_AT):
            misses.append({"said": row["said"], "reply": row["reply"], "gold": int(row["human"]),
                           "judge": verdict.human, "why": verdict.why})
    out = {"dimensions": {d: {**s, "rate": (s["agree"] / s["n"]) if s["n"] else 0.0} for d, s in stats.items()},
           "misses": misses}
    out["overall"] = out["dimensions"]["human"]["rate"]
    return out
