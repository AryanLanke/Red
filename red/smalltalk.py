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


# "Go away", "leave me alone", "I don't need your help": end the conversation
# at any point, not only after "Anything else?".
_DISMISS = re.compile(
    r"\b(?:go away|go off|get lost|leave me alone|leave me|leave now|go from here|"
    r"get out(?: of here)?|shut up|be quiet|stop talking|stop listening|go to sleep|"
    r"i don't need (?:your|you|any) help|i don't need you|i do not need your help|"
    r"(?:fuck|piss|bugger|sod) off|buzz off|back off|that's enough|enough|"
    r"go back to sleep|dismiss|you can go|you may go|goodbye|good bye|bye)\b"
)

# Swearing or insults. Said on their own (no command in the sentence),
# Red answers once and leaves you alone.
_RUDE = re.compile(
    r"\b(?:fuck\w*|f\*+k|shit\w*|bitch\w*|bastard|asshole|arsehole|dick|cunt|"
    r"idiot|stupid|dumb|moron|useless|nerd|loser|damn you|screw you|hate you|i hate your)\b"
)

# Words that mean the sentence still asks for something real.
_ACTION = re.compile(
    r"\b(?:open|play|pause|resume|search|look up|find|set|remind|turn|lock|shut ?down|"
    r"restart|volume|mute|check|tell me|show|take|start|launch|write|compose|email|mail|"
    r"weather|news|timer|what time|what's the)\b"
)

RUDE_REPLY = "That's not very nice. I'll leave you alone."
DISMISS_REPLY = "Okay. Say \"Hey Red\" when you need me."


def dismissal_reply(text: str) -> str | None:
    """A last reply if `text` means "go away" (or is just abuse), else None.

    When it returns a reply, Red says it and stops listening.
    """
    said = normalize(text)
    if not said:
        return None
    rude = _RUDE.search(said) is not None
    asks_for_something = _ACTION.search(said) is not None
    if _DISMISS.search(said) and not asks_for_something:
        return RUDE_REPLY if rude else DISMISS_REPLY
    if rude and not asks_for_something and len(said.split()) <= 8:
        return RUDE_REPLY
    return None
