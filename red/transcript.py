"""Clean what Whisper heard the way Wispr Flow does, with no model call.

People talk with ums and false starts: "Um, open Chrome, no wait, open Edge." Whisper writes
all of it down. `clean_transcript` turns that into what the speaker meant, "Open Edge.":

1. fillers go: um, uh, er, hmm; a leading "so," "well," "like," "you know," "I mean,"; a
   "like," or "you know," set off by commas ("it's, like, hard")
2. self-corrections are resolved. After a pause (a comma or full stop) comes a cue ("no wait",
   "I mean", "sorry", "scratch that", "make it", "or rather", a bare "no" or "wait") and then the
   replacement. The replacement takes the place of what it corrects:
   - it starts like something already said ("open Edge" for "open Chrome", "by Lisa" for "by
     Arijit Singh", "the documents folder" for "the downloads folder"): it replaces from there
   - it is a number ("ten minutes" for "five"): it replaces the last number
   - it is one word ("down" for "up"): it replaces the last word
   - otherwise it is a fresh start and replaces everything
3. a stutter ("open open Chrome", "I I want") is said once.

Text with none of these comes back unchanged (apart from spacing), and a clean-up that would leave
nothing ("um", "hmm") is not applied, so the filler check downstream still sees it. Measured on
44 spoken clips in scripts/voice_bench.py (progress.md, "Hearing like Wispr Flow").
"""

from __future__ import annotations

import re

_FILLER = re.compile(r"(?<![\w'-])(?:u+h+m*|u+m+|e+r+m*|h+m+|m+h+m+|a+h+m+)(?![\w'-])[,.…]*\s*", re.IGNORECASE)
_LEADING = re.compile(
    r"^\W*(?:(?:okay |ok )?so|well|like|you know|i mean|basically|right|anyway|um|uh)\s*,\s*", re.IGNORECASE)
_ASIDE = re.compile(r",\s*(?:you know|like|basically)\s*,", re.IGNORECASE)   # not "I mean": that is a cue

_NUMBER_WORDS = {
    "zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven",
    "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen",
    "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety", "hundred",
    "half", "quarter",
}
# "no, wait" is also heard as "no weight"; the cue has to come after a pause.
_CUE = re.compile(
    r"(?P<pause>[,.;…?!]|\s[-–—]+)\s*"
    r"(?P<cue>(?:no|oh)[, ]+(?:wait|weight|sorry|i mean|actually)|wait[, ]+no|"
    r"(?:uh[, ]+)?i mean|or rather|scratch that|never ?mind|hold on|sorry|wait|weight|"
    r"actually[, ]+(?:make it|let's|i mean|no|do)|make it|let's say|"
    r"oh[, ]+(?:yes|yeah|right|okay|ok)|no)"
    r"(?![\w'])\s*[,.:;]?\s*", re.IGNORECASE)
_SOFT_CUES = {"no", "wait", "weight", "make it", "sorry"}      # short, so they need a short replacement
_STUTTER_EXEMPT = {"no", "very", "really", "so", "bye", "ha", "yes", "yeah", "had", "that", "now", "go", "knock"}


def _bare(token: str) -> str:
    return re.sub(r"[^\w']", "", token).lower()


def _is_number(token: str) -> bool:
    t = _bare(token)
    return t in _NUMBER_WORDS or bool(re.fullmatch(r"\d+(?:[:.]\d+)?(?:st|nd|rd|th|am|pm)?", t))


def _resolve(before: str, after: str) -> str | None:
    """What `after` (the replacement) makes of `before` (what was said first), or None to leave both."""
    old, new = before.split(), after.split()
    if len(old) < 1 or not new:
        return None
    first = _bare(new[0])
    for i in range(len(old) - 1, -1, -1):                      # a word the replacement starts like
        if _bare(old[i]) == first and first not in {"and", "but"}:
            return " ".join(old[:i] + new)
    if _is_number(new[0]):
        for i in range(len(old) - 1, -1, -1):
            if _is_number(old[i]):
                return " ".join(old[:i] + new)
    if len(new) == 1:
        return " ".join(old[:-1] + new)
    return " ".join(new)                                        # a fresh start


def _fix_corrections(text: str) -> str:
    for _ in range(4):                                          # a person may correct more than once
        done = False
        for m in _CUE.finditer(text):
            cue = re.sub(r"[, ]+", " ", m.group("cue").lower()).strip()
            before, after = text[:m.start()].strip(" ,;"), text[m.end():].strip()
            if not before or not after or len(before.split()) < 1:
                continue
            if cue in _SOFT_CUES and len(after.split()) > 4:
                continue                                         # "no, I think we should..." is not a correction
            if cue == "no" and (len(before.split()) < 2 or m.group("pause") != ","):
                continue
            if cue in {"sorry", "wait", "weight"} and len(before.split()) < 2:
                continue
            resolved = _resolve(before, after)
            if resolved is None:
                continue
            text = resolved
            done = True
            break
        if not done:
            break
    return text


def _collapse_stutters(text: str) -> str:
    words = text.split()
    out: list[str] = []
    for word in words:
        if out and _bare(out[-1]) == _bare(word) and _bare(word) and _bare(word) not in _STUTTER_EXEMPT \
                and not out[-1].endswith((".", "!", "?", ",")):
            continue
        out.append(word)
    return " ".join(out)


def _tidy(text: str, capitalise: bool) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\s+([,.!?;:])", r"\1", text)
    text = re.sub(r"^[\s,;:.-]+", "", text)
    text = re.sub(r",\s*([.!?])", r"\1", text)
    text = re.sub(r"([,;])\s*\1+", r"\1", text)
    if capitalise and text and text[0].isalpha():
        text = text[0].upper() + text[1:]
    return text


def clean_transcript(text: str) -> str:
    """The sentence as the speaker meant it (see the module doc). Never returns an empty string
    for a non-empty `text`."""
    original = (text or "").strip()
    if not original:
        return original
    capitalise = original[0].isupper() or not original[0].isalpha()
    cleaned = _FILLER.sub(" ", original)
    cleaned = re.sub(r"(?:^|(?<=[.!?]))\s*,\s*", " ", cleaned)
    for _ in range(3):
        cleaned = _tidy(cleaned, False)
        lead = _LEADING.match(cleaned)
        if not lead:
            break
        cleaned = cleaned[lead.end():]
    cleaned = _ASIDE.sub(" ", cleaned)
    cleaned = _tidy(cleaned, False)
    cleaned = _fix_corrections(cleaned)
    cleaned = _collapse_stutters(cleaned)
    cleaned = _tidy(cleaned, capitalise or cleaned != original)
    if not re.search(r"[A-Za-z0-9]", cleaned):
        return original
    # Whisper's own end mark survives; a replacement that lost it gets the original's.
    if cleaned[-1] not in ".!?" and original[-1] in ".!?":
        cleaned += original[-1]
    return cleaned
