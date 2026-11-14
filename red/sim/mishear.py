"""Whisper's typical mistakes, applied to a sentence the user meant.

From red.log and commands.jsonl: names heard as other names (Remy -> Rennel, Asha -> Asia), a sound-alike
word, a missing first or last word, words run together or split, a stray filler. `mishear(text, rng)`
returns one wrong version, `variants(text, n)` several. Deterministic for a given seed.
"""

from __future__ import annotations

import random
import re

# (what was said, ways Whisper has heard it)
CONFUSIONS = {
    "remy": ["Rennel", "Remmy", "Rémi", "Remi", "Ramy", "Rainey"],
    "asha": ["Asia", "Usha", "Aysha", "Asher", "Ashe", "Aisha"],
    "red": ["Rad", "Read", "Rid", "Ret", "Ryde"],
    "edge": ["age", "H", "etch"],
    "youtube": ["you tube", "YouTube's", "U tube"],
    "chrome": ["crome", "chrom"],
    "notepad": ["not pad", "note pad"],
    "believer": ["be lever", "believe her"],
    "timer": ["time", "timber", "time her"],
    "minutes": ["minute", "minuets"],
    "weather": ["whether", "weather's"],
    "screen": ["scream", "screen's"],
    "volume": ["volumes", "volume up"],
    "downloads": ["download", "down loads"],
    "settings": ["setting", "sitting"],
    "spotify": ["spot a fie", "spotty fly"],
    "play": ["plays", "pray", "lay"],
    "open": ["opened", "opening", "oh pen"],
    "stop": ["stock", "top"],
    "remind": ["reminded", "re mind"],
    "what's": ["what is", "watts"],
    "right now": ["right know", "ride now"],
}
FILLERS = ["uh", "um", "so", "okay", "like"]


def _swap(text: str, rng: random.Random) -> str | None:
    options = [(k, v) for k, v in CONFUSIONS.items() if re.search(rf"\b{re.escape(k)}\b", text, re.I)]
    if not options:
        return None
    key, heard = rng.choice(options)
    return re.sub(rf"\b{re.escape(key)}\b", rng.choice(heard), text, count=1, flags=re.I)


def _drop_edge_word(text: str, rng: random.Random) -> str | None:
    words = text.split()
    if len(words) < 4:
        return None
    return " ".join(words[1:]) if rng.random() < 0.5 else " ".join(words[:-1])


def _filler(text: str, rng: random.Random) -> str:
    words = text.split()
    at = rng.randint(0, max(0, len(words) - 1))
    words.insert(at, rng.choice(FILLERS))
    return " ".join(words)


def _no_punctuation(text: str, rng: random.Random) -> str:
    return re.sub(r"[.,!?]", "", text).lower()


def mishear(text: str, rng: random.Random | None = None) -> str:
    rng = rng or random.Random(0)
    makers = [_swap, _swap, _drop_edge_word, _filler, _no_punctuation]
    rng.shuffle(makers)
    for make in makers:
        out = make(text, rng)
        if out and out.strip() and out != text:
            return out
    return text


def variants(text: str, n: int = 3, seed: int = 0) -> list[str]:
    rng = random.Random(f"{seed}:{text}")
    seen: list[str] = []
    for _ in range(n * 6):
        v = mishear(text, rng)
        if v not in seen and v != text:
            seen.append(v)
        if len(seen) >= n:
            break
    return seen
