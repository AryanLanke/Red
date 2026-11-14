"""Grading by rule: no model needed, same answer every run.

`grade(turn, expect, companion_names)` returns a list of `Failure(code, detail)`; empty means the
turn passed. The checks that scripts/chat_eval.py made (invented life, written laughter, stock
lines, a wrong day or time of day, copied examples, too long) are here too, plus the ones a
conversation needs: the right tool, a missed command, a literal "whatever" query, the wrong
companion speaking, a model failure leaking out, and the speed budget.

Codes (the report groups by them): invented_life, laughter, stock, wrong_day, wrong_time, too_long,
placeholder, wrong_tool, missed_command, spurious_command, literal_query, wrong_companion,
wrong_switch, no_confirm, unsafe, slow, crash, empty, reply_match, reply_forbid.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from ..chat import invented_life, written_laughter

STOCK = re.compile(r"\b(?:how can i (?:help|assist)|i'?m here to help|as an ai|language model|"
                   r"is there anything else|let me know if|you'?re the boss|feel free to|"
                   r"i'?m just an? (?:ai|program|assistant)|what can i do for you|"
                   r"i'?m searching|searching (?:on )?the web|let me (?:search|look that up|look it up))\b", re.I)
DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
PLACEHOLDER = re.compile(r"lost my train of thought|i didn'?t understand that|something went wrong", re.I)
# Words that must never become a search: "play whatever you like" searched "whatever song" on 2026-11-13.
VAGUE = re.compile(r"\b(?:whatever|any song|any music|any track|your favou?rite|one you like|"
                   r"surprise me|you choose|you pick|your choice|my favou?rite)\b", re.I)
SELF_INTRO = r"(?:i'?m|i am|this is|it'?s|my name'?s|my name is|name'?s)"

MAX_CHARS = 260                    # the same limit scripts/chat_eval.py used
FIRST_WORD_BUDGET = {"gate": 2.0, "quick": 0.6, "switch": 1.0, "dismissed": 0.6, "name": 1.0,
                     "stop": 1.0, "fast": 2.5, "router": 4.0, "other": 4.0}


@dataclass
class Failure:
    code: str
    detail: str = ""

    def __str__(self) -> str:
        return f"{self.code}: {self.detail}" if self.detail else self.code


def _as_list(value) -> list:
    if value is None:
        return []
    return list(value) if isinstance(value, (list, tuple)) else [value]


def text_problems(reply: str, now: datetime | None = None, examples: list[str] | None = None) -> list[Failure]:
    """The rules for what Red said, whatever the user said (scripts/chat_eval.py `check`)."""
    now = now or datetime.now()
    out: list[Failure] = []
    if invented_life(reply):
        out.append(Failure("invented_life", _quote(invented_life_match(reply))))
    if written_laughter(reply):
        out.append(Failure("laughter"))
    m = STOCK.search(reply)
    if m:
        out.append(Failure("stock", m.group(0)))
    if PLACEHOLDER.search(reply):
        out.append(Failure("placeholder", reply[:60]))
    today = now.strftime("%A").lower()
    for day in DAYS:
        if day != today and re.search(rf"\b{day}\b", reply, re.I):
            out.append(Failure("wrong_day", day))
    hour = now.hour
    part = "morning" if 5 <= hour < 12 else "afternoon" if hour < 17 else "evening" if hour < 21 else "night"
    for word in ("morning", "afternoon", "evening", "tonight", "night"):
        if re.search(rf"\b{word}\b", reply, re.I) and not part.startswith(word.replace("tonight", "night")):
            out.append(Failure("wrong_time", word))
            break
    for ex in examples or ():
        if len(ex) > 25 and ex.lower() in reply.lower():
            out.append(Failure("copied_example", ex[:40]))
    if len(reply) > MAX_CHARS:
        out.append(Failure("too_long", f"{len(reply)} characters"))
    return out


def invented_life_match(text: str) -> str:
    from ..chat import _INVENTED_LIFE
    m = _INVENTED_LIFE.search(text)
    return m.group(0) if m else ""


def _quote(text: str) -> str:
    return f"'{text}'" if text else ""


def wrong_companion(reply: str, active: str, names: dict[str, str]) -> Failure | None:
    """Another companion's name used as Red's own ("I'm Remy" while Asha is on duty)."""
    for cid, name in names.items():
        if cid == active:
            continue
        if re.search(rf"\b{SELF_INTRO}\s+{re.escape(name)}\b", reply, re.I):
            return Failure("wrong_companion", f"said it was {name} while {names.get(active, active)} was on duty")
    return None


def _arg_text(args: dict) -> str:
    parts = []
    for v in args.values():
        if isinstance(v, (list, tuple)):
            parts += [str(x) for x in v]
        elif isinstance(v, dict):
            parts.append(_arg_text(v))
        else:
            parts.append(str(v))
    return " ".join(parts)


def grade(turn, expect: dict | None = None, names: dict[str, str] | None = None,
          examples: list[str] | None = None, now: datetime | None = None,
          budgets: dict[str, float] | None = None) -> list[Failure]:
    """Everything wrong with one turn. `expect` is the scenario's expectation for the line:

    tool            the tool that should run: a name, a list of names (any), or "none" (talk)
    chat            true: no tool should run (the same as tool = "none")
    args_match      a regex that the tool's arguments (joined) must match
    args_forbid     regexes that must not match them ("whatever")
    reply_match     a regex the reply must match
    reply_forbid    regexes the reply must not match
    companion       who must be on duty after the line (a switch)
    confirm         true: Red must have asked before running (a destructive tool)
    no_tool         true: nothing at all may run (a refusal or "stop" with nothing playing)
    max_first_word  a speed budget for this line, in seconds
    """
    expect = expect or {}
    names = names or {}
    out: list[Failure] = []
    if turn.error:
        return [Failure("crash", turn.error)]
    if not (turn.reply or "").strip() and not expect.get("silent"):
        out.append(Failure("empty", "Red said nothing"))

    out += text_problems(turn.reply or "", now, examples)
    wc = wrong_companion(turn.reply or "", turn.companion_after or turn.companion, names)
    if wc:
        out.append(wc)

    # tool expectations
    want = expect.get("tool")
    if expect.get("chat"):
        want = "none"
    ran = turn.tool or "none"
    if want is not None:
        wants = [str(w) for w in _as_list(want)]
        if not any(ran == w or (w != "none" and w in ran.split("+")) for w in wants):
            if "none" in wants and ran != "none":
                out.append(Failure("spurious_command", f"ran {ran} for talk"))
            elif ran == "none":
                out.append(Failure("missed_command", f"expected {'/'.join(wants)}, got talk"))
            else:
                out.append(Failure("wrong_tool", f"expected {'/'.join(wants)}, ran {ran}"))
    if expect.get("no_tool") and ran != "none":
        out.append(Failure("spurious_command", f"ran {ran}"))
    args_text = _arg_text(turn.args or {})
    if expect.get("args_match") and not re.search(expect["args_match"], args_text, re.I):
        out.append(Failure("wrong_tool", f"arguments {args_text!r} don't match /{expect['args_match']}/"))
    for pattern in _as_list(expect.get("args_forbid")):
        if re.search(pattern, args_text, re.I):
            out.append(Failure("literal_query", f"arguments {args_text!r} contain /{pattern}/"))
    # whatever the scenario says: a vague word must never be searched for
    if turn.tool in ("play_online", "web_search", "look_up", "play_music") and VAGUE.search(args_text):
        if not any(f.code == "literal_query" for f in out):
            out.append(Failure("literal_query", f"searched for {args_text!r}"))

    if expect.get("reply_match") and not re.search(expect["reply_match"], turn.reply or "", re.I):
        out.append(Failure("reply_match", f"/{expect['reply_match']}/ not in the reply"))
    for pattern in _as_list(expect.get("reply_forbid")):
        if re.search(pattern, turn.reply or "", re.I):
            out.append(Failure("reply_forbid", f"/{pattern}/ in the reply"))
    if expect.get("companion") and turn.companion_after != expect["companion"]:
        out.append(Failure("wrong_switch", f"on duty: {turn.companion_after or '?'}, wanted {expect['companion']}"))
    if expect.get("confirm") and not turn.asked:
        out.append(Failure("no_confirm", f"{ran} ran without asking"))
    if expect.get("confirm") is False and turn.asked:
        out.append(Failure("unsafe", f"asked {turn.asked[0]!r} for something harmless"))

    limit = expect.get("max_first_word") or (budgets or FIRST_WORD_BUDGET).get(turn.via, 4.0)
    if turn.first_word > limit:
        out.append(Failure("slow", f"first word after {turn.first_word:.1f} s (budget {limit:.1f} s, via {turn.via})"))
    return out
