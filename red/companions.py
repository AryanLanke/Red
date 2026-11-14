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
MAX_PERSONA = 3500                       # characters of persona.md that go into the prompt
SHIPPED_DIR = Path(__file__).resolve().parents[1] / "companions"


@dataclass(frozen=True)
class Companion:
    id: str
    name: str
    persona: str = ""
    wake: tuple[str, ...] = ()
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
        if isinstance(value, dict) and isinstance(merged.get(key), dict) and key in ("voice", "idle"):
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
        data = _merge(data, _read_toml(folder / "companion.toml"))
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
        folders=tuple(f for f in folders if f.is_dir()),
    )


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


# --- "switch to Remy" -------------------------------------------------------------------------

_SWITCH = re.compile(
    r"^(?:(?:hey|okay|ok|please)(?: \w+)?[, ]+)*(?:can you |could you |i want to |i'd like to |let me )?"
    r"(?:(?:switch|change|swap|go|come back|bring back|bring in|put on|get)\b(?: me)?(?: over)?(?: back)?"
    r"(?: to| with| for)?|talk to|speak (?:to|with)|call in|be)\s+"
    r"(?:the )?(?:companion |character |friend )?(?P<who>[a-z][a-z' -]{0,30}?)\s*(?:please|now|instead)?[.!?]?$",
    re.IGNORECASE)


def switch_target(said: str, home: Path | str | None = None, shipped: Path | None = None) -> str | None:
    """The companion id when `said` asks to switch to one ("switch to Remy", "let me talk to Asha",
    "go back to Red"), else None. Only names of companions that exist count, so "talk to my
    mom" or "switch to dark mode" are never taken for it."""
    text = " ".join(said.lower().replace(",", " ").split())
    m = _SWITCH.match(text)
    if not m:
        return None
    who = m.group("who").strip(" '")
    who = re.sub(r"^(?:back to |to )", "", who)
    for cid in available(home, shipped):
        companion = load(cid, home, shipped)
        names = {cid, companion.name.lower(), *(w.removeprefix("hey ").strip() for w in companion.wake)}
        if who in names:
            return cid
    return None


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


__all__ = ["Companion", "active", "active_id", "available", "handle_switch", "load", "load_all",
           "problems", "set_active", "switch_target"]
