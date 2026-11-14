"""How Red feels while it talks: a tag in the reply, or a cheap guess, as an `emotion` event.

The chat prompt asks for one feeling at the start of a reply: `[happy] Nice one.` The tag is cut out
before the sentence is spoken (a tag is never read aloud, whichever bracket the model puts it in).
When the model leaves it out, `classify()` guesses from the words: no model call, under a millisecond.

`events.emit("emotion", name=..., strength=...)` carries the avatar's own names: happy, laugh, sad,
angry, surprised, shy, thinking, sleepy, or neutral (strength 0: back to the plain face). A tag of
`[annoyed]` is `angry` at half strength, so the avatar needs no new frames. `strength` is 0..1.
"""

from __future__ import annotations

import re

from . import events

# The names the model may use in a tag (the prompt lists the first few) and what else it tends to write.
EMOTIONS = ("happy", "laugh", "sad", "annoyed", "angry", "surprised", "shy", "thinking", "sleepy", "neutral")
PROMPT_LIST = "[happy], [annoyed], [sad], [surprised], [shy], [laugh] or [neutral]"
ALIASES = {
    "excited": "happy", "glad": "happy", "joy": "happy", "joyful": "happy", "pleased": "happy",
    "warm": "happy", "proud": "happy", "playful": "happy", "teasing": "happy", "cheerful": "happy",
    "amused": "laugh", "laughing": "laugh", "giggle": "laugh", "chuckle": "laugh", "laughs": "laugh",
    "upset": "sad", "sorry": "sad", "worried": "sad", "concerned": "sad", "gentle": "sad", "lonely": "sad",
    "mad": "angry", "furious": "angry", "irritated": "annoyed", "grumpy": "annoyed", "stung": "annoyed",
    "sarcastic": "annoyed", "dry": "annoyed", "frustrated": "annoyed",
    "shocked": "surprised", "surprise": "surprised", "amazed": "surprised", "curious": "thinking",
    "embarrassed": "shy", "awkward": "shy", "nervous": "shy",
    "calm": "neutral", "serious": "neutral", "tired": "sleepy", "sleep": "sleepy", "bored": "neutral",
    "thoughtful": "thinking", "hmm": "thinking",
}
# What the avatar knows -> (its name, the strength a bare tag means).
AVATAR = {
    "happy": ("happy", 0.7), "laugh": ("laugh", 0.8), "sad": ("sad", 0.7), "annoyed": ("angry", 0.5),
    "angry": ("angry", 0.9), "surprised": ("surprised", 0.8), "shy": ("shy", 0.6),
    "thinking": ("thinking", 0.5), "sleepy": ("sleepy", 0.5), "neutral": ("neutral", 0.0),
}

# [happy], [ Annoyed ], [mild sigh]: any short bracketed word group. The ones we know are used, all are cut.
_TAG = re.compile(r"\[\s*([A-Za-z][A-Za-z ,'-]{1,24}?)\s*\]\s*")


def canonical(word: str) -> str | None:
    """'Excited' -> 'happy', 'annoyed' -> 'annoyed', 'sigh' -> None."""
    word = " ".join(word.lower().replace(",", " ").split())
    for part in [word, *word.split()]:
        if part in EMOTIONS:
            return part
        if part in ALIASES:
            return ALIASES[part]
    return None


def split_tag(text: str) -> tuple[str, str | None]:
    """('[happy] Nice one.') -> ('Nice one.', 'happy'). Every bracketed tag is removed; the first
    one that names a feeling is returned (else None)."""
    found: list[str] = []

    def take(m: re.Match) -> str:
        name = canonical(m.group(1))
        if name:
            found.append(name)
        return ""

    clean = _TAG.sub(take, text)
    clean = " ".join(clean.split())
    return clean, (found[0] if found else None)


# --- the cheap classifier ---------------------------------------------------------------------

_GUESS = (
    ("laugh", r"\b(?:ha ha|ha!|funny|hilarious|good one|you got me)\b|😂|🤣"),
    ("sad", r"\b(?:sorry|sad|unfortunately|rough|oof|oh no|that sucks|lonely|hurts?|heavy|miss(?:ed)?)\b|😢"),
    ("angry", r"\b(?:ugh|annoying|furious|come on|seriously|ouch|rude|stung|excuse me|really\?)\b"),
    ("surprised", r"\b(?:whoa|wow|no way|what\?!|really\?!|wait,|seriously\?!)\b|!\?"),
    ("shy", r"\b(?:oops|my bad|embarrassing|um+|blush)\b"),
    ("happy", r"\b(?:great|nice|awesome|glad|love|yay|perfect|congrat\w*|congrats|happy|good news|fun|"
              r"deal|sounds good|let's go|brilliant|splendid)\b|[😊🙂😄]"),
    ("thinking", r"\b(?:hmm+|let me think|good question|depends|not sure)\b"),
)


def classify(text: str) -> tuple[str, float]:
    """A rough feeling for `text`: (name, strength). ('neutral', 0.0) when nothing stands out."""
    low = (text or "").lower()
    for name, pattern in _GUESS:
        if re.search(pattern, low):
            strength = AVATAR[name][1] + (0.15 if "!" in low else 0.0)
            return name, round(min(strength, 1.0), 2)
    return "neutral", 0.0


def resolve(text: str, tag: str | None) -> tuple[str, float]:
    """The feeling to show: the model's tag when it gave one, else the guess. -> (avatar name, strength)."""
    if tag:
        name, strength = AVATAR[tag]
        return name, strength
    name, strength = classify(text)
    return AVATAR[name][0], strength


def emit(name: str, strength: float) -> None:
    events.emit("emotion", name=name, strength=strength)
