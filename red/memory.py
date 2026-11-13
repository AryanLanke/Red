"""What Red remembers about you, for longer than one conversation (plan.md A2).

Two files under RED_HOME\\memory, never in git:

- profile.md: a short profile you can edit by hand or in the Red app (your
  name, your people, your projects, what you like). "Name: ..." is the line
  Red reads your name from.
- facts.jsonl: one fact per line, in your own voice ("My sister is Priya."),
  with when it was saved and the sentence it came from.

Facts come from three places: you ask ("remember my sister is Priya"), the
Red app's Memory page, and a background `Learner` that asks the local model
for lasting facts after a chat, only once Red has been quiet for a while, so
it never slows a reply. Anything that looks like a password, a code or a card
is never kept; an address, an email or a phone number is kept only when you
ask for it yourself.

The profile goes into the chat's system prompt (it rarely changes, so Ollama's
prompt cache still works). The facts that best match what you just said, by
plain word overlap, go into the chat prompt.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

log = logging.getLogger(__name__)

MAX_FACT = 200                 # characters in one fact
MAX_FACTS = 500                # the oldest learned facts go first beyond this
MAX_PROFILE = 1500             # characters of the profile that go into the prompt
RELEVANT = 5                   # facts per chat prompt
IDLE_SECONDS = 20.0            # quiet before the learner asks the model
MAX_PENDING = 20               # sentences waiting to be learned from

PROFILE_TEMPLATE = """# About you

Red reads this file to know who you are. Edit it freely.

Name:
People:
Projects:
Likes:
"""


def memory_dir(home: Path) -> Path:
    return Path(home) / "memory"


# --- what never goes in -----------------------------------------------------------------

_SECRET = re.compile(
    r"\b(?:passwords?|passcodes?|passwd|pass phrase|passphrase|pin numbers?|pin codes?|atm pin|"
    r"(?:my|the|bank|card|phone) pin|pin (?:is|was)|otps?|one[- ]time (?:code|password)|cvv|cvc|"
    r"(?:security|verification|login|lock|locker|door|safe|wifi|wi-fi|access|backup|recovery|2fa) codes?|"
    r"codes? (?:is|was)|credentials?|api keys?|(?:access|auth|api|login|bearer) tokens?|"
    r"secret (?:key|code)|private key|seed phrase|recovery phrase|bank account|account number|"
    r"ifsc|iban|routing number|ssn|social security|aadhaar|aadhar|pan (?:card|number))\b", re.I)
_CARD = re.compile(r"\b(?:\d[ -]?){13,19}\b")
_PRIVATE = re.compile(
    r"\b(?:my address|i live at|i stay at|lives at|house number|flat (?:no|number)|zip code|postcode|"
    r"pincode)\b"
    r"|\b\d+[a-z]?,?\s+(?:[a-z]+\s){0,3}(?:street|st|road|rd|lane|ln|avenue|ave|marg|nagar|colony|"
    r"society|apartments?|apt|sector|block|floor)\b"
    r"|[\w.+-]+@[\w-]+\.[\w.]+"
    r"|(?:\d[ ()+-]*){10,}", re.I)          # a phone number; a date has only 8 digits


def looks_secret(text: str) -> bool:
    """A password, a code, a key or a card number: never kept, even when asked."""
    return bool(_SECRET.search(text) or _CARD.search(text))


def looks_private(text: str) -> bool:
    """An address, an email or a phone number: kept only when the user asks."""
    return bool(_PRIVATE.search(text))


# --- words ------------------------------------------------------------------------------

_STOP = set("""a an the and or but so to of in on at for with from by about as is are was were be been
being am i i'm im me my mine myself you your yours we our they their them he she it its this that these
those what who whom which when where why how do does did done have has had having not no yes can could
will would should shall may might must just really very too also than then there here some any all
much many more most own same such only up down out over again once tell know remember please red hey
like get got thing things something""".split())


def words(text: str) -> set[str]:
    """Content words, lower case, with a plural or possessive 's' taken off."""
    out = set()
    for w in re.findall(r"[a-z0-9']+", text.lower()):
        w = w.strip("'")
        if w.endswith("'s"):
            w = w[:-2]
        if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
            w = w[:-1]
        if w and w not in _STOP:
            out.add(w)
    return out


_TO_YOU = [
    (re.compile(r"\bI am\b"), "you are"), (re.compile(r"\bI'm\b", re.I), "you're"),
    (re.compile(r"\bI've\b", re.I), "you've"), (re.compile(r"\bI'd\b", re.I), "you'd"),
    (re.compile(r"\bI'll\b", re.I), "you'll"), (re.compile(r"\bI was\b"), "you were"),
    (re.compile(r"\bI\b"), "you"), (re.compile(r"\bmyself\b", re.I), "yourself"),
    (re.compile(r"\bmine\b", re.I), "yours"), (re.compile(r"\bmy\b", re.I), "your"),
    (re.compile(r"\bme\b", re.I), "you"),
]


def to_you(fact: str) -> str:
    """A fact in the user's voice, said back to them: "My sister is Priya" -> "your sister is Priya"."""
    text = fact.strip()
    for pattern, repl in _TO_YOU:
        text = pattern.sub(repl, text)
    return text[:1].lower() + text[1:] if text[:2] != "I " else text


_VERB_FIX = {"has": "have", "is": "am", "was": "was", "does": "do", "goes": "go"}


def _first_person_verb(word: str) -> str:
    low = word.lower()
    if low in _VERB_FIX:
        return _VERB_FIX[low]
    if low.endswith("ies") and len(low) > 4:
        return word[:-3] + "y"                          # studies -> study
    if low.endswith(("ches", "shes", "sses", "xes")):
        return word[:-2]                                # watches -> watch
    if low.endswith("s") and not low.endswith("ss") and len(low) > 3:
        return word[:-1]                                # likes -> like
    return word


def first_person(fact: str, name: str | None = None) -> str:
    """A fact about the user put back in their voice: 'Aryan is building a robot arm for his
    college project' -> "I'm building a robot arm for my college project". Never keeps a guessed
    he or she."""
    text = fact.strip()
    subjects = [r"the user", r"user"] + ([re.escape(name), re.escape(name.split()[0])] if name else [])
    for subject in subjects:
        m = re.match(rf"^(?:{subject})'s\b\s*", text, re.I)
        if m:
            text = "My " + text[m.end():]
            break
        m = re.match(rf"^(?:{subject})\s+(?:is|'s)\b\s*", text, re.I)
        if m:
            text = "I'm " + text[m.end():]
            break
        m = re.match(rf"^(?:{subject})\s+(\w+)\b", text, re.I)
        if m:
            text = f"I {_first_person_verb(m.group(1))}{text[m.end():]}"
            break
    if re.match(r"^(?:I|I'm|My)\b", text):
        text = re.sub(r"\b(?:his|her|their)\b", "my", text, flags=re.I)
        text = re.sub(r"\b(?:himself|herself|themselves|themself)\b", "myself", text, flags=re.I)
    return text


def clean_fact(text: str) -> str:
    """'remember that my sister is Priya' -> 'My sister is Priya.'"""
    text = " ".join(str(text).split()).strip(" -•*\"'")
    text = re.sub(r"^(?:please\s+)?(?:(?:hey\s+)?red,?\s+)?(?:please\s+)?"
                  r"(?:(?:can|could|will) you\s+)?(?:remember|note|keep in mind|don't forget)"
                  r"(?:\s+(?:that|this))?[:,]?\s+", "", text, flags=re.I)
    text = re.sub(r"^that\s+(?=(?:i|my|i'm|i've|we|our)\b)", "", text, flags=re.I)   # "that I hate mornings"
    text = text[:MAX_FACT].strip()
    if not text:
        return ""
    text = text[0].upper() + text[1:]
    return text if text[-1] in ".!?" else text + "."


# --- the name ---------------------------------------------------------------------------

_NAME_WORD = r"[A-Za-z][A-Za-z'-]{0,23}"
_NOT_NAMES = set("""back later now tomorrow tonight today when if a an the at in on maybe sometime soon
anytime anything whatever nothing something someone boss sir madam dude bro bud buddy please yes no
yeah yep nope sure okay ok fine good great tired busy bored hungry sleepy sad happy here done ready
sorry just not hi hello hey thanks thank you why what who how where which stop cancel never mind
anyone nobody everyone me myself whatever""".split())
_TAIL_WORDS = r"(?:please|from now on|instead)"
_TAIL = rf"(?:\s+{_TAIL_WORDS})?[.!]?$"
_FULL_NAME = rf"{_NAME_WORD}(?:\s+(?!{_TAIL_WORDS}\b){_NAME_WORD})?"
# Clear on their own, at any time: "call me Ari", "my name is Aryan".
_CALL_ME = re.compile(
    rf"^(?:(?:hey\s+)?red[, ]+)?(?:(?:you can|please|just|from now on,?|actually,?)\s+)*"
    rf"(?:call me|my name is|my name's|name's|i go by)\s+({_FULL_NAME}){_TAIL}", re.I)
# Answers to "what should I call you?": "it's Aryan", "just Ari".
_ITS = re.compile(rf"^(?:it's|it is|just)\s+({_FULL_NAME}){_TAIL}", re.I)
# "I'm Aryan" (a capital: "I'm tired" isn't a name).
_IM = re.compile(rf"^[Ii](?:'m| am)\s+([A-Z][A-Za-z'-]{{0,23}}(?:\s+[A-Z][A-Za-z'-]{{0,23}})?){_TAIL}")
# Just the name: "Aryan", "Aryan Lanke", or one lower-case word ("aryan", typed).
_BARE = re.compile(rf"^({_NAME_WORD}(?:\s+{_NAME_WORD})?)[.!]?$")


def _name_from(words_: str) -> str | None:
    parts = words_.split()
    if not parts or any(p.lower() in _NOT_NAMES for p in parts):
        return None
    return " ".join(p[:1].upper() + p[1:] for p in parts)


def name_said(text: str, answering: bool = False) -> str | None:
    """'call me Ari' -> 'Ari'. With `answering` (Red just asked), also 'Aryan' or 'it's Aryan'."""
    said = " ".join(text.split()).strip()
    m = _CALL_ME.match(said)
    if m:
        return _name_from(m.group(1))
    if not answering:
        return None
    m = _ITS.match(said) or _IM.match(said)
    if m:
        return _name_from(m.group(1))
    m = _BARE.match(said)
    if m:
        bare = m.group(1)
        if len(bare.split()) > 1 and not all(p[:1].isupper() for p in bare.split()):
            return None                    # "good thanks", not "Aryan Lanke"
        return _name_from(bare)
    return None


# --- the store --------------------------------------------------------------------------

@dataclass
class Fact:
    id: str
    text: str
    when: str
    source: str = "told"       # told (asked to), learned (background), app (the Memory page)
    said: str = ""             # the sentence it came from


class Memory:
    """The profile and the facts, on disk. Safe to use from several threads."""

    def __init__(self, home: Path, now: Callable[[], datetime] = datetime.now):
        self.dir = memory_dir(home)
        self._now = now
        self._lock = threading.RLock()

    @property
    def profile_path(self) -> Path:
        return self.dir / "profile.md"

    @property
    def facts_path(self) -> Path:
        return self.dir / "facts.jsonl"

    @property
    def state_path(self) -> Path:
        return self.dir / "state.json"

    # profile and name

    def profile(self) -> str:
        try:
            return self.profile_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return ""

    def save_profile(self, text: str) -> None:
        with self._lock:
            self.dir.mkdir(parents=True, exist_ok=True)
            self.profile_path.write_text(text.rstrip() + "\n", encoding="utf-8")

    def profile_for_prompt(self) -> str:
        """The profile's filled-in lines ("Name: Aryan"), without the heading and help text."""
        lines = []
        for line in self.profile().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("Red reads this file"):
                continue
            if re.fullmatch(r"[A-Za-z ]{1,20}:", line):        # an empty field
                continue
            lines.append(line)
        return "\n".join(lines)[:MAX_PROFILE]

    def name(self) -> str | None:
        m = re.search(r"^\s*Name:[ \t]*(\S[^\r\n]*)$", self.profile(), re.M)
        return m.group(1).strip()[:40] if m else None

    def set_name(self, name: str) -> None:
        name = " ".join(name.split())[:40]
        with self._lock:
            text = self.profile() or PROFILE_TEMPLATE
            if re.search(r"^\s*Name:.*$", text, re.M):
                text = re.sub(r"^\s*Name:.*$", f"Name: {name}", text, count=1, flags=re.M)
            else:
                text = f"Name: {name}\n{text}"
            self.save_profile(text)

    def _state(self) -> dict:
        try:
            return json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _set_state(self, **values) -> None:
        with self._lock:
            state = {**self._state(), **values}
            self.dir.mkdir(parents=True, exist_ok=True)
            self.state_path.write_text(json.dumps(state), encoding="utf-8")

    def asked_name(self) -> bool:
        return bool(self._state().get("asked_name"))

    def mark_asked_name(self) -> None:
        self._set_state(asked_name=True)

    # facts

    def facts(self) -> list[Fact]:
        try:
            lines = self.facts_path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            return []
        out = []
        for line in lines:
            try:
                data = json.loads(line)
                out.append(Fact(**{k: data[k] for k in ("id", "text", "when") if k in data},
                                source=data.get("source", "told"), said=data.get("said", "")))
            except (ValueError, TypeError, KeyError):
                continue
        return out

    def _write(self, facts: list[Fact]) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        tmp = self.facts_path.with_suffix(".tmp")
        tmp.write_text("".join(json.dumps(asdict(f), ensure_ascii=False) + "\n" for f in facts),
                       encoding="utf-8")
        tmp.replace(self.facts_path)

    def add(self, text: str, source: str = "told", said: str = "") -> Fact | None:
        """Keep a fact. None when it's empty, already known, or not safe to keep.

        "My name is Ari." sets the profile's name instead.
        """
        fact = clean_fact(text)
        if not fact or looks_secret(fact) or (source != "told" and looks_private(fact)):
            return None
        name = name_said(fact.rstrip("."))
        if name:
            self.set_name(name)
            return None
        with self._lock:
            facts = self.facts()
            key = words(fact)
            for old in facts:
                old_key = words(old.text)
                if old.text.lower() == fact.lower() or (key and key <= old_key):
                    return None                             # nothing new
            new = Fact(id=uuid.uuid4().hex[:12], text=fact,
                       when=self._now().astimezone().isoformat(timespec="seconds"),
                       source=source, said=" ".join(said.split())[:300])
            facts.append(new)
            while len(facts) > MAX_FACTS:
                learned = next((i for i, f in enumerate(facts) if f.source == "learned"), 0)
                facts.pop(learned)
            self._write(facts)
            return new

    def update(self, fact_id: str, text: str) -> bool:
        fact = clean_fact(text)
        with self._lock:
            facts = self.facts()
            for f in facts:
                if f.id == fact_id:
                    if not fact:
                        facts.remove(f)
                    else:
                        f.text = fact
                    self._write(facts)
                    return True
        return False

    def delete(self, fact_id: str) -> bool:
        with self._lock:
            facts = self.facts()
            kept = [f for f in facts if f.id != fact_id]
            if len(kept) == len(facts):
                return False
            self._write(kept)
            return True

    def relevant(self, text: str, k: int = RELEVANT) -> list[Fact]:
        """The facts that share the most words with `text`, newest first among equals."""
        key = words(text)
        if not key:
            return []
        scored = []
        for i, fact in enumerate(self.facts()):
            score = len(key & words(fact.text))
            if score:
                scored.append((score, i, fact))
        scored.sort(key=lambda s: (-s[0], -s[1]))
        return [fact for _, _, fact in scored[:k]]

    def find(self, text: str) -> Fact | None:
        """The fact `text` is about ("my sister" -> "My sister is Priya."), or None."""
        best = self.relevant(text, 1)
        return best[0] if best else None

    def newest(self) -> Fact | None:
        facts = self.facts()
        return facts[-1] if facts else None


# --- learning in the background ---------------------------------------------------------

EXTRACT_SYSTEM = """You keep a friend's long-term memory. From what the user said below, write down lasting facts about the user that are worth remembering for months: their name, the people in their life (names and who they are), their projects, work or studies, likes and dislikes, plans, and important dates.
- Skip moods, passing requests, commands to the PC, questions, small talk, and anything already known (listed).
- Never keep passwords, codes, PINs, card or bank numbers, addresses, emails or phone numbers.
- Write each fact as one short sentence the way the user would say it, starting with "I" or "My", for example "My sister is Priya." or "I'm learning Rust." Never use their name, "the user", he, she or they.
- Most chats have no new facts. Then return an empty list. Never invent anything.
Reply with JSON only: {"facts": ["<fact>", ...]}"""

EXTRACT_SCHEMA = {
    "type": "object",
    "properties": {"facts": {"type": "array", "maxItems": 3,
                             "items": {"type": "string", "minLength": 3, "maxLength": MAX_FACT}}},
    "required": ["facts"],
    "additionalProperties": False,
}


class Learner:
    """Picks up lasting facts from chats, only while Red is idle.

    `note(said)` queues a sentence (kept on disk, so a restart doesn't lose it);
    the worker thread waits until `quiet()` says Red has had IDLE_SECONDS of
    quiet, then asks the model once for the whole batch.
    """

    def __init__(self, memory: Memory, llm, quiet: Callable[[], float], *,
                 idle: float = IDLE_SECONDS, poll: float = 2.0):
        self.memory = memory
        self.llm = llm
        self._quiet = quiet
        self.idle = idle
        self.poll = poll
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def pending_path(self) -> Path:
        return self.memory.dir / "pending.jsonl"

    def pending(self) -> list[str]:
        try:
            lines = self.pending_path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            return []
        out = []
        for line in lines:
            try:
                out.append(str(json.loads(line)))
            except ValueError:
                continue
        return out[-MAX_PENDING:]

    def note(self, said: str) -> None:
        said = " ".join(said.split())
        if len(words(said)) < 2:          # "hi", "okay": nothing to learn
            return
        with self._lock:
            try:
                self.memory.dir.mkdir(parents=True, exist_ok=True)
                with self.pending_path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(said[:500], ensure_ascii=False) + "\n")
            except OSError:
                log.exception("Couldn't queue a sentence to learn from")

    def learn_now(self) -> list[Fact]:
        """Ask the model about everything pending; keep the safe, new facts."""
        with self._lock:
            pending = self.pending()
            if not pending or self.llm is None:
                return []
            from .llm import complete
            text = " ".join(pending)
            known = [f.text for f in self.memory.relevant(text, 10)]
            profile = self.memory.profile_for_prompt()
            prompt = ("Already known:\n" + "\n".join(f"- {k}" for k in ([profile] if profile else []) + known)
                      if profile or known else "Already known: nothing yet.")
            prompt += "\n\nWhat the user said:\n" + "\n".join(f"- {p}" for p in pending)
            try:
                raw = complete(self.llm, EXTRACT_SYSTEM, prompt, EXTRACT_SCHEMA, max_tokens=200)
                found = json.loads(raw).get("facts", [])
            except Exception as e:  # noqa: BLE001 - try again at the next quiet spell
                log.warning("Memory: couldn't learn from the chat: %s", e)
                return []
            kept = []
            name = self.memory.name()
            for fact in found[:3]:
                new = self.memory.add(first_person(str(fact), name), source="learned", said=text)
                if new is not None:
                    kept.append(new)
            self.pending_path.unlink(missing_ok=True)
        if kept:
            log.info("Memory: learned %s", "; ".join(f.text for f in kept))
        return kept

    def _run(self) -> None:
        while not self._stop.wait(self.poll):
            try:
                if self.pending() and self._quiet() >= self.idle:
                    self.learn_now()
            except Exception:  # noqa: BLE001 - memory is a nice-to-have, never a crash
                log.exception("Memory learner failed")

    def start(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="red-memory", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()


def quiet_since(last: Callable[[], float], clock: Callable[[], float] = time.monotonic):
    """A `quiet()` for Learner: seconds since `last()`."""
    return lambda: clock() - last()
