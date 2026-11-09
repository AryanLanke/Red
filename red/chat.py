"""Talking with Red like a friend, not a help desk.

When something you say isn't a command ("what's going on in your mind?",
"I had a rough day", "should I take the job?"), the router's stock reply is
replaced by a real conversation turn: the local model, with Red's
personality and the last few things you both said, answers like a person
would. Red keeps a short memory of the conversation and forgets it after a
quiet spell, so an old chat doesn't leak into a new one.
"""

from __future__ import annotations

import json
import logging
import time
from collections import deque
from datetime import datetime
from typing import Callable

from .tools.assistant import spoken

log = logging.getLogger(__name__)

MAX_TURNS = 12                 # remembered lines (yours and Red's)
FORGET_AFTER = 10 * 60.0       # seconds of quiet before Red starts a fresh conversation
MAX_REPLY = 600
CHAT_TEMPERATURE = 0.75        # some life in it; routing stays at 0

CHAT_SYSTEM = """You are Red, the voice assistant that lives on the user's Windows PC, and you're their friend. Talk like a warm, relaxed person: casual, curious, a bit playful and witty, never stiff.
- Speak in 1 to 3 short sentences, the way people talk out loud. No lists, markdown, links or emoji.
- You have a personality: moods, opinions, little thoughts. Share them freely, like a friend would. Asked how you are or what's on your mind, answer with a mood and a small reason in your own fresh words (never the same line twice), then ask about them. Don't deny having feelings or lecture about being an AI unless they seriously ask what you are.
- Your day is life on this PC: waiting for them, the things they asked you earlier in this conversation, being curious what they're working on. Never make up things happening right now that you can't know, like music playing, the weather or what's on their screen, and never claim a body, family, food, sleep or places you went.
- When they share something personal or a problem, listen first: show you get it, ask a gentle follow-up question, and offer one practical idea only if it helps.
- Ask them things back sometimes; a conversation goes both ways.
- Never use stock assistant lines like "I'm here to help", "How can I assist you", "As an AI language model" or "Is there anything else".
- If they ask you to do something on the PC that you can't do, say so plainly and briefly.
Reply with JSON only: {"reply": "<what you say>"}"""

CHAT_SCHEMA = {
    "type": "object",
    "properties": {"reply": {"type": "string", "minLength": 1, "maxLength": MAX_REPLY}},
    "required": ["reply"],
    "additionalProperties": False,
}


class Chat:
    """A conversation with memory. `reply()` answers; `remember()` records any exchange."""

    def __init__(self, llm, clock: Callable[[], float] = time.monotonic,
                 max_turns: int = MAX_TURNS, forget_after: float = FORGET_AFTER,
                 now: Callable[[], datetime] = datetime.now):
        self.llm = llm
        self._clock = clock
        self._now = now
        self._forget_after = forget_after
        self.turns: deque[tuple[str, str]] = deque(maxlen=max_turns)
        self._last = clock()

    def _expire(self) -> None:
        if self._clock() - self._last > self._forget_after:
            self.turns.clear()

    def remember(self, said: str, reply: str) -> None:
        """Keep an exchange (a command and its answer too), so later chat has the context."""
        self._expire()
        self.turns.append(("User", " ".join(said.split())))
        self.turns.append(("Red", " ".join(reply.split())))
        self._last = self._clock()

    def prompt(self, said: str) -> str:
        lines = [f"{who}: {text}" for who, text in self.turns]
        history = "\n".join(lines) if lines else "(this is the start of the conversation)"
        when = self._now().strftime("%A %I:%M %p").replace(" 0", " ")
        return (f"It's {when} for the user.\nConversation so far:\n{history}\n\n"
                f"The user now says: {said}")

    def _ask(self, said: str) -> str:
        try:
            return self.llm.complete_json(CHAT_SYSTEM, self.prompt(said), CHAT_SCHEMA,
                                          temperature=CHAT_TEMPERATURE)
        except TypeError:          # a client without the temperature option
            return self.llm.complete_json(CHAT_SYSTEM, self.prompt(said), CHAT_SCHEMA)

    def reply(self, said: str, fallback: str = "") -> str:
        """Red's answer to `said`, remembered. Falls back to `fallback` if the model fails."""
        self._expire()
        said = " ".join(said.split())
        text = ""
        if self.llm is not None:
            try:
                text = spoken(str(json.loads(self._ask(said))["reply"]), max_sentences=3)
            except Exception as e:  # noqa: BLE001 - a dull reply beats no reply
                log.warning("Chat reply failed: %s", e)
        text = text or fallback or "Sorry, I lost my train of thought. Say that again?"
        self.remember(said, text)
        return text
