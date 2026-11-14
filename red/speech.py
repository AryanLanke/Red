"""Speak while the model writes (plan.md task 6).

A long answer used to be spoken only once the model had finished it: 6.6 s
of waiting in the 23:37 test. Now the model's reply streams in
(`stream_field`), is cut into sentences (`sentences`), and each finished
sentence goes to Piper while the rest is still being written (`SpeechStream`).

The model still answers in the same JSON ({"answer": ...} or {"reply": ...})
with the same, unchanged system prompts, so Ollama can reuse its cached
prompt and nothing about routing or answers changes. `JsonFieldReader` pulls
the string out of the JSON as it arrives, and stops at its closing quote.

The voice loop opens a SpeechStream for each command and makes it the
"current" one on its thread (`speaking_to`). Tools that answer (answer,
look_up, describe_screen) and the chat use it when there is one; typed mode
and tests without one work as before.
"""

from __future__ import annotations

import logging
import queue
import re
import threading
import time
from contextlib import contextmanager
from typing import Callable, Iterable, Iterator

log = logging.getLogger(__name__)


# --- the JSON string, as it arrives ---------------------------------------------------

_ESCAPES = {"n": " ", "t": " ", "r": "", "b": "", "f": "", '"': '"', "\\": "\\", "/": "/"}


class JsonFieldReader:
    """Feed it pieces of '{"answer": "Hello wor' ... and get the decoded string text back."""

    def __init__(self, key: str):
        self._start = re.compile(r'"%s"\s*:\s*"' % re.escape(key))
        self._head = ""          # text before the string starts
        self._pending = ""       # an escape split across two pieces
        self.started = False
        self.done = False

    def feed(self, piece: str) -> str:
        if self.done:
            return ""
        if not self.started:
            self._head += piece
            m = self._start.search(self._head)
            if not m:
                self._head = self._head[-200:]
                return ""
            self.started = True
            piece, self._head = self._head[m.end():], ""
        return self._decode(self._pending + piece)

    def _decode(self, text: str) -> str:
        self._pending = ""
        out = []
        i = 0
        while i < len(text):
            c = text[i]
            if c == '"':
                self.done = True
                break
            if c != "\\":
                out.append(c)
                i += 1
                continue
            if i + 1 >= len(text):
                self._pending = text[i:]
                break
            kind = text[i + 1]
            if kind != "u":
                out.append(_ESCAPES.get(kind, kind))
                i += 2
                continue
            if i + 6 > len(text):
                self._pending = text[i:]
                break
            try:
                code = int(text[i + 2:i + 6], 16)
            except ValueError:
                i += 6
                continue
            if 0xD800 <= code < 0xDC00:              # the first half of an emoji
                if i + 12 > len(text):
                    self._pending = text[i:]
                    break
                try:
                    low = int(text[i + 8:i + 12], 16)
                    out.append(chr(0x10000 + ((code - 0xD800) << 10) + (low - 0xDC00)))
                except ValueError:
                    pass
                i += 12
                continue
            out.append(chr(code))
            i += 6
        return "".join(out)


def stream_field(llm, system: str, user: str, schema: dict, key: str, **options) -> Iterator[str]:
    """The text of one JSON string field of the model's reply, piece by piece.

    Uses the client's stream_json when it has one; otherwise the whole reply at once.
    Stops reading at the field's closing quote (and closes the stream).
    """
    stream = getattr(llm, "stream_json", None)
    if stream is None:
        import json

        from .llm import complete
        yield str(json.loads(complete(llm, system, user, schema, **options))[key])
        return
    if not options.get("images"):
        options.pop("images", None)
    reader = JsonFieldReader(key)
    pieces = stream(system, user, schema, **options)
    try:
        for piece in pieces:
            text = reader.feed(piece)
            if text:
                yield text
            if reader.done:
                return
    finally:
        close = getattr(pieces, "close", None)
        if close:
            close()


# --- sentences ------------------------------------------------------------------------

_END = re.compile(r"[.!?]+[\"')\]”’]*(?=\s)|\n+")
_ABBREVIATION = re.compile(r"(?:\b(?:mr|mrs|ms|dr|st|jr|sr|vs|etc|vol|fig|approx|inc|ltd|co)\.|"
                           r"\b(?:[a-z]\.){1,3})$", re.IGNORECASE)


def sentences(pieces: Iterable[str]) -> Iterator[str]:
    """Join streamed pieces and yield each sentence as soon as it's finished."""
    buf = ""
    for piece in pieces:
        buf += piece
        start = 0
        while True:
            m = _END.search(buf, start)
            if m is None:
                break
            head = buf[:m.end()]
            if _ABBREVIATION.search(head.rstrip()):
                start = m.end()
                continue
            sentence = " ".join(head.split())
            buf = buf[m.end():].lstrip()
            start = 0
            if sentence:
                yield sentence
    rest = " ".join(buf.split())
    if rest:
        yield rest


# --- speaking them --------------------------------------------------------------------

_current = threading.local()


def current() -> "SpeechStream | None":
    """The SpeechStream the voice loop opened for this command, if any."""
    return getattr(_current, "stream", None)


@contextmanager
def speaking_to(stream: "SpeechStream | None"):
    """Make `stream` the current one on this thread while the command runs."""
    before = current()
    _current.stream = stream
    try:
        yield stream
    finally:
        _current.stream = before


_DONE = object()


def _said(text: str) -> None:
    """events `said(text)`: this piece's audio has just started (plan.md 0.2)."""
    from . import events
    events.emit("said", text=text)

# A human beat after each piece, from its punctuation, so Red doesn't sound robotic.
COMMA_PAUSE = 0.15
SENTENCE_PAUSE = 0.3
LONG_PAUSE = 0.5               # "..." or a dash: a trailing-off beat
LONG_SENTENCE = 90             # characters; longer sentences are cut at commas
_MIN_PIECE = 20                # never cut off a scrap shorter than this
FIRST_LONG = 60                # the first sentence of a reply is cut at its first comma from this length
FIRST_HEAD = 12                # ...if that leaves at least this much to say first

_TRAIL = re.compile(r"(?:\.\.\.|…|\s[-–—]|[-–—])$")
# Where a sentence may be cut: after "..." or a spaced dash always, after a comma
# or semicolon only in a long sentence.
_TRAIL_CUT = re.compile(r"(?:\.\.\.|…)(?=\s)|\s[-–—](?=\s)")
_COMMA_CUT = re.compile(r"[,;](?=\s)")


def pause_after(text: str) -> float:
    """How long to wait after saying `text`, from how it ends."""
    text = text.rstrip(" \"')]”’")
    if _TRAIL.search(text):
        return LONG_PAUSE
    if text.endswith((",", ";", ":")):
        return COMMA_PAUSE
    return SENTENCE_PAUSE


def breath_of(speaker) -> float:
    """Silence the speaker already puts after each piece (Kokoro adds a short breath)."""
    if getattr(speaker, "using_fallback", True):     # Piper, a fake, or Kokoro fallen back to Piper
        return 0.0
    from .tts_kokoro import PAUSE_SECONDS
    return PAUSE_SECONDS


def _cut(text: str, pattern: re.Pattern) -> list[str]:
    pieces, start = [], 0
    for m in pattern.finditer(text):
        head = text[start:m.end()].strip()
        rest = text[m.end():].strip()
        if len(head) >= _MIN_PIECE and len(rest) >= _MIN_PIECE:
            pieces.append(head)
            start = m.end()
    pieces.append(text[start:].strip())
    return [p for p in pieces if p]


def speech_pieces(sentence: str, long_sentence: int = LONG_SENTENCE, first: bool = False) -> list[str]:
    """One sentence as the pieces to say, each followed by its own pause.

    "Rust if you like compilers... some people do." trails off at the "...";
    a long sentence is cut at its commas so the voice's intonation resets.
    """
    sentence = " ".join(sentence.split())
    pieces = []
    if first and len(sentence) >= FIRST_LONG:
        # The first piece decides when Red starts talking, and Kokoro's time grows with its length:
        # start with the first clause, say the rest while it plays.
        for m in _COMMA_CUT.finditer(sentence):
            head, rest = sentence[:m.end()].strip(), sentence[m.end():].strip()
            if len(head) >= FIRST_HEAD and len(rest) >= _MIN_PIECE:
                return [head, *speech_pieces(rest, long_sentence)]
    for part in _cut(sentence, _TRAIL_CUT):
        pieces.extend(_cut(part, _COMMA_CUT) if len(part) > long_sentence else [part])
    return pieces


class SpeechStream:
    """Sentences in, speech out: Piper makes the next one while the last one plays.

    `say()` returns at once; `finish()` waits until everything is spoken;
    `cancel()` stops at once (Hey Red while Red is talking). With a speaker
    that only has say() (tests), each sentence is said in turn.
    """

    def __init__(self, speaker, on_text: Callable[[str], None] | None = None,
                 clock: Callable[[], float] = time.perf_counter,
                 sleep: Callable[[float], None] = time.sleep):
        self.speaker = speaker
        self.on_text = on_text            # the text so far, for the overlay
        self._clock = clock
        self._sleep = sleep
        self._queue: queue.Queue = queue.Queue()
        self._thread: threading.Thread | None = None
        self.cancelled = False
        self.spoken: list[str] = []       # what was handed over to be said, in order
        self.first_word_at: float | None = None

    @property
    def used(self) -> bool:
        return bool(self.spoken)

    def say(self, sentence: str) -> None:
        sentence = " ".join(sentence.split())
        if not sentence or self.cancelled:
            return
        self.spoken.append(sentence)
        if self.on_text is not None:
            try:
                self.on_text(" ".join(self.spoken))
            except Exception:  # noqa: BLE001 - the overlay is only a display
                log.exception("Overlay update failed")
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="red-speech", daemon=True)
            self._thread.start()
        self._queue.put(sentence)

    def finish(self, timeout: float | None = None) -> None:
        """Wait until every sentence has been spoken (or the stream was cancelled)."""
        if self._thread is None:
            return
        self._queue.put(_DONE)
        self._thread.join(timeout)

    def cancel(self) -> None:
        self.cancelled = True
        try:
            self.speaker.stop()
        except Exception:  # noqa: BLE001
            log.exception("Couldn't stop speaking")
        self._queue.put(_DONE)

    def _run(self) -> None:
        synthesize = getattr(self.speaker, "synthesize", None)
        player = getattr(self.speaker, "player", None)
        playing = False
        started = False                              # the first sentence gets a shorter first piece
        pause = 0.0                                  # after the piece that's playing now
        while True:
            item = self._queue.get()
            if item is _DONE or self.cancelled:
                break
            if synthesize is None or player is None:
                try:
                    self._mark_first()
                    _said(item)
                    self.speaker.say(item, block=True)
                except Exception:  # noqa: BLE001 - no speakers: the text is still shown
                    log.exception("Couldn't speak %r", item[:60])
                continue
            first_item, started = not started, True
            for piece in speech_pieces(item, first=first_item):
                try:
                    audio, rate = synthesize(piece)  # while the last piece still plays
                    if self.cancelled:
                        break
                    if playing:
                        player.wait()
                        rest = pause - breath_of(self.speaker)
                        if rest > 0 and not self.cancelled:
                            self._sleep(rest)
                    if self.cancelled or getattr(audio, "size", 0) == 0:
                        continue
                    self._mark_first()
                    player.play(audio, rate)
                    _said(piece)                     # the bubble shows it now, with the voice
                    playing = True
                    pause = pause_after(piece)
                except Exception:  # noqa: BLE001 - no speakers: the text is still shown
                    log.exception("Couldn't speak %r", piece[:60])
            if self.cancelled:
                break
        if playing and not self.cancelled:
            try:
                player.wait()
            except Exception:  # noqa: BLE001
                log.exception("Couldn't finish speaking")

    def _mark_first(self) -> None:
        if self.first_word_at is None:
            self.first_word_at = self._clock()
