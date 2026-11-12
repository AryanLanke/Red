"""Instant common commands: "open YouTube", "volume up", "pause", "lock", "shut down".

In the 23:37 voice test the model took 1.3 s of the 2.65 s for "open YouTube".
Clear, common commands don't need it. `match()` turns a sentence into a tool
call only when the whole sentence is one of the forms below; anything else
(None) goes to the model as before. Router.route() checks the call with the
same schema as a model's call, and the Executor asks the same confirmations
(shutdown and restart stay destructive, so they are still confirmed aloud).

It's plain string matching, well under a millisecond, with or without a GPU.
The words are only looked up: an app, folder or site name has to be in a
fixed list (or the allowlist), and a web address has to look like one.
"""

from __future__ import annotations

import re
from typing import Callable

from . import known_folders as _known
from .browser import named_in

# Sites people open by name. Only these names (or something.tld) become URLs.
SITES = {
    "youtube": "https://www.youtube.com", "you tube": "https://www.youtube.com",
    "youtube music": "https://music.youtube.com",
    "github": "https://github.com", "gmail": "https://mail.google.com",
    "google": "https://www.google.com", "google maps": "https://www.google.com/maps",
    "google drive": "https://drive.google.com", "google docs": "https://docs.google.com",
    "netflix": "https://www.netflix.com", "wikipedia": "https://en.wikipedia.org",
    "facebook": "https://www.facebook.com", "instagram": "https://www.instagram.com",
    "twitter": "https://x.com", "reddit": "https://www.reddit.com",
    "amazon": "https://www.amazon.com", "linkedin": "https://www.linkedin.com",
    "whatsapp web": "https://web.whatsapp.com", "chatgpt": "https://chatgpt.com",
    "hotstar": "https://www.hotstar.com", "prime video": "https://www.primevideo.com",
}
_DOMAIN = re.compile(r"(?:www\.)?[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:com|org|net|io|dev|in|co|ai|app|edu|gov|tv|me)")

# Politeness and Red's name, taken off both ends before matching.
_LEAD = re.compile(r"^(?:(?:hey|ok|okay|yo)\s+)?(?:red\b[,\s]*)?(?:(?:can|could|would|will) you\s+|"
                   r"please\s+|just\s+|go ahead and\s+|i want you to\s+)*")
_TAIL = re.compile(r"(?:\s+(?:for me|please|now|right now|red|real quick|quickly))+$")

_BROWSER_SUFFIX = re.compile(r"\s+(?:in|from|on|using|with)\s+(?:the\s+)?(?:google\s+|microsoft\s+|mozilla\s+)?"
                             r"(chrome|edge|firefox)(?:\s+browser)?$")


def normalize(text: str) -> str:
    text = text.lower().replace("’", "'").strip()
    text = re.sub(r"[.!?,;:]+$", "", text).strip()
    text = re.sub(r"\s+", " ", text)
    text = _LEAD.sub("", text)
    text = re.sub(r"\s+for me\b", "", text)          # "open YouTube for me from Chrome"
    text = _TAIL.sub("", text)
    return text.strip(" ,")


def _call(tool: str, **args) -> dict:
    return {"tool": tool, "args": args}


# --- fixed sentences ---------------------------------------------------------------

_FIXED = [
    (r"(?:turn (?:the )?volume up|volume up|turn (?:it|the sound) up|louder|increase (?:the )?volume|"
     r"raise (?:the )?volume)", _call("volume", action="up")),
    (r"(?:turn (?:the )?volume down|volume down|turn (?:it|the sound) down|quieter|lower (?:the )?volume|"
     r"decrease (?:the )?volume|reduce (?:the )?volume)", _call("volume", action="down")),
    (r"(?:mute|mute (?:it|the (?:sound|volume|pc|computer|laptop))|be muted)", _call("volume", action="mute")),
    (r"(?:unmute|unmute (?:it|the (?:sound|volume|pc|computer|laptop)))", _call("volume", action="unmute")),
    (r"pause(?: (?:it|this|that|the (?:music|song|video|track|podcast)|music|youtube|playback))?",
     _call("pause_music")),
    (r"(?:(?:resume|unpause|continue playing|keep playing)(?: (?:it|the (?:music|song|video|podcast)|music|"
     r"playing|playback))?|play|play it|continue)", _call("resume_music")),
    (r"(?:next|skip|next (?:song|track|video|one)|skip (?:it|this|this (?:song|track|video|one))|"
     r"play the next (?:song|track|video|one))", _call("next_song")),
    (r"(?:previous|previous (?:song|track|video|one)|last (?:song|track)|go back a (?:song|track)|"
     r"play the previous (?:song|track|video|one))", _call("previous_track")),
    (r"stop (?:the )?(?:music|song|video|podcast|playing|playback)", _call("stop_music")),
    (r"lock(?: (?:my|the|this) (?:pc|computer|laptop|screen|windows|system))?|lock (?:it|the pc)",
     _call("lock_pc")),
    (r"(?:what time is it|what's the time|what is the time|tell me the time|time(?: now)?|"
     r"what time is it now)", _call("tell_status", what="time")),
    (r"(?:what's the date(?: today)?|what is the date(?: today)?|what's today's date|what is today's date|"
     r"what date is it(?: today)?)", _call("tell_status", what="date")),
    (r"(?:how much battery (?:do i have|is left|have i got)(?: left)?|battery(?: level)?|"
     r"what's (?:my|the) battery(?: level)?)", _call("tell_status", what="battery")),
    (r"(?:take a screenshot|take a screen ?shot|screenshot|capture (?:the|my) screen)", _call("take_screenshot")),
]
_FIXED_RE = [(re.compile(p), c) for p, c in _FIXED]

# "shut down", "shut down in 2 hours", "restart the pc": the delay is parsed
# here, so even offline these go straight to the tool (the Executor still
# confirms, since shutdown and restart are destructive).
_DELAY_SUFFIX = r"(?:\s+in\s+(.+))?"
_DEVICE = r"(?:the|my|this)\s+(?:pc|computer|laptop|system|machine)"
_POWER = re.compile(
    r"(?:(?:shut\s?down|shutdown|power\s+off|turn\s+off)(?:\s+" + _DEVICE + r")?"
    r"|shut\s+" + _DEVICE + r"\s+down"
    r"|turn\s+" + _DEVICE + r"\s+off)" + _DELAY_SUFFIX)
_RESTART = re.compile(r"(?:restart|reboot)(?:\s+" + _DEVICE + r")?" + _DELAY_SUFFIX)
_CANCEL = re.compile(r"cancel(?:\s+the)?\s+(?:shutdown|shut\s?down|restart|reboot)")


def _delay_minutes(said: str) -> int | None:
    """'2 hours', 'half an hour', '1 hour and 30 minutes' -> minutes, or None."""
    said = " ".join(said.split())
    if re.fullmatch(r"half\s+an?\s+hour", said):
        return 30
    if re.fullmatch(r"an?\s+hour\s+and\s+a\s+half", said):
        return 90
    total, found = 0, False
    for part in re.split(r"\s*(?:and|,)\s*", said):
        if re.fullmatch(r"(?:an?|one)\s+hour", part):
            total, found = total + 60, True
            continue
        m = re.fullmatch(r"(\d+)\s*(?:hours?|hrs?|h)", part)
        if m:
            total, found = total + int(m.group(1)) * 60, True
            continue
        m = re.fullmatch(r"(\d+)\s*(?:minutes?|mins?|m)", part)
        if m:
            total, found = total + int(m.group(1)), True
            continue
        return None
    return total if found else None

_SET_VOLUME = re.compile(r"(?:set (?:the )?volume to|volume(?: to)?|turn (?:the )?volume to) (\d{1,3})(?: ?(?:percent|%))?")
_OPEN = re.compile(r"(?:open|launch|start|open up|bring up|go to) (?:the |my )?(.+?)(?: app| application| website| site| folder)?")
_PLAY = re.compile(r"(?:play|put on) (.+?)(?: on youtube)?")
_SEARCH_YT = re.compile(r"(?:search (?:on )?youtube for|search youtube|youtube search(?: for)?|find on youtube) (.+)"
                        r"|(?:search(?: for)?|find|look for) (.+?) on youtube")
_SEARCH_WEB = re.compile(r"(?:search (?:the web|online|google|the internet) for|google|search for|search) (.+)")
# A search like these is something else: a file, or a spoken answer (look_up).
_NOT_A_WEB_SEARCH = re.compile(r"\b(?:my|file|files|folder|document|pdf|tell me|explain|and|what|who|how|why)\b")
_NOT_PLAYABLE = re.compile(r"^(?:it|this|that|the next.*|next.*|the previous.*|previous.*|again)$")

# A plain fact question about a named thing goes straight to look_up: the model
# took 1.0-1.2 s to route such questions (red.log, 2026-11-09). Anything personal,
# about Red, about now (time, weather, news), on screen, a sum, or pointing back
# ("who made it") is left to the model, which knows the conversation and the tools.
_FACT = re.compile(r"(?:who (?:is|was|are|were|made|created|invented|founded|built|developed|designed|"
                   r"owns|wrote|directed|discovered|started)|what (?:is|are|was|were)|what's|"
                   r"tell me about|what do you know about) (.+)")
_NOT_A_FACT = re.compile(
    r"\b(?:my|mine|me|i|i'm|im|you|your|yours|you're|it|its|it's|this|that|these|those|they|them|"
    r"their|he|him|his|she|her|we|us|our|here|there|red|up|time|date|day|today|tonight|tomorrow|"
    r"yesterday|now|weather|temperature|rain|news|headlines|screen|battery|volume|playing|song|music|"
    r"reminder|reminders|timer|alarm|email|emails|mail|inbox|calendar|meeting|meetings|event|events|"
    r"schedule|happening|going|wrong|plan|plans|plus|minus|times|divided|multiplied|squared)\b"
    r"|\d\s*[-+*/x×^%]\s*\d")


def _browser(text: str) -> tuple[str, str | None]:
    """'youtube in edge' -> ('youtube', 'edge')."""
    m = _BROWSER_SUFFIX.search(text)
    if not m:
        return text, None
    return text[:m.start()].strip(), m.group(1)


def _open(target: str, apps: Callable[[str], bool], folders: Callable[[str], bool]) -> dict | None:
    target, browser = _browser(target)
    site = SITES.get(target)
    if site is None and _DOMAIN.fullmatch(target):
        site = "https://" + target
    if browser:
        # "open YouTube in Edge": only websites open in a browser.
        return _call("open_url", url=site, browser=browser) if site else None
    if apps(target):
        return _call("open_app", app=target)
    if folders(target):
        known = _known.canonical(target)            # "documents" -> "Documents", like the model says it
        return _call("open_folder", folder=known.capitalize() if known else target)
    if site:
        return _call("open_url", url=site)
    return None


def _known_app(name: str) -> bool:
    from .allowlist import load_allowlist
    from .tools.apps import AppPaths
    try:
        if load_allowlist().app(name) is not None:
            return True
    except Exception:  # noqa: BLE001 - a broken allowlist: let the model and the tool say so
        return False
    return AppPaths().known(name) is not None


def _known_folder(name: str) -> bool:
    if _known.canonical(name) is not None:
        return True
    from .allowlist import load_allowlist
    try:
        return load_allowlist().folder(name) is not None
    except Exception:  # noqa: BLE001
        return False


def _with_case(call: dict | None, command: str) -> dict | None:
    """Names as the user wrote them ("Edge", "Believer"): matching was done in lower case."""
    if call is None:
        return None
    for key in ("app", "folder", "query", "topic"):
        value = call["args"].get(key)
        if isinstance(value, str):
            i = command.lower().replace("’", "'").find(value)
            if i >= 0:
                call["args"][key] = command[i:i + len(value)]
    return call


def match(command: str, *, apps: Callable[[str], bool] = _known_app,
          folders: Callable[[str], bool] = _known_folder) -> dict | None:
    """A tool call for a clear, common command, or None to ask the model."""
    return _with_case(_match(normalize(command), apps, folders), " ".join(command.split()))


def _match(said: str, apps: Callable[[str], bool], folders: Callable[[str], bool]) -> dict | None:
    if not said or len(said) > 80:
        return None
    for pattern, call in _FIXED_RE:
        if pattern.fullmatch(said):
            return {"tool": call["tool"], "args": dict(call["args"])}
    m = _POWER.fullmatch(said)
    if m:
        minutes = _delay_minutes(m.group(1)) if m.group(1) else 0
        if minutes is not None:
            return _call("shutdown", minutes=minutes)
    m = _RESTART.fullmatch(said)
    if m:
        minutes = _delay_minutes(m.group(1)) if m.group(1) else 0
        if minutes is not None:
            return _call("restart", minutes=minutes)
    m = _CANCEL.fullmatch(said)
    if m:
        return _call("cancel_shutdown")
    m = _SET_VOLUME.fullmatch(said)
    if m and int(m.group(1)) <= 100:
        return _call("volume", action="set", percent=int(m.group(1)))
    m = _OPEN.fullmatch(said)
    if m:
        return _open(m.group(1).strip(), apps, folders)
    m = _SEARCH_YT.fullmatch(said)
    if m:
        query, browser = _browser((m.group(1) or m.group(2)).strip())
        args = {"query": query, "site": "youtube"}
        return _call("web_search", **args, **({"browser": browser} if browser else {})) if query else None
    m = _SEARCH_WEB.fullmatch(said)
    if m:
        query, browser = _browser(m.group(1).strip())
        if not query or _NOT_A_WEB_SEARCH.search(query) or named_in(query):
            return None
        return _call("web_search", query=query, **({"browser": browser} if browser else {}))
    m = _PLAY.fullmatch(said)
    if m:
        query = m.group(1).strip()
        if _NOT_PLAYABLE.fullmatch(query) or _BROWSER_SUFFIX.search(query):
            return None
        return _call("play_online", query=query)
    m = _FACT.fullmatch(said)
    if m and not _NOT_A_FACT.search(m.group(1)):          # the subject, not "tell me about"
        topic = re.sub(r"^(?:a|an|the)\s+", "", m.group(1).strip())
        topic = re.sub(r"\s+(?:about|all about)$", "", topic)       # "what's Punisher about"
        if len(topic) >= 2:
            return _call("look_up", topic=topic)
    return None
