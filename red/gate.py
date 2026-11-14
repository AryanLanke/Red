"""Answer at once: talk goes straight to chat, without asking the router first (plan.md 0.3 lane 2 task 2).

Every sentence used to go to the router (one model call with a 4,000-token prompt),
and only then, for talk, to the chat (a second call). On 2026-11-13 the router
alone took 1 to 32 s on "What's up?", "Don't sleep, OK?" and "You're crazy.",
before Red had said a word. Most of what people say to a companion is talk.

`needs_router(text)` is plain word matching, well under a millisecond. It sends a
sentence to the router whenever it *might* be a command or a question about the
world: a command word anywhere ("open", "play", "remind", "turn off"), an app,
site or folder name, the screen, music, a number, a question about facts ("what
is", "who made", "how tall", "do you know X") or anything fresh ("latest",
"today", "news"). Only what is clearly talk ("What's up?", "You're crazy.",
"I'm feeling lonely.", "what's on your mind") skips it. When unsure, it routes:
a slow answer is better than a command Red ignores.
"""

from __future__ import annotations

import re

from . import fastpath as _fastpath
from . import known_folders as _known

# Words that make a sentence a possible command. Matched as whole words.
_COMMAND = (
    r"open|opens|launch|start|close|quit|exit|search|google|bing|find|locate|look ?up|lookup|"
    r"play|playing|put on|pause|resume|stop|skip|next song|previous|shuffle|mute|unmute|volume|louder|quieter|"
    r"lock|turn (?:on|off|up|down)|switch (?:on|off|to)|shut ?down|shutdown|restart|reboot|sleep mode|hibernate|"
    r"set|remind|reminder|reminders|timer|alarm|notify|alert|wake me|"
    r"mail|email|e-mail|inbox|send|reply|forward|message|text|whatsapp|call|"
    r"add|delete|remove|cancel|move|copy|rename|download|install|uninstall|update|upload|save|"
    r"read|check|show|list|take|empty|clear|screenshot|record|"
    r"summary|summarize|summarise|explain|describe|translate|calculate|convert|define|spell|spelled|spelt|spelling|"
    r"compare|recommend|suggest|review|"
    r"weather|forecast|temperature|news|headlines|price|prices|cost|stock|score|"
    r"latest|newest|recent|today|tonight|tomorrow|yesterday|this week|right now on|"
    r"schedule|calendar|meeting|meetings|event|events|task|tasks|to-?do|todo|note|notes|"
    r"remember|forget|my name|call me|"
    r"repo|repos|repository|commit|build|code|git|github|"
    r"screen|window|windows|tab|tabs|folder|folders|file|files|desktop|downloads|documents|app|apps|"
    r"song|songs|music|playlist|album|artist|podcast|video|videos|movie|trailer|series|episode|spotify|youtube|"
    r"watch|watching|finish|finishes|finished|done|wait|"
    r"tell me|show me|give me|get me|bring|go to|navigate|visit|"
    r"debate|quiz|argue|discuss"
)
_COMMAND_RE = re.compile(rf"\b(?:{_COMMAND})\b")

# Apps people name; any of these in a sentence means it may be a command.
_APPS = (
    "chrome", "edge", "firefox", "brave", "opera", "vs code", "vscode", "visual studio", "notepad",
    "word", "excel", "powerpoint", "outlook", "teams", "zoom", "discord", "steam", "telegram",
    "slack", "settings", "control panel", "explorer", "file explorer", "terminal", "powershell",
    "command prompt", "calculator", "paint", "photos", "camera", "clock", "store", "task manager",
    "obs", "vlc", "claude", "chatgpt", "copilot", "cursor",
)
_NAMES = sorted({*_APPS, *_fastpath.SITES, *_known.FOLDER_IDS, *_known.ALIASES},
                key=len, reverse=True)
_NAMES_RE = re.compile(r"\b(?:%s)\b" % "|".join(re.escape(n) for n in _NAMES if n))

# A question about the world, not about Red or the user's feelings.
_FACT_QUESTION = re.compile(
    r"\b(?:what (?:time|day|date|year|month|song|movie|show|game|app)\b|what (?:is|are|was|were|does|do) (?!you\b|your\b|up\b|going\b|happening\b|wrong\b|it\b|that\b|this\b)"
    r"|what's (?!up\b|going\b|happening\b|wrong\b|on your\b|in your\b|your\b|good\b|new with you\b)"
    r"|whats (?!up\b|going\b|happening\b|wrong\b|on your\b|in your\b|your\b)"
    r"|who (?:is|was|are|were|made|makes|invented|created|wrote|won|owns|founded|directed|sang|plays)"
    r"|when (?:is|was|did|does|do|will|would)|where (?:is|was|are|can|do|does)"
    r"|which (?!one do you\b)|how (?:many|much|tall|big|far|long|old|fast|does|do i|do you make|to|is the|are the|did)"
    r"|why (?:is|are|does|do|did) (?!you\b|u\b)|is it true|is there|are there"
    r"|do you know (?!me\b|what i\b|how i\b|that i\b|i\b)|have you heard of|tell me about|know about)")

_NUMBER = re.compile(r"\d")

# Talk about Red or the user: these never need the router, even with a word above
# ("what's going on in your mind right now", "are you mad at me").
_ABOUT_US = re.compile(
    r"^(?:(?:hey|yo|so|and|but|well|okay|ok|man|bro|dude|red)[, ]+)*"
    r"(?:what'?s up|wh?at'?s going on (?:in |on )?(?:your mind|with you)|what is going on in your mind|"
    r"how are you|how you doin|how(?:'?s| is) it going|how(?:'?s| is) everything|how was your|"
    r"are you (?:mad|angry|okay|ok|there|listening|chilling|bored|tired|sleepy|happy|sad|real|alive|crazy)|"
    r"you(?:'re| are) (?:crazy|funny|weird|annoying|mean|rude|a nerd|nice|cool|great|the best|offensive|sort of)|"
    r"i(?:'m| am) (?:feeling|so|really|kind of|kinda|just|bored|tired|sad|happy|lonely|angry|sorry)|"
    r"i feel|i love you|i hate you|i miss|thank you|thanks|good (?:morning|night|evening|afternoon))\b")


def _clean(text: str) -> str:
    text = text.lower().replace("’", "'").replace("‘", "'")
    text = re.sub(r"[^\w' -]+", " ", text)
    return " ".join(text.split())


def needs_router(text: str) -> bool:
    """True when `text` might be a command or a question about the world (so it is routed).

    False only for plain talk, which goes straight to Red's chat.
    """
    words = _clean(text)
    if not words:
        return True
    if _ABOUT_US.search(words) and not _NAMES_RE.search(words) and not re.search(
            r"\b(?:open|play|remind|search|look ?up|turn (?:on|off)|shut ?down|restart|screen)\b", words):
        return False
    if _COMMAND_RE.search(words) or _NAMES_RE.search(words) or _NUMBER.search(words):
        return True
    if _FACT_QUESTION.search(words):
        return True
    # "Blink Crazy by Lisa Raffin": a short "<title> by <artist>" is a song (2026-11-09, said after a
    # misheard "play ...").
    if len(words.split()) <= 8 and re.search(r"^[\w' -]{2,40}\bby [a-z]", words):
        return True
    # "Can you X?", "could you X", "please X": a request for something, unless X is talk.
    if re.search(r"\b(?:can|could|would|will) you (?!be\b|stay\b|talk\b|listen\b|laugh\b|chill\b|"
                 r"just be\b|hear me\b|forgive\b|calm\b|relax\b|believe\b)\w+", words):
        return True
    if re.match(r"^(?:please |just |now |go |i want you to |i need you to )", words):
        return True
    return False
