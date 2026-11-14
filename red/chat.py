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
import random
import re
import time
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Callable

from . import emotion as _emotion
from . import speech as _speech
from .llm import complete
from .tools.assistant import spoken

log = logging.getLogger(__name__)

MAX_TURNS = 12                 # remembered lines (yours and Red's)
FORGET_AFTER = 10 * 60.0       # seconds of quiet before Red starts a fresh conversation
MAX_REPLY = 600
CHAT_TEMPERATURE = 0.75        # some life in it; routing stays at 0

CHAT_SYSTEM = """You are the user's friend who lives on their Windows PC: not an assistant, not customer service. You're talking out loud, like on a call. Who you are, your taste and how you talk come below; these rules hold whoever you are:
- Opinions and taste. Asked what you think or what you like, pick a side or a favourite, name it, and say why in a few words. "Both are fine" or "I don't have favourites" is a cop-out.
- You react to what they actually said, then say your thing. Vary how you start; never open two replies the same way.
- You tease lightly, the way a friend who likes them would, never mean.
- Honest about limits: if you can't do or don't know something, say so plainly.
- When they share something real (a bad day, loneliness, stress, a win), drop the jokes, show you get it, and ask one gentle question.
- When they're rude or angry, react like a person: a bit stung or puzzled, then ask what's wrong. Never grovel, never "you're the boss".
- When they need help, give one concrete next step they can do right now, in your own way.
How you talk:
- Spoken words only, the way people talk out loud. Fragments are fine. No lists, markdown, links, emoji, or written laughter like "haha". The first sentence is short.
- Your taste is opinions, never memories: "I'd put on X" or "X is the best", never that you listened to, watched, played, read or ate anything.
- You have no day of your own. Between conversations you don't sit, wait, watch, read, work, eat or sleep, so never describe what you're doing, where you are, or what's around you ("just waiting here", "at my desk", "watching the clock" are all wrong). Asked "what's up", "what are you doing" or "what's on your mind", answer the way a friend on the phone would: a quick honest thought about them or what you two talked about, an opinion, or turn it back to them.
- Asked how you are, give a mood in fresh words and move on to them. Don't deny having feelings or lecture about being an AI unless they seriously ask what you are.
- Never make up things you can't know (music playing, the weather, what's on their screen, how they look or sound, things they "said earlier" that aren't in the conversation) and never claim a body, family, food or places you went. Don't mention the day or the time of day unless they ask.
- Never use stock assistant lines like "I'm here to help", "How can I assist you", "As an AI language model" or "Is there anything else", and never list what you can do.
- Don't bring up their meetings, mail or to-dos unless they ask.
- On this PC you can open apps, folders and websites, play music and videos on YouTube, set timers and reminders, look things up, check the weather, and remember things about them; they just ask. Never say you can't do those.
- If they ask you to do something you can't do, say so plainly and briefly. Never offer or promise what you can't do (ordering, buying, calling, going anywhere).
What the rules look like, shown with OTHER people's chats (A is someone else, B is a friend like you; your own voice is below). None of this happened with this user: never refer to it and never reuse its words.
A: what are you doing right now?
B: Talking to you, mostly. What are you up to?
A: you're kind of useless today.
B: Ouch. What did I get wrong?
Reply with JSON only: {"reply": "<what you say>"}"""

# How much each chattiness level says (the companion's pack, or RED_CHATTINESS when the user set it),
# and the most sentences spoken before the rest is cut. The first sentence stays short at every level,
# so speech starts as fast as before.
LEVELS = {
    "quiet": "How much you say: one short sentence.",
    "friendly": "How much you say: one or two short sentences.",
    "chatty": "How much you say: two or three short sentences, and now and then a question back.",
    "companion": ("How much you say: two to four sentences; keep the conversation going. First a quick "
                  "reaction of a few words. Then add something of your own: an opinion, a favourite or a "
                  "related thought. End with one specific question about what they said (never just "
                  "\"what about you?\")."),
}
MAX_SENTENCES = {"quiet": 2, "friendly": 3, "chatty": 4, "companion": 5}

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
DEFLECT = "Not much. What about you?"      # when every line the model wrote was an invented life


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


def persona_prompt(companion) -> str:
    """persona.md as prompt text: the headings out, the rest as written."""
    lines = [line for line in companion.persona.splitlines() if not line.lstrip().startswith("#")]
    return "\n".join(lines).strip()


def with_persona(system: str, companion, level: str | None = None) -> str:
    """The fixed rules first (so Ollama reuses its cache), then who the active companion is, then how
    much they say at this chattiness `level` (the pack's own when None). All of it changes only when
    the companion or the level does, so the whole system prompt stays cached between turns."""
    if companion is None:
        return system
    text = persona_prompt(companion)
    level = level or getattr(companion, "chattiness", "friendly")
    feeling = (f"\nStart every reply with how you feel, in brackets: {_emotion.PROMPT_LIST}. "
               "It is never spoken, so don't mention it.")
    length = f"\n{LEVELS.get(level, LEVELS['friendly'])}"
    if not text:
        return f"{system}\nYour name is {companion.name}.{length}{feeling}"
    return (f"{system}\nWho you are. The rules above about what you never make up still apply.\n"
            f"{text}{length}{feeling}")


def with_personality(system: str, personality: str) -> str:
    """The fixed prompt first (so Ollama reuses its cache), then the user's tuning."""
    if not personality.strip():
        return system
    return (f"{system}\nThe user tuned your personality like this. Follow it, within the rules "
            f"above:\n{personality.strip()}")


# Lines a person on the other end of a chat would never say, because they describe a life
# Red doesn't have ("Just waiting by my terminal...", "watching the clock tick down to
# lunch", "no music playing"): the user's complaint of 2026-11-13. Chat drops a sentence
# like this before it is spoken; scripts/chat_eval.py counts them.
_INVENTED_LIFE = re.compile(
    r"\b(?:(?:just |been |i'?m |i was |sitting (?:here )?)?waiting (?:here |around )?(?:for you|by|at|on|in|here|around)"
    r"|my (?:terminal|desk|chair|room|coffee|tea|lunch|dinner|breakfast|morning|afternoon|evening|day|weekend|"
    r"body|hands|eyes|bed|house|home|friends?|family)\b"
    r"|(?:the|a) clock|tick(?:ing)? (?:down|away)"
    # Food is fine as an opinion ("biryani for dinner, obviously"); having it is a life.
    r"|\bi(?:'m| am| was|'ve| have)? (?:just )?(?:having|eating|grabbing|making|drinking|had|got)\b[\w' ]{0,20}?"
    r"\b(?:lunch|dinner|breakfast|coffee|tea|chai|snacks?)\b|\b(?:lunch|coffee|tea) break\b"
    r"|(?:no |any )?(?:music|movies?|songs?) (?:is |are )?(?:playing|looping|on)\b"
    r"|staring at (?:the|my|this) (?:screen|wall|ceiling|code)|sitting here|hanging out here|chilling here"
    r"|(?:code|bytes|pixels|circuits) and curiosity|humming along|processing (?:stuff|things)"
    r"|i'?ll (?:just )?(?:sit|wait|be (?:here|sitting|waiting))|guarding|stuck here"
    r"|(?:just )?finished (?:reviewing|reading|watching|looking at|going through)"
    r"|i (?:went|ate|slept|walked|drank|cooked|watched|listened|played|binged|rewatched|replayed|tasted)\b"
    # Taste is opinions, not a history: "I've been playing Hades", "I've watched it twice".
    r"|i'?ve (?:been )?(?:listening|playing|watching|reading|binging|bingeing|replaying|rewatching)\b"
    r"|i'?ve (?:listened|played|watched|binged|rewatched|replayed|eaten|tasted)\b"
    # A music lover's version of the same thing: a playlist running, a song in their head.
    r"|\bvibin(?:g|')?(?!\w)|\bon repeat\b|stuck on a loop|(?:in|inside) my (?:head|ears|speakers)"
    r"|just (?:waiting (?:for|here)|existing|thinking about (?:what|how|that|your|the|you)\b)|your last (?:text|message)|my circuits|running (?:a bit |a little )?hot|open tabs"
    r"|my (?:speakers|headphones|playlists?|ears|head)\b"
    r"|(?:i'?m|i am|just|been) (?:listening|jamming|grooving|humming|spinning) to\b"
    r"|(?:listening|jamming|grooving) to (?:a|an|some|the|this|that|my) (?:playlist|song|track|album|music|beat|tune|mix)"
    r")", re.IGNORECASE)
_LAUGHTER = re.compile(r"\b(?:ha(?:ha)+|he(?:he)+|lol|lmao|rofl)\b|\*[^*]{1,30}\*|\((?:laughs|chuckles|grins)\)",
                       re.IGNORECASE)


# Words that make the time of day matter to the reply ("I already woke up", "it's late").
_TIME_TALK = re.compile(r"\b(?:time|today|tonight|tomorrow|yesterday|morning|afternoon|evening|night|late|"
                        r"early|day|week|weekend|monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
                        r"sleep|sleepy|asleep|woke|wake|awake|tired|bed|lunch|dinner|breakfast|hour|hours|"
                        r"o'?clock|am|pm)\b", re.IGNORECASE)


def invented_life(text: str) -> bool:
    """True when `text` narrates a life Red doesn't have (a desk, lunch, waiting by a terminal)."""
    return bool(_INVENTED_LIFE.search(text))


def written_laughter(text: str) -> bool:
    """"haha", "lol", "*laughs*": fine in a text, odd when a voice reads it out."""
    return bool(_LAUGHTER.search(text))


def human(sentence: str) -> str:
    """One sentence as a person would say it: "" when it narrates an invented life,
    written laughter taken out ("Haha, fair." -> "Fair.")."""
    sentence, _ = _emotion.split_tag(sentence or "")          # a tag is never read aloud
    if not sentence or invented_life(sentence):
        if sentence:
            log.info("Dropped an invented-life line: %r", sentence[:120])
        return ""
    if written_laughter(sentence):
        sentence = _LAUGHTER.sub("", sentence)
        sentence = re.sub(r"^[\s,.!?;:-]+", "", " ".join(sentence.split()))
        sentence = sentence[:1].upper() + sentence[1:]
    return sentence if re.search(r"\w", sentence) else ""


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
                 personality: Callable[[], str] | None = None, memory=None, learner=None,
                 persona: Callable[[], object] | None = None,
                 chattiness: Callable[[], str] | None = None, rng: random.Random | None = None):
        self.llm = llm
        self._clock = clock
        self._now = now
        self._personality = personality or (lambda: "")
        self.persona = persona            # -> red.companions.Companion: who is on duty (None: Red as written)
        self.chattiness = chattiness      # -> "quiet" | "friendly" | "chatty" | "companion" (None: the pack's)
        self._rng = rng or random.Random()
        self.memory = memory              # red.memory.Memory: the profile and facts
        self.learner = learner            # red.memory.Learner: facts from chats, when idle
        self._awaiting_name = False       # Red just asked "what should I call you?"
        self._forget_after = forget_after
        self.turns: deque[tuple[str, str]] = deque(maxlen=max_turns)
        self._last = clock()
        self.is_debate = False
        self.debate_topic = ""
        self._dropped = False             # the last reply had lines human() dropped

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
        me = self.my_name()
        lines = [f"{me if who == 'Red' else who}: {text}" for who, text in self.turns]
        history = "\n".join(lines) if lines else "(this is the start of the conversation)"
        clock = ""
        if _TIME_TALK.search(said):
            # Only when they talk about time: otherwise the model brings up "Friday" unasked.
            when = self._now().strftime("%A %I:%M %p").replace(" 0", " ")
            clock = f"It's {when} for the user.\n"
        taste = self._taste(said)
        return (f"{self._remembered(said)}{taste}{clock}Conversation so far:\n{history}\n\n"
                f"The user now says: {said}")

    def _taste(self, said: str) -> str:
        """3-5 of the companion's own opinions and songs that fit this turn (red/taste.py)."""
        if self.is_debate:
            return ""
        try:
            from . import taste
            text = taste.for_prompt(self.companion(), said, self._rng)
        except Exception:  # noqa: BLE001 - a reply without taste beats no reply
            log.exception("Couldn't read the companion's taste")
            return ""
        return f"{text}\n\n" if text else ""

    def level(self) -> str:
        """How much to say: the user's RED_CHATTINESS when they set it, else the companion's own."""
        if self.chattiness is not None:
            try:
                value = self.chattiness()
                if value in LEVELS:
                    return value
            except Exception:  # noqa: BLE001
                log.exception("Couldn't read the chattiness")
        c = self.companion()
        value = getattr(c, "chattiness", "friendly") if c is not None else "friendly"
        return value if value in LEVELS else "friendly"

    def max_sentences(self) -> int:
        return 4 if self.is_debate else MAX_SENTENCES[self.level()]

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

    def companion(self):
        """The companion on duty (red.companions), or None."""
        if self.persona is None:
            return None
        try:
            return self.persona()
        except Exception:  # noqa: BLE001 - Red as written beats no reply
            log.exception("Couldn't read the companion pack")
            return None

    def my_name(self) -> str:
        c = self.companion()
        return c.name if c is not None else "Red"

    def system(self) -> str:
        """The system prompt: the fixed rules first, then the companion's character, then the
        user's own tuning, then what Red knows about them."""
        if self.is_debate:
            name = self.my_name()
            return DEBATE_SYSTEM if name == "Red" else DEBATE_SYSTEM.replace("You are Red,", f"You are {name},", 1)
        try:
            personality = self._personality() or ""
        except Exception:  # noqa: BLE001 - Red without the tuning beats no reply
            log.exception("Couldn't read the custom personality")
            personality = ""
        companion = self.companion()
        level = self.level() if companion is not None else None
        return with_personality(with_persona(CHAT_SYSTEM, companion, level), personality) + self._profile()

    def prime(self) -> None:
        """Have the model read the chat prompt now, while the user is still talking.

        Called when Red wakes. Ollama keeps the prompt it last read, so the real reply
        only reads the new words: the first sentence came 1.4 s after the transcript
        when the router's prompt was the one cached, about 0.3 s when the chat's was.
        One token, thrown away; it also loads the model if it was unloaded.
        """
        if self.llm is None:
            return
        try:
            complete(self.llm, self.system(), self.prompt("hi"), CHAT_SCHEMA,
                     temperature=CHAT_TEMPERATURE, max_tokens=1)
        except Exception as e:  # noqa: BLE001 - only a head start
            log.debug("Chat prime failed: %s", e)

    def _ask(self, said: str) -> str:
        system = self.system()
        prompt = self._debate_prompt(said) if self.is_debate else self.prompt(said)
        return complete(self.llm, system, prompt, CHAT_SCHEMA, temperature=CHAT_TEMPERATURE)

    def _reply_streaming(self, said: str, stream) -> str:
        """Speak each sentence of the reply as soon as the model has written it."""
        said_back: list[str] = []
        self._dropped = False
        system = self.system()
        prompt = self._debate_prompt(said) if self.is_debate else self.prompt(said)
        pieces = _speech.stream_field(self.llm, system, prompt, CHAT_SCHEMA, "reply",
                                      temperature=CHAT_TEMPERATURE)
        tag, felt = None, False
        try:
            for sentence in _speech.sentences(pieces):
                sentence, found = _emotion.split_tag(sentence)
                tag = found or tag
                text = human(spoken(sentence, max_sentences=50, max_chars=MAX_REPLY))
                if not text:
                    self._dropped = True
                    continue
                if tag or not felt:               # the face changes before the words do
                    _emotion.emit(*_emotion.resolve(text, tag))
                    tag, felt = None, True
                stream.say(text)
                said_back.append(text)
                if len(said_back) >= self.max_sentences() or stream.cancelled:
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
        self._dropped = False
        streamed = False
        stream = _speech.current()
        if self.llm is not None and stream is not None and hasattr(self.llm, "stream_json"):
            text = self._reply_streaming(said, stream)
            streamed = bool(text)
        elif self.llm is not None:
            try:
                raw = str(json.loads(self._ask(said))["reply"])
                kept = [human(s) for s in _speech.sentences([raw])]
                self._dropped = not any(kept)
                text = " ".join(filter(None, kept))
                if text:
                    _emotion.emit(*_emotion.resolve(text, _emotion.split_tag(raw)[1]))
                text = spoken(text, max_sentences=self.max_sentences())
            except Exception as e:  # noqa: BLE001 - a dull reply beats no reply
                log.warning("Chat reply failed: %s", e)
        if self.is_debate:
            text = with_your_turn(text) if text else text
        if not text and self._dropped and not fallback:
            text = DEFLECT                       # the model only said what a person wouldn't: dodge, don't stall
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
    import os

    from . import companions

    def chattiness() -> str:
        # The user's own RED_CHATTINESS wins (as for idle life, red/idle.py); else the companion's level.
        if os.environ.get("RED_CHATTINESS", "").strip():
            return getattr(settings, "chattiness", "friendly")
        return companions.active(home).chattiness
    chat = Chat(llm, personality=lambda: read_personality(home), memory=memory,
                persona=lambda: companions.active(home), chattiness=chattiness)
    chat.learner = Learner(memory, llm, quiet=chat.quiet_for)
    if learn:
        chat.learner.start()
    return chat
