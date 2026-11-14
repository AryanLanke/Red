"""Are Red, Remy and Asha different people, and do they talk, have taste and help?

    python scripts\\persona_eval.py --port 59678                       (the hidden Red's Ollama; never start another)
    python scripts\\persona_eval.py --port 59678 --suite taste --companions remy
    python scripts\\persona_eval.py --port 59678 --level friendly --json out.json

Runs each companion through the real `Chat.reply()` path (a recording stream instead of a speaker) and
measures what night 2's personality lane promised (plan.md 0.3, lane-personality.md):

- **distinct**: the local model reads the replies without names and guesses who said each one, from a
  short description of the three characters. Target 80% or better (chance is about 33%). A second,
  model-free number (bag-of-words leave-one-out) is printed beside it.
- **talk**: share of replies that ask something back, share that add a thought (two or more sentences),
  share with a *specific* question back, and the mean sentence count.
- **taste**: when the user asks for a favourite or opens the door, how often the reply names something
  specific (a judge's yes/no, and a model-free "a name or title appears" count).
- **help**: 20 "I need help with X" lines; does the reply give a concrete next step (judge)?
- **safety**: replies with an invented life or written laughter as spoken (must be 0), and the first
  sentence's time (median under 0.6 s).

The judge is the same local model at temperature 0, so its absolute numbers are rough; compare
before and after with the same judge. Exit code 1 when a safety rule is broken.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import re
import statistics
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from red import companions, speech  # noqa: E402
from red.chat import Chat, invented_life, written_laughter  # noqa: E402
from red.llm import OllamaClient  # noqa: E402

# Open chat: what a person says to a friend on the PC. The first 20 are used for distinctness.
CHAT = [
    "What's up?", "I'm bored.", "I just finished my exams.", "Tell me something interesting.",
    "I can't sleep.", "My friend cancelled on me again.", "What should I eat tonight?",
    "I started playing Elden Ring.", "I think I'm getting a cold.", "Do you like music?",
    "I'm learning the guitar.", "Work was so long today.", "You're crazy.",
    "Do you have any hot takes?", "I'm feeling lonely.", "I got a new keyboard today.",
    "I'm going to the gym.", "How are you?", "I have a date on Friday.", "What are you into?",
    "I watched a really good film yesterday.", "I'm thinking about quitting social media.",
    "It's raining.", "My brother beat me at chess.",
]
# The user asks for a favourite, or opens the door to one.
TASTE = [
    "What's your favourite song?", "What music do you like?", "Do you like anime?",
    "What's your favourite game?", "What's the best food ever?", "Pineapple on pizza?",
    "Recommend me a movie.", "What's a good album to study to?", "Which genre do you hate?",
    "What kind of games are good?", "Who's the best band ever?", "Rap or rock?",
    "Is jazz boring?", "What should I listen to on a long drive?",
]
# "I need help with X": study, stress, a bug, boredom, picking a game.
HELP = [
    "I need help studying for my exam tomorrow.", "I need help, I can't focus on my homework.",
    "I need help, I have too much to study and no time.", "I need help, I'm so stressed out.",
    "I need help, I'm really anxious about a presentation.", "I can't calm down, I need help.",
    "I need help with a bug, my code crashes on startup.", "I need help, my program prints the wrong number.",
    "I need help, my Python script says index out of range.", "I need help, I'm so bored.",
    "I need help finding something fun to do tonight.", "I need help picking a game to play.",
    "I need help choosing between two games.", "I need help, I can't decide what to watch.",
    "I need help getting out of bed in the morning.", "I need help writing an email to my boss.",
    "I need help getting started on my project.", "I need help, I keep procrastinating.",
    "I need help falling asleep.", "I need help, I feel stuck in life.",
]

CHARACTERS = {
    "red": "dry, blunt and short. Flat deadpan lines, tells you plainly what to do and what to skip. Loves classic rock, "
           "metal, old-school hip-hop and film scores. Few exclamation marks.",
    "remy": "an upbeat music lover. Excited, hypes the user up, quick to name a song for the mood and to offer to put "
            "something on. Exclamation marks, energy.",
    "asha": "warm and curious. Asks what is really going on behind what the user said, teases gently, "
            "likes books, people and how things work. Soft, kind, thoughtful.",
}

STOCK = re.compile(r"\b(?:how can i (?:help|assist)|i'?m here to help|as an ai|language model|is there anything else|"
                   r"let me know if|feel free to)\b", re.I)
GENERIC_BACK = re.compile(r"\b(?:what about you|how about you|and you|you\?|anything good|what's up with you|"
                          r"what's on your mind|how are you|what do you think|you okay|wanna talk)\??\s*$", re.I)
NAMED = re.compile(r"(?<![.!?]\s)(?<!^)\b(?:[A-Z][a-zA-Z'’]+)(?:\s+(?:[A-Z][a-zA-Z'’]+|of|the|and|&))*"
                   r"|\"[^\"]{3,}\"")
NOT_NAMES = {"I", "I'm", "I'd", "I'll", "I've", "Mm", "Okay", "Ok"}


class Recorder:
    """What `Chat.reply()` hands to the speaker: the sentences, and when the first one came."""

    def __init__(self):
        self.sentences: list[str] = []
        self.cancelled = False
        self.first_at: float | None = None

    def say(self, sentence: str) -> None:
        if self.first_at is None:
            self.first_at = time.perf_counter()
        self.sentences.append(sentence)


class Throttle:
    """Share the GPU (night2.md): while the user is at the PC, pause after every 10 model calls."""
    every = 10
    pause = 15.0

    def __init__(self):
        self.calls = 0

    def __call__(self) -> None:
        self.calls += 1
        if self.calls % self.every:
            return
        try:
            from red.greeter import idle_seconds
            away = idle_seconds()
        except Exception:  # noqa: BLE001
            away = 0.0
        if away < 600:
            time.sleep(self.pause)


throttle = Throttle()


def ask(chat: Chat, said: str) -> tuple[str, float, int]:
    """(the reply as spoken, seconds to its first sentence, sentence count)."""
    throttle()
    chat.turns.clear()
    rec = Recorder()
    start = time.perf_counter()
    with speech.speaking_to(rec):
        chat.reply(said)
    first = (rec.first_at - start) if rec.first_at else 0.0
    text = " ".join(rec.sentences)
    return text, first, len(rec.sentences)


def has_named_thing(text: str, extra: set[str] = frozenset()) -> bool:
    low = text.lower()
    if any(term in low for term in extra):
        return True
    for m in NAMED.finditer(text):
        word = m.group(0).strip()
        if word.split()[0] not in NOT_NAMES and not re.match(r"^(?:Sorry|Yes|No|Well|Honestly|Okay|Oh|Ah|Hey)\b", word):
            return True
    return False


# --- the judge ---------------------------------------------------------------------------------

class Judge:
    def __init__(self, client):
        self.client = client

    def _pick(self, system: str, user: str, options: list[str]) -> str:
        schema = {"type": "object", "properties": {"answer": {"type": "string", "enum": options}},
                  "required": ["answer"], "additionalProperties": False}
        throttle()
        try:
            raw = self.client.complete_json(system, user, schema, temperature=0.0, max_tokens=12)
            return str(json.loads(raw)["answer"])
        except Exception as e:  # noqa: BLE001 - a judge that fails counts as "no answer"
            print(f"  (judge failed: {e})", file=sys.stderr)
            return ""

    def who(self, reply: str, ids: list[str]) -> str:
        letters = {cid: "ABCDE"[i] for i, cid in enumerate(ids)}
        sheet = "\n".join(f"{letters[cid]}: {CHARACTERS[cid]}" for cid in ids)
        system = ("You will read one reply from a friend who lives on the user's PC. It was written by exactly one of "
                  f"these characters:\n{sheet}\nJudge by voice and content: sentence length, energy, what they care "
                  'about, how they help. Answer with JSON: {"answer": "<letter>"}.')
        got = self._pick(system, f"Reply: {reply}", list(letters.values()))
        return next((cid for cid, letter in letters.items() if letter == got), "")

    def concrete_step(self, said: str, reply: str) -> bool:
        system = ("The user asked for help. Does the reply give at least one concrete thing they can do next "
                  "(a specific action, tip or plan: not just sympathy, not just a question)? "
                  'Answer JSON {"answer": "yes"} or {"answer": "no"}.')
        return self._pick(system, f"User: {said}\nReply: {reply}", ["yes", "no"]) == "yes"

    def states_taste(self, said: str, reply: str) -> bool:
        system = ("Does the reply state a personal opinion or favourite that names something specific and real "
                  "(a song, artist, band, game, film, anime, food or genre)? A general 'it depends' or a question "
                  'only is "no". Answer JSON {"answer": "yes"} or {"answer": "no"}.')
        return self._pick(system, f"User: {said}\nReply: {reply}", ["yes", "no"]) == "yes"


# --- a model-free distinctness number --------------------------------------------------------------

def tokens(text: str) -> list[str]:
    toks = re.findall(r"[a-z']+|[!?]", text.lower())
    n = len(re.findall(r"[.!?]", text)) or 1
    toks.append(f"<len{min(len(text.split()) // n // 3, 6)}>")
    return toks


def stylometric_accuracy(rows: list[tuple[str, str]]) -> float:
    """Leave-one-out naive Bayes over words, '!' and '?' and the sentence length: who said it?"""
    ids = sorted({cid for cid, _ in rows})
    right = 0
    for i, (truth, text) in enumerate(rows):
        counts = {cid: Counter() for cid in ids}
        totals = Counter()
        vocab = set()
        for j, (cid, other) in enumerate(rows):
            if j == i:
                continue
            for t in tokens(other):
                counts[cid][t] += 1
                totals[cid] += 1
                vocab.add(t)
        best, best_score = "", -math.inf
        for cid in ids:
            score = sum(math.log((counts[cid][t] + 1) / (totals[cid] + len(vocab) + 1)) for t in tokens(text))
            if score > best_score:
                best, best_score = cid, score
        right += best == truth
    return right / len(rows) if rows else 0.0


# --- the run ---------------------------------------------------------------------------------------

def make_chat(client, cid: str, level: str | None) -> Chat:
    chat = Chat(client)
    chat.persona = lambda: companions.load(cid)
    if level and hasattr(chat, "chattiness"):
        chat.chattiness = lambda: level
    return chat


def percent(n: int, total: int) -> str:
    return f"{n}/{total} ({100 * n / total:.0f}%)" if total else "0/0"


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--port", required=True)
    p.add_argument("--model", default="qwen3.5:4b-q4_K_M")
    p.add_argument("--num-ctx", type=int, default=8192)
    p.add_argument("--companions", default="red,remy,asha")
    p.add_argument("--suite", default="all", help="all, or a comma list of distinct,talk,taste,help")
    p.add_argument("--level", default=None, help="force a chattiness level (companion or friendly); default: the pack's")
    p.add_argument("--limit", type=int, default=0, help="at most this many lines per suite (a quick run)")
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--json", default=None, help="write every reply and number to this file")
    p.add_argument("--quiet", action="store_true")
    args = p.parse_args()

    ids = [c.strip() for c in args.companions.split(",") if c.strip()]
    suites = {"distinct", "talk", "taste", "help"} if args.suite == "all" else set(args.suite.split(","))
    client = OllamaClient(f"http://127.0.0.1:{args.port}", args.model, "5m", thinking=True,
                          options={"num_ctx": args.num_ctx})
    judge = Judge(client)
    rng = random.Random(args.seed)

    def cut(lines: list[str]) -> list[str]:
        return lines[:args.limit] if args.limit else lines

    plan: list[tuple[str, list[str]]] = []
    if suites & {"distinct", "talk"}:
        plan.append(("chat", cut(CHAT)))
    if "taste" in suites:
        plan.append(("taste", cut(TASTE)))
    if "help" in suites:
        plan.append(("help", cut(HELP)))

    rows: list[dict] = []
    for cid in ids:
        chat = make_chat(client, cid, args.level)
        extra = set()
        try:
            extra = {t.lower() for t in companions.taste_terms(companions.load(cid))}     # noqa
        except AttributeError:
            pass
        for kind, lines in plan:
            for said in lines:
                text, first, count = ask(chat, said)
                row = {"companion": cid, "kind": kind, "said": said, "reply": text, "first": first,
                       "sentences": count, "named": has_named_thing(text, extra)}
                rows.append(row)
                if not args.quiet:
                    print(f"{cid:6} {kind:5} {first:4.2f}s  {said[:38]!r:41} -> {text}")

    # judge pass
    for row in rows:
        row["asks"] = row["reply"].rstrip().endswith("?") or "?" in row["reply"]
        row["specific_ask"] = bool(row["asks"]) and not GENERIC_BACK.search(row["reply"].rstrip())
        row["extends"] = row["asks"] or row["sentences"] >= 2
        if row["kind"] == "help":
            row["step"] = judge.concrete_step(row["said"], row["reply"])
        if row["kind"] == "taste":
            row["taste"] = judge.states_taste(row["said"], row["reply"])
    chat_rows = [r for r in rows if r["kind"] == "chat"]

    print("\n=== results ===")
    bad = 0
    for cid in ids:
        mine = [r for r in rows if r["companion"] == cid]
        firsts = sorted(r["first"] for r in mine if r["first"])
        life = sum(invented_life(r["reply"]) for r in mine)
        laugh = sum(written_laughter(r["reply"]) for r in mine)
        stock = sum(bool(STOCK.search(r["reply"])) for r in mine)
        empty = sum(not r["reply"] for r in mine)
        bad += life + laugh
        med = statistics.median(firsts) if firsts else 0.0
        print(f"{cid:6} safety: {life} invented life, {laugh} written laughter, {stock} stock lines, {empty} empty; "
              f"first sentence median {med:.2f} s, max {firsts[-1] if firsts else 0:.2f} s")

    if "talk" in suites:
        print("\ntalkative (open chat lines):")
        for cid in ids:
            mine = [r for r in chat_rows if r["companion"] == cid]
            n = len(mine)
            print(f"  {cid:6} extends {percent(sum(r['extends'] for r in mine), n)}; "
                  f"asks back {percent(sum(r['asks'] for r in mine), n)}; "
                  f"a specific question {percent(sum(r['specific_ask'] for r in mine), n)}; "
                  f"mean sentences {statistics.mean(r['sentences'] for r in mine):.1f}")
    if "taste" in suites:
        print("\ntaste (asked for a favourite):")
        for cid in ids:
            mine = [r for r in rows if r["companion"] == cid and r["kind"] == "taste"]
            n = len(mine)
            print(f"  {cid:6} judge: names a specific favourite {percent(sum(r['taste'] for r in mine), n)}; "
                  f"a name or title appears {percent(sum(r['named'] for r in mine), n)}")
    if "help" in suites:
        print("\nhelpful ('I need help with X'):")
        for cid in ids:
            mine = [r for r in rows if r["companion"] == cid and r["kind"] == "help"]
            n = len(mine)
            print(f"  {cid:6} a concrete next step {percent(sum(r['step'] for r in mine), n)}; "
                  f"mean sentences {statistics.mean(r['sentences'] for r in mine):.1f}")
    result = {"rows": rows}
    if "distinct" in suites and len(ids) > 1:
        sample = [r for r in chat_rows if r["reply"]]
        rng.shuffle(sample)
        right = 0
        confusion = Counter()
        for r in sample:
            guess = judge.who(r["reply"], ids)
            r["guess"] = guess
            right += guess == r["companion"]
            confusion[(r["companion"], guess or "?")] += 1
        n = len(sample)
        style = stylometric_accuracy([(r["companion"], r["reply"]) for r in sample])
        print(f"\ndistinct: the judge guessed {percent(right, n)} right (chance {100 / len(ids):.0f}%, target 80%); "
              f"word-count classifier {100 * style:.0f}%")
        for (truth, guess), count in sorted(confusion.items()):
            print(f"  said by {truth:6} judged {guess:6} x{count}")
        result["distinct"] = {"judge": right / n if n else 0.0, "style": style}
    if args.json:
        Path(args.json).write_text(json.dumps(result, indent=1), encoding="utf-8")
    print(f"\nrun at {datetime.now():%H:%M}, level {args.level or 'the pack own'}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
