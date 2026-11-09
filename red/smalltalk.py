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
    r"not right now|not really|no more|i'm fine|i am fine|that's fine|"
    r"that's all|that is all|that's it|that is it|i'm good|i am good|"
    r"i'm done|i am done|all good|all done|we're good|we are good|never ?mind|"
    r"stop|stop listening|go to sleep|bye|goodbye|good bye|see you|see you later|"
    r"that will be all|that'll be all)"
    r"(?: for now| thanks| thank you| red)*"
    r"|(?:no|nope|nah)(?:,)? (?:that's all|that is all|nothing|thanks|thank you|i'm good|i am good|"
    r"that's it|i'm fine|not really)"
)
_GOODBYE_RE = re.compile(_GOODBYES.pattern)


def is_goodbye(text: str) -> bool:
    """True when `text` just says "no, that's all": nothing more for Red to do."""
    said = normalize(text)
    return bool(said) and _GOODBYE_RE.fullmatch(said) is not None


# "Go away", "leave me alone", "I don't need your help": end the conversation
# at any point, not only in a follow-up.
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


# "Can you ...?", "Could you ...?", "... will you do that?": asking whether Red
# can do something. Red says it can and asks before doing it.
_ABILITY = re.compile(
    r"^(?:hey red )?(?:can|could|would|will) you\b"
    r"|^(?:are you able|would you be able|will you be able) to\b"
    r"|^is it possible\b"
    r"|^do you know how to\b"
    r"|^(?:can|could|may) i ask you to\b"
    r"|\b(?:can|could|will|would) you do (?:that|this|it)\b"
    r"|\bis that something you can do\b"
)

# Yes, the relaxed way people say it. Only for things that aren't risky:
# shutdown and friends still need a plain "yes".
_CASUAL_YES = re.compile(
    r"(?:yes|yeah|yep|yup|ya|sure|ok|okay|alright|all right|of course|absolutely|definitely|"
    r"go ahead|do it|go for it|please|yes please|please do|sure thing|why not)"
    r"(?: (?:yes|yeah|sure|ok|okay|please|go ahead|do it|go for it|thanks|thank you|red))*"
)


def is_ability_question(text: str) -> bool:
    """True for "can you turn off my laptop?", not for "turn off my laptop"."""
    return _ABILITY.search(normalize(text)) is not None


def is_casual_yes(text: str | None) -> bool:
    return bool(text) and _CASUAL_YES.fullmatch(normalize(text)) is not None


# Sounds and fillers that ask for nothing: "you know", "hmm", "okay so".
# Not "yeah", "okay", "what" or "hey": those answer a question or greet.
_FILLER_WORDS = (
    r"you know|y'know|i mean|i guess|let me see|let's see|let me think|hold on|one sec|"
    r"um+|uh+|uhm|uh huh|er+|erm|hmm+|hm+|mm+|mhm|ah+|oh+|huh|eh|"
    r"okay so|ok so|so|well|like|and|but|anyway|actually|basically|wait"
)
_FILLER = re.compile(rf"(?:(?:{_FILLER_WORDS})\s*)+")


def is_filler(text: str) -> bool:
    """True when `text` is only filler ("you know", "hmm", "okay so"), with no request in it.

    Whisper also turns breaths and room noise into these, so Red ignores them
    instead of answering.
    """
    said = normalize(text)
    return not said or _FILLER.fullmatch(said) is not None


# Words a sentence doesn't end on: "open Edge and...", "um", "play the".
_UNFINISHED_END = re.compile(
    r"\b(?:and|or|but|so|then|also|plus|because|cause|if|when|while|that|which|who|to|for|of|"
    r"with|without|about|from|in|on|at|into|by|the|a|an|my|your|this|some|like|um+|uh+|uhm|"
    r"er+|erm|hmm+|mm+|ah+|oh|well|okay so|ok so|can you|could you|please|maybe|just|is|are)$"
)


def sounds_finished(text: str) -> bool:
    """Whether a transcript sounds like a whole sentence, so Red can stop listening sooner.

    "Open Edge." is finished. "Open Edge and", "um", "play the..." and a
    trailing comma are not: you're probably still talking.
    """
    raw = text.strip()
    if not raw or raw.endswith((",", "...", "…", "-", ":")):
        return False
    said = normalize(raw)
    return bool(said) and _UNFINISHED_END.search(said) is None


# Phrases that sound negative but mean "go on": "you don't need my permission",
# "no problem", "why not". They are removed before looking for no-words.
_NOT_A_NO = re.compile(
    r"\b(?:you )?(?:don't|do not|dont) (?:need|have) (?:to ask(?: me)?|my permission|permission|"
    r"to check(?: with me)?)"
    r"|\bno need (?:to ask(?: me)?|for permission|to check)"
    r"|\bwithout asking(?: me)?"
    r"|\b(?:no|not a) (?:problem|worries)\b"
    r"|\bdon't worry\b|\bwhy not\b|\bwhy don't you\b|\bno doubt\b"
)
# Any of these anywhere in the answer means no.
_NO_WORDS = re.compile(
    r"\b(?:no|nope|nah|don't|dont|do not|not|never|stop|cancel|cancelled|wait|hold on|"
    r"negative|never ?mind|forget it|leave it)\b"
)
# A clear yes: enough even for a shutdown.
_STRONG_YES = re.compile(
    r"\b(?:y|yes|yeah|yep|yup|yea|yah|sure|go ahead|do it|go for it|of course|absolutely|"
    r"definitely|please do|confirm|confirmed|proceed|affirmative)\b"
)
# A relaxed yes: fine for opening an app, not for turning the PC off.
_SOFT_YES = re.compile(r"\b(?:ok|okay|alright|all right|ya|please|fine|right|carry on|go on)\b")


def yes_intent(text: str | None, strict: bool = False) -> bool | None:
    """Whether a spoken or typed answer means yes (True), no (False), or isn't clear (None).

    Yes and no words count anywhere in the sentence, so "Yeah, you don't
    need my permission, go ahead" is a yes. Any no-word ("no", "don't",
    "stop", "cancel") wins over a yes. With `strict` (risky actions), "okay"
    or "please" alone isn't enough: it needs "yes", "sure", "go ahead"...
    """
    if not text:
        return None
    said = _NOT_A_NO.sub(" ", normalize(text))
    if _NO_WORDS.search(said):
        return False
    if _STRONG_YES.search(said):
        return True
    if not strict and _SOFT_YES.search(said):
        return True
    return None
