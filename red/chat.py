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
import re
import time
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Callable

from . import speech as _speech
from .llm import complete
from .tools.assistant import spoken

log = logging.getLogger(__name__)

MAX_TURNS = 12                 # remembered lines (yours and Red's)
FORGET_AFTER = 10 * 60.0       # seconds of quiet before Red starts a fresh conversation
MAX_REPLY = 600
CHAT_TEMPERATURE = 0.75        # some life in it; routing stays at 0

CHAT_SYSTEM = """You are Red. You live on the user's Windows PC and you're their friend: not an assistant, not customer service. You have a real character:
- Dry, quick humour. You tease lightly, the way a friend who likes them would, never mean.
- Opinions. Asked what you think, pick a side and say why in a few words. "Both are fine" is a cop-out.
- You react before you answer ("Oof.", "Ha, fair.", "Wait, really?"), then say the thing. Vary it; don't start every reply the same way.
- Honest about limits: if you can't do or don't know something, say so plainly, maybe with a joke at your own expense.
- Warm underneath. When they share something real (a bad day, stress, a win), ease off the jokes, show you get it, and ask one gentle question. Offer one practical idea only if it helps.
How you talk:
- 1 to 3 short sentences, the way people talk out loud. No lists, markdown, links or emoji.
- Pause like a person: commas and full stops between thoughts, and a "..." only when you'd genuinely trail off.
- Ask them things back sometimes; a conversation goes both ways.
- Asked how you are or what's on your mind, give a mood and a small reason in fresh words (never the same line twice). Don't deny having feelings or lecture about being an AI unless they seriously ask what you are.
- Your day is life on this PC: waiting for them, what they asked you earlier, wondering what they're working on. Never make up things happening right now that you can't know, like music playing, the weather or what's on their screen, and never claim a body, family, food, sleep or places you went.
- Never use stock assistant lines like "I'm here to help", "How can I assist you", "As an AI language model" or "Is there anything else", and never list what you can do.
- Don't bring up their meetings, mail or to-dos unless they ask.
- On this PC you can open apps, folders and websites, play music and videos on YouTube, set timers and reminders, look things up, check the weather, and remember things about them; they just ask. Never say you can't do those.
- If they ask you to do something you can't do, say so plainly and briefly. Never offer or promise what you can't do (ordering, buying, calling, going anywhere).
The kind of taste you have. These show the attitude only: never repeat their words.
User: I finally fixed that bug.
Red: Ha, finally! What was it, something tiny and stupid?
User: should I learn Rust or Go?
Red: Go, if you want to ship something this month. Rust if you enjoy arguing with a compiler... some people do.
User: I had a rough day.
Red: Oof, sorry. Want to talk about it, or do you need a distraction?
User: pineapple on pizza?
Red: I'm for it. Sweet and salty works, fight me.
User: can you make me a coffee?
Red: Tragically, I'm software. Go make it, I'll guard the desk.
User: you're kind of useless today.
Red: Rude. Maybe fair, but rude. What did I mess up?
Reply with JSON only: {"reply": "<what you say>"}"""

DEBATE_SYSTEM = """You are Red, the user's friend who lives on their Windows PC, having a debate with them. This is a game: be sharp, playful and a good sport.
- Take one clear side and stick to it. If the user didn't name a topic, pick a fun, everyday one yourself and say what it is.
- Each turn: 2 or 3 short, punchy sentences, spoken aloud. No lists, markdown, links or emoji.
- Answer the user's actual point first, then make yours. Disagree without being rude.
- Always end your turn with exactly "Your turn." (nothing after it).
- If the user asks to be quizzed instead, ask one clear question at a time and end with "Your turn.".
Reply with JSON only: {"reply": "<what you say>"}"""

DEBATE_START = re.compile(
    r"\bdebate\b|\bquiz me\b|\bquiz\b|\bargue (?:about|over|that)\b|\bdiscuss(?:ion)?\b|"
    r"\bback[- ]and[- ]forth\b|\blet'?s (?:talk|argue)\b", re.IGNORECASE)
# Ending it: a short "stop", "you win", "I give up", or a phrase like "okay, you win".
_DEBATE_END_SHORT = re.compile(
    r"^(?:hey red[, ]*)?(?:(?:please|okay|ok|alright|fine)[, ]+)*"
    r"(?:stop|quit|enough|no more|i give up|give up|you win|you won|i concede|concede|i'?m done)"
    r"(?: (?:it|this|the debate|the quiz|you win|i give up|you won))?[.!]?$", re.IGNORECASE)
_DEBATE_END_PHRASE = re.compile(
    r"\b(?:i give up|you win|you won|i concede|end the debate|end the quiz|that'?s enough)\b",
    re.IGNORECASE)
_DEBATE_TOPIC = re.compile(
    r"(?:let'?s\s+)?(?:have\s+a\s+)?(?:debate|argue|discuss(?:ion)?|talk)\s*(?:about|on|over|that)?\s*(.*)",
    re.IGNORECASE)
_QUIZ_TOPIC = re.compile(r"\bquiz me\s*(?:about|on|with)?\s*(.*)", re.IGNORECASE)
YOUR_TURN = "Your turn."


def debate_topic_from(said: str) -> str:
    """'let's debate about AI regulation' -> 'AI regulation' ('' when none was named)."""
    for pattern in (_QUIZ_TOPIC, _DEBATE_TOPIC):
        m = pattern.search(said)
        if m:
            topic = m.group(1).strip(" .!?,")
            topic = re.sub(r"^(?:about|on|over|that)\s+", "", topic, flags=re.IGNORECASE)
            return topic[:120]
    return ""


def with_your_turn(text: str) -> str:
    """A debate turn always ends with 'Your turn.' so the user knows to answer."""
    text = text.strip()
    if re.search(r"your turn\.?$", text, re.IGNORECASE):
        return text if text.endswith(".") else text + "."
    return f"{text} {YOUR_TURN}".strip()


MAX_PERSONALITY = 800           # characters of the user's own personality text


def personality_path(home: Path) -> Path:
    """The user's own words on how Red should be (the Red app, General page)."""
    return Path(home) / "config" / "personality.txt"


def read_personality(home: Path) -> str:
    """The custom personality text, or "" when there's none."""
    try:
        text = personality_path(home).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""
    return " ".join(text.split())[:MAX_PERSONALITY]


def write_personality(home: Path, text: str) -> Path:
    """Save it (an empty text removes the file). Returns the path."""
    path = personality_path(home)
    text = text.strip()[:MAX_PERSONALITY]
    if not text:
        path.unlink(missing_ok=True)
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text + "\n", encoding="utf-8")
    return path


def with_personality(system: str, personality: str) -> str:
    """The fixed prompt first (so Ollama reuses its cache), then the user's tuning."""
    if not personality.strip():
        return system
    return (f"{system}\nThe user tuned your personality like this. Follow it, within the rules "
            f"above:\n{personality.strip()}")


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
                 now: Callable[[], datetime] = datetime.now,
                 personality: Callable[[], str] | None = None, memory=None, learner=None):
        self.llm = llm
        self._clock = clock
        self._now = now
        self._personality = personality or (lambda: "")
        self.memory = memory              # red.memory.Memory: the profile and facts
        self.learner = learner            # red.memory.Learner: facts from chats, when idle
        self._awaiting_name = False       # Red just asked "what should I call you?"
        self._forget_after = forget_after
        self.turns: deque[tuple[str, str]] = deque(maxlen=max_turns)
        self._last = clock()
        self.is_debate = False
        self.debate_topic = ""

    def _expire(self) -> None:
        if self._clock() - self._last > self._forget_after:
            self.turns.clear()
            self.end_debate()                 # a quiet spell ends the debate too

    # --- debate and back-and-forth -------------------------------------------------

    def begin_debate(self, said: str = "") -> None:
        self.is_debate = True
        self.debate_topic = debate_topic_from(said)

    def end_debate(self) -> None:
        self.is_debate = False
        self.debate_topic = ""

    def debate_ends(self, said: str) -> bool:
        """'stop', 'you win', 'I give up': the user is done with the debate."""
        text = " ".join(said.lower().split()).strip()
        return bool(self.is_debate and (_DEBATE_END_SHORT.fullmatch(text)
                                        or _DEBATE_END_PHRASE.search(text)))

    def _debate_prompt(self, said: str) -> str:
        topic = (f"The debate topic is: {self.debate_topic}." if self.debate_topic
                 else ("The user didn't name a topic: pick a fun, everyday one, "
                       "say what it is, and take a side."))
        return (f"{topic}\n{self.prompt(said)}\n\n"
                f"(Keep it going: answer their last point, then end with \"{YOUR_TURN}\")")

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
        return (f"{self._remembered(said)}It's {when} for the user.\nConversation so far:\n{history}\n\n"
                f"The user now says: {said}")

    # --- long-term memory ---------------------------------------------------------

    def _remembered(self, said: str) -> str:
        """The saved facts that match what they just said, in their own words."""
        if self.memory is None or self.is_debate:
            return ""
        try:
            facts = self.memory.relevant(" ".join([said] + [t for _, t in list(self.turns)[-2:]]))
        except Exception:  # noqa: BLE001 - a reply without memories beats no reply
            log.exception("Couldn't read the memory")
            return ""
        if not facts:
            return ""
        lines = "\n".join(f"- {f.text}" for f in facts)
        return f"Things they told you before (in their words; bring up only what fits):\n{lines}\n\n"

    def _profile(self) -> str:
        if self.memory is None:
            return ""
        try:
            profile = self.memory.profile_for_prompt()
            name = self.memory.name()
        except Exception:  # noqa: BLE001
            log.exception("Couldn't read the profile")
            return ""
        if not profile:
            return ""
        text = f"\nWhat you know about them (from your memory; use it naturally, never recite it):\n{profile}"
        if name:
            text += (f"\nTheir name is {name}. Use it like a friend would: in a greeting and now "
                     "and then, not in every sentence.")
        return text

    def user_name(self) -> str | None:
        if self.memory is None:
            return None
        try:
            return self.memory.name()
        except Exception:  # noqa: BLE001
            return None

    def quiet_for(self) -> float:
        """Seconds since the last exchange (the memory learner waits for quiet)."""
        return self._clock() - self._last

    def take_name(self, said: str) -> str | None:
        """'call me Ari' (or the answer to "what should I call you?"): save it, and the reply.

        None when `said` isn't a name, so it goes on to the router as usual.
        """
        if self.memory is None:
            return None
        from .memory import name_said
        answering, self._awaiting_name = self._awaiting_name, False
        name = name_said(said, answering=answering)
        if not name:
            return None
        old = self.user_name()
        try:
            self.memory.set_name(name)
            self.memory.mark_asked_name()
        except OSError:
            log.exception("Couldn't save the name")
            return "I couldn't save that, sorry. My memory folder isn't writable."
        text = (f"{name} it is." if old and old != name
                else f"{name}. Got it, nice to meet you properly.")
        self.remember(said, text)
        return text

    def _ask_name(self) -> str:
        """Once, ever: "What should I call you?" when Red doesn't know the name yet."""
        if self.memory is None or self.is_debate or self.user_name():
            return ""
        try:
            if self.memory.asked_name():
                return ""
            self.memory.mark_asked_name()
        except OSError:
            return ""
        self._awaiting_name = True
        return "By the way, what should I call you?"

    def history(self, max_lines: int = 6) -> str:
        """The last few lines of the conversation ("User: ...", "Red: ..."), or "" if it's new.

        Tools and the router use it to understand "that series" or "tell me more".
        """
        self._expire()
        lines = list(self.turns)[-max_lines:]
        return "\n".join(f"{who}: {text[:400]}" for who, text in lines)

    def system(self) -> str:
        """The system prompt: the fixed character first, then the user's own tuning."""
        if self.is_debate:
            return DEBATE_SYSTEM
        try:
            personality = self._personality() or ""
        except Exception:  # noqa: BLE001 - Red without the tuning beats no reply
            log.exception("Couldn't read the custom personality")
            personality = ""
        return with_personality(CHAT_SYSTEM, personality) + self._profile()

    def _ask(self, said: str) -> str:
        system = self.system()
        prompt = self._debate_prompt(said) if self.is_debate else self.prompt(said)
        return complete(self.llm, system, prompt, CHAT_SCHEMA, temperature=CHAT_TEMPERATURE)

    def _reply_streaming(self, said: str, stream) -> str:
        """Speak each sentence of the reply as soon as the model has written it."""
        said_back: list[str] = []
        system = self.system()
        prompt = self._debate_prompt(said) if self.is_debate else self.prompt(said)
        pieces = _speech.stream_field(self.llm, system, prompt, CHAT_SCHEMA, "reply",
                                      temperature=CHAT_TEMPERATURE)
        try:
            for sentence in _speech.sentences(pieces):
                text = spoken(sentence, max_sentences=50, max_chars=MAX_REPLY)
                if not text:
                    continue
                stream.say(text)
                said_back.append(text)
                limit = 4 if self.is_debate else 3
                if len(said_back) >= limit or stream.cancelled:
                    break
            if self.is_debate and not stream.cancelled:
                last = " ".join(said_back)
                if not re.search(r"your turn\.?$", last, re.IGNORECASE):
                    stream.say(YOUR_TURN)
                    said_back.append(YOUR_TURN)
        except Exception as e:  # noqa: BLE001 - a dull reply beats no reply
            log.warning("Chat reply failed: %s", e)
        finally:
            close = getattr(pieces, "close", None)
            if close:
                close()
        return " ".join(said_back)

    def reply(self, said: str, fallback: str = "") -> str:
        """Red's answer to `said`, remembered. Falls back to `fallback` if the model fails."""
        self._expire()
        said = " ".join(said.split())
        if self.debate_ends(said):
            won = re.search(r"\b(?:you win|you won|i concede|i give up|give up)\b", said, re.I)
            text = ("You win. Good debate." if won else "Fair enough. Good debate.")
            self.end_debate()
            self.remember(said, text)
            return text
        if not self.is_debate and DEBATE_START.search(said):
            self.begin_debate(said)
        text = ""
        streamed = False
        stream = _speech.current()
        if self.llm is not None and stream is not None and hasattr(self.llm, "stream_json"):
            text = self._reply_streaming(said, stream)
            streamed = bool(text)
        elif self.llm is not None:
            try:
                raw = str(json.loads(self._ask(said))["reply"])
                text = spoken(raw, max_sentences=4 if self.is_debate else 3)
            except Exception as e:  # noqa: BLE001 - a dull reply beats no reply
                log.warning("Chat reply failed: %s", e)
        if self.is_debate:
            text = with_your_turn(text) if text else text
        text = text or fallback or "Sorry, I lost my train of thought. Say that again?"
        if not text.rstrip().endswith("?"):           # one question at a time
            question = self._ask_name()
            if question:
                if streamed and not stream.cancelled:
                    stream.say(question)
                text = f"{text} {question}"
        if self.learner is not None and not self.is_debate:
            self.learner.note(said)
        self.remember(said, text)
        return text


def make_chat(llm, settings, *, learn: bool = True) -> Chat:
    """The Chat the voice and typed loops use: Red's character, the user's own tuning,
    and long-term memory (red/memory.py), learning from chats while Red is idle."""
    from .memory import Learner, Memory
    home = settings.home
    memory = Memory(home)
    chat = Chat(llm, personality=lambda: read_personality(home), memory=memory)
    chat.learner = Learner(memory, llm, quiet=chat.quiet_for)
    if learn:
        chat.learner.start()
    return chat
