"""Companion packs: who Red is, and who else can be there instead (plan.md 0.2).

A companion is data, not code: a folder `companions/<id>/` with `companion.toml` (name, wake
names, voice, look, humour, chattiness, temper, likes, idle switches) and `persona.md` (who they
are, how they talk, example exchanges). Red ships five (red, remy, asha, bruno, winston).

The user's edits live in `RED_HOME\\companions\\<id>\\` and win **field by field**: a
`companion.toml` there that only says `humour = "cheeky"` changes only that (and `[voice]` or
`[idle]` merge key by key); a `persona.md` there replaces the shipped one. A folder with a new
id there is a companion of its own.

The active companion is `RED_COMPANION`, else the `"companion"` key of `RED_HOME\\cache\\companion.json`
(the avatar writes it too), else Red. `set_active()` saves the choice and emits the
`companion(id)` event; chat, the voice (red/tts) and the avatar follow it.
"""

from __future__ import annotations

import json
import logging
import os
import re
import tomllib
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from . import events

log = logging.getLogger(__name__)

DEFAULT_ID = "red"
ID_PATTERN = re.compile(r"[a-z][a-z0-9_-]{0,31}")
HUMOUR = ("off", "light", "normal", "cheeky")
CHATTINESS = ("quiet", "friendly", "chatty", "companion")
TEMPER = ("low", "medium", "high")
IDLE_SWITCHES = ("look_around", "sleep", "wander", "grumble", "music")
# Kinds of taste a pack can list under [taste]: opinions and favourites, never experiences.
TASTE_KINDS = ("music", "hates", "artists", "games", "films", "anime", "food", "books", "takes")
MOODS = ("calm", "focus", "chill", "hype", "sad", "drive")
MAX_PERSONA = 3500                       # characters of persona.md that go into the prompt
SHIPPED_DIR = Path(__file__).resolve().parents[1] / "companions"


@dataclass(frozen=True)
class Favourite:
    """One of a companion's own songs: `songs = [["title", "artist", "why", "moods"], ...]`."""
    title: str
    artist: str
    why: str = ""                         # said in one line when it's picked
    moods: tuple[str, ...] = ()

    @property
    def query(self) -> str:
        """What to search for: never "whatever", always a real title and artist."""
        return f"{self.title} {self.artist}"


@dataclass(frozen=True)
class Companion:
    id: str
    name: str
    persona: str = ""
    wake: tuple[str, ...] = ()
    aliases: tuple[str, ...] = ()         # how speech-to-text mishears the name ("rennel" for Remy)
    tagline: str = ""
    hello: str = ""                       # said when the user switches to this companion
    voice: dict = field(default_factory=lambda: {"engine": "kokoro", "id": "af_heart", "speed": 1.0})
    voices: tuple[str, ...] = ()
    sounds: str = ""
    avatar: str = ""                      # RED_HOME\models\companion\<avatar>; "" = no look yet (text only)
    humour: str = "normal"
    chattiness: str = "friendly"
    temper: str = "medium"
    likes: tuple[str, ...] = ()
    idle: dict = field(default_factory=lambda: dict.fromkeys(IDLE_SWITCHES, True))
    songs: tuple[Favourite, ...] = ()     # their own favourites ("play whatever you like")
    taste: dict = field(default_factory=dict)     # kind -> tuple of opinion lines (TASTE_KINDS)
    folders: tuple[Path, ...] = ()        # where it was read from (shipped, then the user's)

    @property
    def voice_id(self) -> str:
        return str(self.voice.get("id") or "af_heart")

    @property
    def text_only(self) -> bool:
        return not self.avatar

    def likes_music(self) -> bool:
        return any("music" in like or "song" in like for like in self.likes)

    def allows(self, switch: str) -> bool:
        """An idle switch (look_around, sleep, wander, grumble, music)."""
        return bool(self.idle.get(switch, True))


# --- schema ----------------------------------------------------------------------------------

def problems(data: dict) -> list[str]:
    """Everything wrong with a companion.toml's content ([] when it's fine)."""
    out: list[str] = []

    def kind(key: str, types, label: str) -> bool:
        if key in data and not isinstance(data[key], types):
            out.append(f"{key} must be {label}")
            return False
        return key in data

    cid = data.get("id")
    if not isinstance(cid, str) or not ID_PATTERN.fullmatch(cid):
        out.append("id must be lowercase letters, digits, - or _")
    if not isinstance(data.get("name"), str) or not data.get("name", "").strip():
        out.append("name is required")
    if kind("wake", list, "a list of phrases") and not all(isinstance(w, str) and w.strip() for w in data["wake"]):
        out.append("wake must hold phrases")
    if kind("aliases", list, "a list of words") and not all(isinstance(w, str) and w.strip() for w in data["aliases"]):
        out.append("aliases must hold words")
    if kind("songs", list, 'a list like [["title", "artist", "why", "moods"], ...]'):
        for song in data["songs"]:
            if (not isinstance(song, list) or not 2 <= len(song) <= 4
                    or not all(isinstance(x, str) for x in song) or not all(x.strip() for x in song[:2])):
                out.append('songs must hold ["title", "artist", "why", "moods"] lists')
                break
    if kind("taste", dict, "a table of lists of opinions"):
        for key, value in data["taste"].items():
            if key not in TASTE_KINDS:
                out.append(f"taste.{key} isn't a kind of taste ({', '.join(TASTE_KINDS)})")
            elif not isinstance(value, list) or not all(isinstance(x, str) for x in value):
                out.append(f"taste.{key} must be a list of opinions")
    for key in ("tagline", "hello", "sounds", "avatar"):
        kind(key, str, "text")
    if kind("voice", dict, "a table like { engine = \"kokoro\", id = \"am_michael\", speed = 1.0 }"):
        voice = data["voice"]
        if not isinstance(voice.get("id", ""), str):
            out.append("voice.id must be text")
        speed = voice.get("speed", 1.0)
        if isinstance(speed, bool) or not isinstance(speed, (int, float)) or not 0.7 <= speed <= 1.5:
            out.append("voice.speed must be a number from 0.7 to 1.5")
    if kind("voices", list, "a list of voice ids") and not all(isinstance(v, str) for v in data["voices"]):
        out.append("voices must hold voice ids")
    for key, choices in (("humour", HUMOUR), ("chattiness", CHATTINESS), ("temper", TEMPER)):
        if kind(key, str, "text") and data[key] not in choices:
            out.append(f"{key} must be one of {', '.join(choices)}")
    if kind("likes", list, "a list of words") and not all(isinstance(x, str) for x in data["likes"]):
        out.append("likes must hold words")
    if kind("idle", dict, "a table of true/false switches"):
        for key, value in data["idle"].items():
            if key not in IDLE_SWITCHES:
                out.append(f"idle.{key} isn't an idle switch ({', '.join(IDLE_SWITCHES)})")
            elif not isinstance(value, bool):
                out.append(f"idle.{key} must be true or false")
    return out


# --- loading ---------------------------------------------------------------------------------

def user_dir(home: Path | str | None = None) -> Path:
    from .config import red_home
    return Path(home or red_home()) / "companions"


def _read_toml(path: Path) -> dict:
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as e:
        log.warning("Couldn't read %s: %s", path, e)
        return {}


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return ""


def _merge(base: dict, over: dict) -> dict:
    """The user's fields win; the tables `voice` and `idle` merge key by key. A field of the
    wrong type is ignored (with a log line), so a typo can't break a companion."""
    merged = dict(base)
    for key, value in over.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict) and key in ("voice", "idle", "taste"):
            merged[key] = {**merged[key], **value}
        else:
            merged[key] = value
    return merged


def _clean(data: dict) -> dict:
    """Drop the fields that fail the schema, one by one, so the rest still applies."""
    bad = problems(data)
    if not bad:
        return data
    cleaned = dict(data)
    for message in bad:
        key = message.split(" ")[0].split(".")[0]
        log.warning("Companion %s: %s (ignored)", data.get("id", "?"), message)
        if key in cleaned and key not in ("id", "name"):
            cleaned.pop(key)
        elif key == "idle":
            cleaned.pop("idle", None)
    return cleaned


def _clean_layer(layer: dict, cid: str) -> dict:
    """One file's fields without the broken ones, so a typo in the user's file falls back to the
    shipped value instead of to nothing."""
    if not layer:
        return layer
    cleaned = _clean({"name": cid.title(), **layer, "id": cid})
    cleaned.pop("id", None)
    if "name" not in layer:
        cleaned.pop("name", None)
    return cleaned


def available(home: Path | str | None = None, shipped: Path | None = None) -> list[str]:
    """Every companion id: the shipped ones first, then the user's own."""
    ids: list[str] = []
    for root in (shipped or SHIPPED_DIR, user_dir(home)):
        try:
            folders = sorted(p for p in root.iterdir() if p.is_dir())
        except OSError:
            continue
        for folder in folders:
            if ID_PATTERN.fullmatch(folder.name) and folder.name not in ids and (
                    (folder / "companion.toml").is_file() or (folder / "persona.md").is_file()):
                ids.append(folder.name)
    return ids


def load(companion_id: str, home: Path | str | None = None, shipped: Path | None = None) -> Companion:
    """The companion `companion_id`, the shipped pack with the user's edits on top.

    An id with no pack at all still loads (a model added with avatar_render's add.py): its name
    is the id, with no persona.
    """
    cid = (companion_id or DEFAULT_ID).strip().lower()
    folders = [(shipped or SHIPPED_DIR) / cid, user_dir(home) / cid]
    data: dict = {}
    persona = ""
    for folder in folders:
        data = _merge(data, _clean_layer(_read_toml(folder / "companion.toml"), cid))
        persona = _read_text(folder / "persona.md") or persona
    data["id"] = cid
    data.setdefault("name", cid.title())
    data = _clean(data)
    base = Companion(id=cid, name=str(data["name"]))
    return Companion(
        id=cid,
        name=str(data["name"]).strip() or cid.title(),
        persona=persona[:MAX_PERSONA],
        wake=tuple(w.lower().strip() for w in data.get("wake", ()) if str(w).strip()),
        tagline=data.get("tagline", ""),
        hello=data.get("hello", ""),
        voice={**base.voice, **data.get("voice", {})},
        voices=tuple(data.get("voices", ())),
        sounds=data.get("sounds", ""),
        avatar=data.get("avatar", ""),
        humour=data.get("humour", base.humour),
        chattiness=data.get("chattiness", base.chattiness),
        temper=data.get("temper", base.temper),
        likes=tuple(data.get("likes", ())),
        idle={**base.idle, **data.get("idle", {})},
        aliases=tuple(a.lower().strip() for a in data.get("aliases", ()) if a.strip()),
        songs=tuple(_favourite(s) for s in data.get("songs", ())),
        taste={k: tuple(v) for k, v in data.get("taste", {}).items()},
        folders=tuple(f for f in folders if f.is_dir()),
    )


def _favourite(row: list[str]) -> Favourite:
    title, artist, why, moods = (list(row) + ["", ""])[:4]
    return Favourite(title.strip(), artist.strip(), why.strip(),
                     tuple(m for m in moods.lower().split() if m in MOODS))


def taste_terms(companion: Companion) -> list[str]:
    """The names in a companion's taste (song titles and artists), for checks and evals."""
    terms = []
    for song in companion.songs:
        terms += [song.title, song.artist]
    return [t for t in terms if len(t) > 3]


def load_all(home: Path | str | None = None, shipped: Path | None = None) -> dict[str, Companion]:
    return {cid: load(cid, home, shipped) for cid in available(home, shipped)}


# --- the active one ---------------------------------------------------------------------------

def state_path(home: Path | str | None = None) -> Path:
    from .config import red_home
    return Path(home or red_home()) / "cache" / "companion.json"


def active_id(home: Path | str | None = None, environ=None) -> str:
    """RED_COMPANION, else the saved choice (RED_HOME\\cache\\companion.json), else Red."""
    env = (environ if environ is not None else os.environ).get("RED_COMPANION", "").strip().lower()
    if env and ID_PATTERN.fullmatch(env):
        return env
    try:
        saved = json.loads(state_path(home).read_text(encoding="utf-8")).get("companion")
    except (OSError, ValueError, AttributeError):
        saved = None
    if isinstance(saved, str) and ID_PATTERN.fullmatch(saved.lower()):
        return saved.lower()
    return DEFAULT_ID


def active(home: Path | str | None = None, environ=None, shipped: Path | None = None) -> Companion:
    return load(active_id(home, environ), home, shipped)


def set_active(companion_id: str, home: Path | str | None = None) -> Companion:
    """Make `companion_id` the one on duty: save it (keeping the avatar's spot in the same file)
    and tell everyone with `events.emit("companion", id=...)`. Raises ValueError for an id with
    no pack and no look."""
    cid = companion_id.strip().lower()
    if not ID_PATTERN.fullmatch(cid):
        raise ValueError(f"{companion_id!r} isn't a companion id")
    path = state_path(home)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            data = {}
    except (OSError, ValueError):
        data = {}
    data["companion"] = cid
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding="utf-8")
    except OSError:
        log.warning("Couldn't save the active companion", exc_info=True)
    if os.environ.get("RED_COMPANION", "").strip():
        os.environ["RED_COMPANION"] = cid       # the setting would otherwise win over the choice
    companion = load(cid, home)
    events.emit("companion", id=cid)
    return companion


# --- names, as speech-to-text hears them ------------------------------------------------------------

MIN_SIMILARITY = 0.75          # 1 - edit distance / length, on the sound keys below
_GREETING = re.compile(r"^(?:(?:hey|hi|hello|hiya|yo|oi|ok|okay|please|um|uh)\b[\s,.!]*)+")
_SOUNDS = (("ph", "f"), ("ck", "k"), ("ch", "sh"), ("c", "k"), ("q", "k"), ("x", "ks"), ("z", "s"),
           ("ee", "i"), ("ie", "i"), ("ey", "i"), ("y", "i"))
_VOWELS = set("aeiou")
_NAME_CACHE: dict = {}
_NAME_CACHE_SECONDS = 5.0


def _plain(word: str) -> str:
    """'Rémy's' -> 'remy': lower case, accents off, letters only."""
    word = unicodedata.normalize("NFKD", word.lower())
    word = "".join(c for c in word if not unicodedata.combining(c))
    word = re.sub(r"['’]s$", "", word)
    return re.sub(r"[^a-z]", "", word)


def sound_key(word: str) -> str:
    """A rough key for how a word sounds: 'Remmy', 'Remi' and 'Remy' all give 'remi'."""
    key = _plain(word)
    for spelled, sounds in _SOUNDS:
        key = key.replace(spelled, sounds)
    return re.sub(r"(.)\1+", r"\1", key)            # doubled letters sound single


def _distance(a: str, b: str) -> int:
    """Edit distance with swaps of two neighbours ('Burno' is one step from 'Bruno')."""
    d = [[i + j if i * j == 0 else 0 for j in range(len(b) + 1)] for i in range(len(a) + 1)]
    for i in range(1, len(a) + 1):
        for j in range(1, len(b) + 1):
            cost = a[i - 1] != b[j - 1]
            d[i][j] = min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + cost)
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                d[i][j] = min(d[i][j], d[i - 2][j - 2] + 1)
    return d[-1][-1]


def name_similarity(heard: str, name: str) -> float:
    """How alike `heard` and `name` sound, 0..1. Names of three letters or fewer ('Red') only
    match exactly: 'Fred' or 'bed' must never wake Red. The first sound must agree too (any
    vowel with any vowel: 'Usha' for 'Asha')."""
    a, b = sound_key(heard), sound_key(name)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if len(b) <= 3 or len(a) < 4:
        return 0.0
    if a[0] != b[0] and not (a[0] in _VOWELS and b[0] in _VOWELS):
        return 0.0
    return 1.0 - _distance(a, b) / max(len(a), len(b))


def _name_table(home, shipped) -> list[tuple[str, set[str], set[str]]]:
    """(id, names, alias keys) for every companion; re-read at most every few seconds."""
    import time
    cache_key = (str(home), str(shipped))
    hit = _NAME_CACHE.get(cache_key)
    if hit and time.monotonic() - hit[0] < _NAME_CACHE_SECONDS:
        return hit[1]
    table = []
    for cid in available(home, shipped):
        c = load(cid, home, shipped)
        names = {cid, _plain(c.name)} | {_plain(w.removeprefix("hey ")) for w in c.wake if " " not in w.removeprefix("hey ")}
        table.append((cid, {n for n in names if n}, {sound_key(a) for a in c.aliases}))
    _NAME_CACHE[cache_key] = (time.monotonic(), table)
    return table


def match_name(text: str, home: Path | str | None = None, shipped: Path | None = None, *,
               fuzzy: bool = True) -> str | None:
    """The companion whose name `text` is, as speech-to-text writes it: 'Remmy', 'Rennel', 'Rami' ->
    'remy'; 'Usha', 'Asia', 'Aysha' -> 'asha'; 'hey Winsten' -> 'winston'. None when no name fits
    ('my mom', 'remind', 'Fred').

    `text` is the words where a name is expected (after "switch to", "talk to", "bring", or
    after "hey" for waking); only its first three words count. A name matches by its sound key
    (red/companions sound_key) and edit distance (MIN_SIMILARITY), or a pack's `aliases`
    exactly. `fuzzy=False`: the name, its wake word or an alias exactly."""
    text = _GREETING.sub("", " ".join(text.lower().split()))
    words = [w for w in (_plain(w) for w in re.split(r"[\s,.!?;:-]+", text)) if w][:3]
    heard = words + [a + b for a, b in zip(words, words[1:])]      # "win ston"
    best, best_id, tied = 0.0, None, False
    for cid, names, alias_keys in _name_table(home, shipped):
        for word in heard:
            key = sound_key(word)
            score = 1.0 if (key in alias_keys or any(key == sound_key(n) for n in names)) else 0.0
            if not score and fuzzy:
                score = max((name_similarity(word, n) for n in names), default=0.0)
            if score > best:
                best, best_id, tied = score, cid, False
            elif score == best and score > 0 and cid != best_id:
                tied = True
    if best >= MIN_SIMILARITY and not (tied and best < 1.0):
        return best_id
    return None


# --- "switch to Remy" -------------------------------------------------------------------------

_SWITCH = re.compile(
    r"^(?:(?:hey|okay|ok|please)(?: \w+)?[, ]+)*(?:can you |could you |i want to |i wanna |i'd like to |let me )?"
    r"(?P<verb>(?:switch|change|swap|go|come back|bring back|bring in|bring|put on|get)\b(?: me)?(?: over)?(?: back)?"
    r"(?: to| with| for)?|talk to|talk with|speak (?:to|with)|call in|be)\s+"
    r"(?:the )?(?:companion |character |friend )?(?P<who>[a-z][a-z' -]{0,30}?)"
    r"(?:\s+(?:please|now|instead|back|here|over|in))*\s*[.!?]?$",
    re.IGNORECASE)
# "Go to Asia" is a trip, not Asha: after these verbs only an exact name counts.
_LOOSE_VERBS = re.compile(r"^(?:go|get|put on|be)\b")


def switch_target(said: str, home: Path | str | None = None, shipped: Path | None = None) -> str | None:
    """The companion id when `said` asks to switch to one ("switch to Remy", "let me talk to Asha",
    "bring Remy back", "go back to Red"), else None. The name is matched by sound (`match_name`:
    "switch to Rennel" is Remy), so only companions that exist count: "talk to my mom" or
    "switch to dark mode" are never taken for it."""
    text = " ".join(said.lower().replace(",", " ").split())
    m = _SWITCH.match(text)
    if not m:
        return None
    who = m.group("who").strip(" '")
    who = re.sub(r"^(?:back to |to )", "", who)
    words = who.split()
    if not words or len(words) > 2 or re.search(r"['’]s\b", who):      # "go to Remy's house"
        return None
    name = "".join(words)                                               # "win ston"
    if _LOOSE_VERBS.match(m.group("verb")):
        plain = _plain(name)
        return next((cid for cid, names, _ in _name_table(home, shipped) if plain in names), None)
    return match_name(name, home, shipped)


def handle_switch(said: str, home: Path | str | None = None) -> str | None:
    """If `said` asks to switch companions, do it and return what the new companion says
    (spoken in the new voice: the voice follows the `companion` event). Else None."""
    cid = switch_target(said, home)
    if cid is None:
        return None
    current = active_id(home)
    companion = set_active(cid, home) if cid != current else load(cid, home)
    if cid == current:
        return f"I'm already {companion.name}."
    return companion.hello or f"{companion.name} here."


__all__ = ["Companion", "Favourite", "active", "active_id", "available", "handle_switch", "load", "load_all",
           "match_name", "name_similarity", "problems", "set_active", "sound_key", "switch_target", "taste_terms"]
