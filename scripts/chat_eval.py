"""Does Red sound like a person? Runs the user's own sentences through Chat on the real model.

    python scripts\\chat_eval.py --port 62277              (the hidden Red's Ollama; never start a second one)
    python scripts\\chat_eval.py --port 62277 --companion remy --repeat 2

Checks every reply for: invented life ("waiting by my terminal", "the clock", "lunch",
"music playing"), written laughter ("haha", "*laughs*"), stock assistant lines, a
weekday other than today's, lines copied from the prompt's examples, and length.
Prints each reply with its first-sentence time, then the counts. Exit code 1 when any
reply breaks a rule, so it can gate a change.
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from red import emotion, speech  # noqa: E402
from red.chat import CHAT_SCHEMA, CHAT_TEMPERATURE, Chat, human, invented_life, written_laughter  # noqa: E402
from red.llm import OllamaClient  # noqa: E402

# The user's own words (logs/commands.jsonl, 2026-11-09 to 13), plus a few everyday ones.
SENTENCES = [
    "What's up?", "What is going on in your mind right now?", "What are you doing right now?",
    "Don't sleep, OK?", "You're crazy.", "You're a nerd.", "I'm feeling lonely.",
    "Are you listening to me?", "How are you?", "It's good, what about you?",
    "True, I love retro gadgets", "I already woke up man", "Man, I just wanna sleep.",
    "You really make me angry.", "I don't like the way you talk",
    "I'm sorry for what I said earlier, honestly. I just want you to be with me. Will you be with me?",
    "Because I don't feel sleepy, I wanna do work. What about you?",
    "I really feel like to laugh and just laugh with me.", "Are you chilling right now?",
    "I'm not talking to you.",
]

STOCK = re.compile(r"\b(?:how can i (?:help|assist)|i'?m here to help|as an ai|language model|"
                   r"is there anything else|let me know if|you'?re the boss|feel free to)\b", re.I)
DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


def check(reply: str, examples: list[str], today: str) -> list[str]:
    problems = []
    if invented_life(reply):
        problems.append("invented life")
    if written_laughter(reply):
        problems.append("written laughter")
    if STOCK.search(reply):
        problems.append("stock line")
    for day in DAYS:
        if day != today and re.search(rf"\b{day}\b", reply, re.I):
            problems.append(f"wrong day ({day})")
    hour = datetime.now().hour
    part = ("morning" if 5 <= hour < 12 else "afternoon" if hour < 17 else "evening" if hour < 21 else "night")
    for word in ("morning", "afternoon", "evening", "tonight", "night"):
        if re.search(rf"\b{word}\b", reply, re.I) and not part.startswith(word.replace("tonight", "night")):
            problems.append(f"wrong time of day ({word})")
            break
    for ex in examples:
        if len(ex) > 25 and ex.lower() in reply.lower():
            problems.append("copied example")
    if len(reply) > 260:
        problems.append("too long")
    return problems


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--port", required=True)
    p.add_argument("--model", default="qwen3.5:4b-q4_K_M")
    p.add_argument("--num-ctx", type=int, default=8192, help="the size the hidden Red uses (no reload)")
    p.add_argument("--companion", default=None, help="a companion id (red/companions.py); default Red")
    p.add_argument("--repeat", type=int, default=1)
    args = p.parse_args()

    client = OllamaClient(f"http://127.0.0.1:{args.port}", args.model, "5m", thinking=True,
                          options={"num_ctx": args.num_ctx})
    chat = Chat(client)
    if args.companion:
        from red import companions
        chat.persona = lambda: companions.load(args.companion)
    system = chat.system()
    examples = [line.split(":", 1)[1].strip() for line in system.splitlines()
                if re.match(r"^\w+: ", line) and not line.startswith(("User:", "A:"))]
    today = datetime.now().strftime("%A").lower()
    bad, raw_bad, firsts = 0, 0, []
    tagged, spoken_tags = 0, 0
    for _ in range(args.repeat):
        for said in SENTENCES:
            chat.turns.clear()
            start = time.perf_counter()
            pieces = speech.stream_field(client, chat.system(), chat.prompt(said), CHAT_SCHEMA, "reply",
                                         temperature=CHAT_TEMPERATURE)
            out, first = [], None
            raw = []
            for sentence in speech.sentences(pieces):
                raw.append(sentence)
                kept = human(sentence)            # what Red actually says (red/chat.py)
                if not kept:
                    continue
                if first is None:
                    first = time.perf_counter() - start
                out.append(kept)
                if len(out) >= 3:
                    break
            reply = " ".join(out)
            tagged += any(emotion.split_tag(s)[1] for s in raw[:1])
            spoken_tags += bool(re.search(r"\[[A-Za-z ]+\]", reply))
            problems = check(reply, examples, today)
            if not reply:
                problems.append("dropped everything")      # Chat would say its stock fallback line
            raw_bad += bool(check(" ".join(raw), examples, today))
            bad += bool(problems)
            firsts.append(first or 0.0)
            mark = "  !! " + ", ".join(problems) if problems else ""
            print(f"{first or 0:5.2f} s  {said[:45]!r:48} -> {reply}{mark}")
    firsts.sort()
    print(f"\n{len(firsts)} replies, {bad} broke a rule as spoken ({raw_bad} as the model wrote them); "
          f"first sentence median {firsts[len(firsts) // 2]:.2f} s, "
          f"max {firsts[-1]:.2f} s")
    print(f"feeling tag on the first sentence: {tagged}/{len(firsts)}; a tag left in the spoken text: {spoken_tags}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
