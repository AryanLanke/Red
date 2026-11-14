"""A companion's own taste: opinions and favourite songs, and "play whatever you like".

Each pack (companions/<id>/companion.toml) lists its taste as opinions, never experiences:
`[taste]` (music, hates, artists, games, films, anime, food, books, takes) and `songs`
(title, artist, why, moods). The persona stays short: chat puts only the 3-5 lines that fit
what the user just said into the turn's prompt (`for_prompt`), after the cached system prompt.

"Play whatever you like", "surprise me", "play something calm", "your favourite song": the
companion picks one of its own songs (`own_pick`), never the same one twice in a row (the last
picks are kept in RED_HOME\\cache\\taste.json), and says in one line what and why ("Putting on
Come Together by The Beatles. McCartney's bassline does all the work."). The search is always
the real title and artist, never the user's "whatever".
"""

from __future__ import annotations

import json
import logging
import random
import re
import threading
from dataclasses import dataclass
from pathlib import Path

from .companions import Companion, Favourite

log = logging.getLogger(__name__)

MAX_LINES = 5
RECENT = 10                      # never one of the last few picks (fewer when the list is short)

_TOPICS = {
    "music": r"music|songs?|bands?|artists?|singers?|albums?|listen\w*|playlists?|genres?|rap|hip[- ]?hop|rock|jazz|"
             r"pop|metal|k-?pop|classical|edm|concerts?|guitar|piano|drums|lyrics|tunes?|beats?|soundtracks?",
    "games": r"games?|gaming|gamer|steam|elden ring|minecraft|fortnite|valorant|zelda|console|xbox|playstation|ps5|nintendo",
    "films": r"movies?|films?|cinema|shows?|series|netflix|tv|watch(?:ing|ed)?",
    "anime": r"anime|manga|ghibli",
    "food": r"food|eat|eating|hungry|cook|cooking|dinner|lunch|breakfast|pizza|pineapple|snacks?|coffee|tea|chai|"
            r"biryani|ramen|dessert|burger|pasta",
    "books": r"books?|reading|novels?|authors?",
}
_TOPIC_RE = {k: re.compile(rf"\b(?:{v})\b", re.I) for k, v in _TOPICS.items()}
# The user opens the door to an opinion: asks for a favourite, a take, a pick.
_DOOR = re.compile(r"\b(?:favou?rites?|fave|hot takes?|opinions?|recommend|suggest|best|worst|overrated|underrated|"
                   r"prefer|do you (?:like|love|hate|rate|think)|what do you think|what are you into|you into|"
                   r"what'?s good|any good)\b|\b\w+ or \w+\?\s*$", re.I)
_HELP = re.compile(r"\b(?:help|stuck|can'?t (?:focus|sleep|decide|start|calm)|bored|procrastinat\w*|stressed|anxious)\b", re.I)
# Hurting: no favourites unless they ask for one.
_SERIOUS = re.compile(r"\b(?:lonely|depressed|sad|upset|crying|cried|hurt|scared|anxious|died|death|funeral|"
                      r"broke up|breakup|hate myself|worthless|panic|grief|grieving|alone)\b", re.I)
_MOOD_WORDS = {
    "calm": r"calm|calming|relax|relaxing|relaxed|unwind|sleep|sleepy|soft|gentle|quiet|peaceful|stress|stressed|anxious",
    "focus": r"focus|focusing|study|studying|homework|exam|exams|work|working|code|coding|concentrate|concentration",
    "chill": r"chill|chilled|chilling|mellow|lazy|easy",
    "hype": r"hype|upbeat|happy|party|dance|dancing|celebrate|celebrating|energy|energetic|workout|gym|pump|fun|loud|"
            r"cheer me up|good mood",
    "sad": r"sad|cry|crying|breakup|heartbroken|heartbreak|miss|missing|melancholy",
    "drive": r"drive|driving|road trip|car ride",
}
_MOOD_RE = {k: re.compile(rf"\b(?:{v})\b", re.I) for k, v in _MOOD_WORDS.items()}

# --- "play whatever you like" ----------------------------------------------------------------------

_PICK = re.compile(
    r"\b(?:whatever|anything|something|what|one|a song|a track|some music|music|a tune|songs?)\s+"
    r"(?:you(?:'d)?\s+(?:like|love|want|pick|choose|prefer|enjoy|recommend|feel like|think|play|put on|"
    r"would (?:like|pick|choose|play))|of yours)"
    r"|\b(?:your|ur) (?:own |personal |all[- ]time )?(?:favou?rites?|fave|faves|choice|pick|kind of music|taste|"
    r"style|jam|song|songs|music)\b"
    r"|\byou (?:pick|choose|decide)\b|\bsurprise me\b|\bdealer'?s choice\b|\brandom (?:song|track|music)\b"
    r"|\bsomething good\b|\bsomething nice\b|\bsomething cool\b", re.I)
_NAMED_SOMETHING = re.compile(r"\b(?:by|from|of|called|named|like)\b\s+(?!you\b|yours\b)\w", re.I)
_FILLER = re.compile(r"\b(?:play|put on|throw on|me|us|please|for me|for us|on youtube|now|a|an|the|some|any|just|"
                     r"maybe|little|bit|kind of|kinda|type of|song|songs|music|tune|tunes|track|tracks|something|"
                     r"anything|whatever|stuff|to|for|with|while|i|am|i'm|im|we|are|go|good|nice|"
                     r"mix|playlist)\b", re.I)


def mood_of(text: str) -> str | None:
    """'something to study to' -> 'focus'; None when no mood is named."""
    for mood, pattern in _MOOD_RE.items():
        if pattern.search(text or ""):
            return mood
    return None


def wants_own_pick(query: str) -> bool:
    """'whatever you like', 'surprise me', 'your favourite', 'something calm', 'some music': the
    companion chooses. 'something by Queen', 'Believer' or 'lofi beats' are the user's own choice."""
    q = " ".join(str(query or "").lower().replace("’", "'").split()).strip(" .!?,")
    if not q or _NAMED_SOMETHING.search(q):          # "your song by Elton John" is a request
        return False
    if _PICK.search(q):
        return True
    rest = q
    for pattern in _MOOD_RE.values():
        rest = pattern.sub(" ", rest)
    rest = _FILLER.sub(" ", rest)
    return not re.sub(r"[^a-z0-9]+", "", rest)


@dataclass(frozen=True)
class Pick:
    song: Favourite
    line: str                    # what the companion says: what, and why, in one line

    @property
    def query(self) -> str:
        return self.song.query


_LEADS = {
    "red": ["Putting on {song}.", "{song}. Trust me.", "Here's {song}."],
    "remy": ["Ooh, {song}!", "Okay, {song}! Turn it up.", "This one: {song}!"],
    "asha": ["Let's have {song}.", "Okay, {song}.", "I'd pick {song}."],
    "bruno": ["{song}. Turn it up.", "Fine. {song}.", "{song}. Loud."],
    "winston": ["Allow me: {song}.", "{song}, I think.", "Might I suggest {song}."],
}
_GENERIC_LEADS = ["Putting on {song}."]
_lock = threading.Lock()


def _state_path(home) -> Path:
    from .config import red_home
    return Path(home or red_home()) / "cache" / "taste.json"


def _recent(home, cid: str) -> list[str]:
    try:
        data = json.loads(_state_path(home).read_text(encoding="utf-8"))
        recent = data.get("recent", {}).get(cid, [])
        return [str(t) for t in recent] if isinstance(recent, list) else []
    except (OSError, ValueError, AttributeError):
        return []


def _remember(home, cid: str, title: str, keep: int) -> None:
    path = _state_path(home)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("recent"), dict):
            data = {"recent": {}}
    except (OSError, ValueError):
        data = {"recent": {}}
    recent = [t for t in data["recent"].get(cid, []) if t != title] + [title]
    data["recent"][cid] = recent[-keep:] if keep > 0 else []
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding="utf-8")
    except OSError:
        log.warning("Couldn't save the last song picks", exc_info=True)


def pick_song(companion: Companion, *, mood: str | None = None, rng: random.Random | None = None,
              home=None) -> Favourite | None:
    """One of the companion's own songs: of the mood when it has one, never one of the last picks."""
    songs = list(companion.songs)
    if not songs:
        return None
    rng = rng or random.Random()
    with _lock:
        keep = min(RECENT, len(songs) - 1)
        history = _recent(home, companion.id)
        recent = set(history[-keep:]) if keep > 0 else set()
        last = history[-1] if history else None
        fresh = [s for s in songs if s.title not in recent] or songs
        moody = [s for s in songs if mood in s.moods] if mood else []
        # The mood comes first ("something calm" is calm even if it was played lately), but never
        # the same song twice in a row.
        pool = ([s for s in moody if s.title not in recent] or [s for s in moody if s.title != last] or moody
                if moody else fresh)
        song = rng.choice(pool)
        _remember(home, companion.id, song.title, keep)
    return song


def pick_line(companion: Companion, song: Favourite, rng: random.Random | None = None) -> str:
    """'Putting on Come Together by The Beatles. McCartney's bassline does all the work.'"""
    rng = rng or random.Random()
    lead = rng.choice(_LEADS.get(companion.id, _GENERIC_LEADS)).format(song=f"{song.title} by {song.artist}")
    return f"{lead} {song.why}".strip()


def own_pick(query: str, companion: Companion, *, home=None, rng: random.Random | None = None) -> Pick | None:
    """The companion's pick for "play whatever you like" (None when it has no songs of its own)."""
    song = pick_song(companion, mood=mood_of(query), rng=rng, home=home)
    if song is None:
        return None
    return Pick(song, pick_line(companion, song, rng))


# --- taste in the chat prompt ---------------------------------------------------------------------

def _song_line(song: Favourite) -> str:
    return f'"{song.title}" by {song.artist}: {song.why}'.strip()


def for_prompt(companion: Companion | None, said: str, rng: random.Random | None = None) -> str:
    """3-5 of the companion's opinions and songs that fit what the user just said, as prompt text;
    one stray opinion for plain chat; nothing when they're hurting (unless they ask)."""
    if companion is None or not (companion.taste or companion.songs):
        return ""
    rng = rng or random.Random()
    text = said or ""
    taste = companion.taste
    topics = [t for t, pattern in _TOPIC_RE.items() if pattern.search(text)]
    door = bool(_DOOR.search(text))
    mood = mood_of(text)
    helping = bool(_HELP.search(text))
    if _SERIOUS.search(text) and not door and not topics and not helping:
        return ""

    def some(kind: str, n: int) -> list[str]:
        items = list(taste.get(kind, ()))
        return rng.sample(items, min(n, len(items)))

    def songs(n: int) -> list[str]:
        pool = [s for s in companion.songs if mood in s.moods] if mood else []
        pool = pool or list(companion.songs)
        return [_song_line(s) for s in rng.sample(pool, min(n, len(pool)))]

    lines: list[str] = []
    if "music" in topics:
        lines += some("music", 1) + songs(2) + some("artists", 1)
        if door:
            lines += some("hates", 1)
    for topic in topics:
        if topic != "music":
            lines += some(topic, 2)
    if door and not topics:
        kinds = [k for k in ("music", "games", "films", "anime", "food", "artists") if taste.get(k)]
        lines += some("takes", 1) + [x for k in rng.sample(kinds, min(3, len(kinds))) for x in some(k, 1)]
    if helping and mood and not lines:
        lines += songs(2)
    if lines:
        head = ("Your own taste, for this (opinions, not things you did; if it fits, bring one in, "
                "in your own words):")
        return head + "\n" + "\n".join(f"- {x}" for x in lines[:MAX_LINES])
    pool = list(taste.get("takes", ())) + list(taste.get("music", ()))
    if not pool or helping:
        return ""
    return ("A thought of yours, only if it fits naturally (an opinion, not something you did):\n"
            f"- {rng.choice(pool)}")


__all__ = ["Pick", "for_prompt", "mood_of", "own_pick", "pick_line", "pick_song", "wants_own_pick"]
