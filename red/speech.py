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
_ABBREVIATION = re.compile(r"(?:\b(?:mr|mrs|ms|dr|st|jr|sr|vs|etc|no|vol|fig|approx|inc|ltd|co)\.|"
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


class SpeechStream:
    """Sentences in, speech out: Piper makes the next one while the last one plays.

    `say()` returns at once; `finish()` waits until everything is spoken;
    `cancel()` stops at once (Hey Red while Red is talking). With a speaker
    that only has say() (tests), each sentence is said in turn.
    """

    def __init__(self, speaker, on_text: Callable[[str], None] | None = None,
                 clock: Callable[[], float] = time.perf_counter):
        self.speaker = speaker
        self.on_text = on_text            # the text so far, for the overlay
        self._clock = clock
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
        while True:
            item = self._queue.get()
            if item is _DONE or self.cancelled:
                break
            try:
                if synthesize is None or player is None:
                    self._mark_first()
                    self.speaker.say(item, block=True)
                    continue
                audio, rate = synthesize(item)       # while the last sentence still plays
                if self.cancelled:
                    break
                if playing:
                    player.wait()
                if self.cancelled or getattr(audio, "size", 0) == 0:
                    continue
                self._mark_first()
                player.play(audio, rate)
                playing = True
            except Exception:  # noqa: BLE001 - no speakers: the text is still shown
                log.exception("Couldn't speak %r", item[:60])
        if playing and not self.cancelled:
            try:
                player.wait()
            except Exception:  # noqa: BLE001
                log.exception("Couldn't finish speaking")

    def _mark_first(self) -> None:
        if self.first_word_at is None:
            self.first_word_at = self._clock()
