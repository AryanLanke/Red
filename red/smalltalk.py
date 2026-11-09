"""Instant replies to small talk.

"How are you" or "what are you doing" doesn't need the language model, so
Red answers these straight away instead of showing "thinking" for seconds.
Only whole sentences match: "hey" is small talk, "hey, open Downloads" is
a command and goes to the router as usual.

The replies are honest about what Red is: it runs on this PC and listens
for you. It doesn't claim to see the screen, because it can't.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Callable

Reply = Callable[[datetime], str]


def greeting(now: datetime) -> str:
    if 5 <= now.hour < 12:
        return "Good morning"
    if 12 <= now.hour < 17:
        return "Good afternoon"
    return "Good evening"


_RED = r"(?: red)?"   # "thanks red", "hi red"

_RULES: list[tuple[str, Reply]] = [
    (rf"(?:hi|hello|hey|hey there|hiya|yo){_RED}",
     lambda now: f"{greeting(now)}! What can I do for you?"),
    (rf"good (?:morning|afternoon|evening){_RED}",
     lambda now: f"{greeting(now)}! What can I do for you?"),
    (rf"good ?night{_RED}",
     lambda now: "Good night! Sleep well."),
    (rf"how are you(?: doing)?(?: today)?{_RED}|how's it going{_RED}|how are things{_RED}",
     lambda now: "I'm doing great, thanks for asking. What can I do for you?"),
    (rf"what are you (?:doing|up to)(?: right now| now)?{_RED}",
     lambda now: "Just here on your PC, listening for you. What do you need?"),
    (r"who are you|what is your name|what's your name|whats your name|what are you",
     lambda now: "I'm Red, your assistant on this PC."),
    (rf"(?:thank you|thanks|thanks a lot|thank you so much|thank you very much){_RED}",
     lambda now: "You're welcome!"),
    (rf"(?:are you there|you there|can you hear me){_RED}",
     lambda now: "Yes, I'm here."),
    (r"what can you do|what can you help me with|what do you do",
     lambda now: ("I can open apps, folders and websites, find files, play music, "
                  "set timers and reminders, check the weather, look things up, "
                  "and shut down or restart your PC. Just ask.")),
]

_COMPILED = [(re.compile(pattern), reply) for pattern, reply in _RULES]


def normalize(text: str) -> str:
    """Lower case, curly quotes made straight, punctuation and extra spaces gone."""
    text = text.lower().replace("’", "'").replace("‘", "'")
    text = re.sub(r"[^\w' ]+", " ", text)
    text = re.sub(r"\bplease\b", " ", text)
    return " ".join(text.split()).strip("' ")


def quick_reply(text: str, now: datetime | None = None) -> str | None:
    """A reply for small talk, or None when `text` is a real command."""
    said = normalize(text)
    if not said:
        return None
    for pattern, reply in _COMPILED:
        if pattern.fullmatch(said):
            return reply(now or datetime.now())
    return None


# "No", "that's all", "nothing else": the user is done, so Red stops listening.
_GOODBYES = re.compile(
    r"(?:no|nope|nah|no thanks|no thank you|nothing|nothing else|nothing more|not now|"
    r"not right now|that's all|that is all|that's it|that is it|i'm good|i am good|"
    r"i'm done|i am done|all good|all done|we're good|we are good|never ?mind|"
    r"stop|stop listening|go to sleep|bye|goodbye|good bye|see you|see you later|"
    r"that will be all|that'll be all)"
    r"(?: for now| thanks| thank you| red)*"
    r"|no(?:,)? (?:that's all|that is all|nothing|thanks|thank you|i'm good|i am good|that's it)"
)
_GOODBYE_RE = re.compile(_GOODBYES.pattern)


def is_goodbye(text: str) -> bool:
    """True when `text` just says "no, that's all": nothing more for Red to do."""
    said = normalize(text)
    return bool(said) and _GOODBYE_RE.fullmatch(said) is not None
