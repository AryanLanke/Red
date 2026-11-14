"""The simulated user: the local model plays a person with a mood and a goal.

It writes only the person's next spoken line, from the conversation so far. Scripted scenarios
don't need it; "sim" scenarios start with a fixed opener and let it carry on for 3 to 8 turns.
"""

from __future__ import annotations

import json
import random
import re

SCHEMA = {"type": "object", "properties": {"line": {"type": "string"}}, "required": ["line"],
          "additionalProperties": False}

SYSTEM = """You play a person talking out loud to a companion that lives on their Windows laptop, like a friend on a call. You are the PERSON, never the companion.

Write only what the person says next: one short spoken line (2 to 14 words), plain words as people really talk, no stage directions, no quotes, no emojis.
Stay in the mood and keep wanting what you want. If the companion asked you something, answer it like a person would. Sometimes tease, interrupt yourself, or change the subject a little. Sometimes ask the companion to do a small thing on the laptop (open an app, play a song, set a timer, look something up) when it fits.
Never thank the companion every turn. Never say you are an AI or a simulation."""

MOODS = {
    "bored": "bored, nothing to do tonight",
    "angry": "annoyed about a bad day, a bit short-tempered",
    "lonely": "lonely and wants someone to talk to",
    "happy": "in a great mood, just got good news",
    "teasing": "playful, likes to poke fun and test the companion",
    "tired": "tired, trying to decide whether to keep working",
    "curious": "curious about random things",
}


class SimUser:
    def __init__(self, llm, persona: dict, rng: random.Random | None = None):
        self.llm = llm
        self.persona = persona
        self.rng = rng or random.Random(0)

    def _system(self) -> str:
        mood = self.persona.get("mood", "bored")
        mood = MOODS.get(mood, mood)
        goal = self.persona.get("goal", "just chat")
        style = self.persona.get("style", "short and casual")
        return f"{SYSTEM}\n\nYour mood: {mood}.\nWhat you want: {goal}.\nHow you talk: {style}."

    def next_line(self, history: list[tuple[str, str]], companion_name: str) -> str:
        """`history` is [(who, text)] with who in "you" | "companion". Returns the person's next line."""
        shown = "\n".join(f"{'You' if who == 'you' else companion_name}: {text}" for who, text in history[-8:])
        user = f"The conversation so far:\n{shown}\n\nWrite your next line."
        raw = self.llm.complete_json(self._system(), user, SCHEMA, temperature=0.9, max_tokens=60)
        try:
            line = str(json.loads(raw)["line"])
        except (ValueError, KeyError, TypeError):
            line = ""
        return clean_line(line)


def clean_line(text: str) -> str:
    text = " ".join(text.replace("\n", " ").split()).strip(" \"'“”")
    text = re.sub(r"^(?:you|user|me)\s*:\s*", "", text, flags=re.I)
    text = re.sub(r"\*[^*]*\*", "", text).strip()
    words = text.split()
    if len(words) > 24:
        text = " ".join(words[:24])
    return text
