"""Spoken yes/no confirmation.

spoken_ask() returns a function with the same shape as confirm.Ask in Track A:
(question, timeout seconds) -> answer text, or None if nothing was said in
time. Red speaks the question, records the answer and returns the transcript.
Deciding whether the answer means yes is left to confirm.is_yes, so typed and
spoken answers go through exactly the same check.
"""

from __future__ import annotations

import logging
import re
from typing import Callable

from red.audio import record_command

log = logging.getLogger(__name__)

ANSWER_SECONDS = 4.0            # longest answer recorded once you start talking
ANSWER_SILENCE_SECONDS = 0.7

# "[y/N]", "(y/n)" and similar typed-prompt hints at the end of a question.
_TYPED_HINT = re.compile(r"\s*[\[(]\s*y(es)?\s*/\s*n(o)?\s*[\])]\s*$", re.IGNORECASE)


def speakable(question: str) -> str:
    """The question as it should be said aloud: no '[y/N]' hint, and a short instruction."""
    q = _TYPED_HINT.sub("", question).strip()
    if not q:
        return "Say yes to confirm."
    if not q.endswith(("?", ".", "!")):
        q += "?"
    return f"{q} Say yes to confirm."


def spoken_ask(speaker, transcriber, *,
               record: Callable[..., object] = record_command,
               listener=None) -> Callable[[str, float], str | None]:
    """Build an Ask that speaks the question and listens for the answer.

    speaker: a tts.Speaker. transcriber: an stt.Transcriber. listener: an
    optional listener.Listener whose wake word is paused while asking (it's
    already paused when this runs inside a trigger handler; pauses nest).
    """

    def ask(question: str, timeout: float) -> str | None:
        if listener is not None:
            listener.pause()
        try:
            speaker.say(speakable(question), block=True)
            audio = record(max_seconds=timeout + ANSWER_SECONDS,
                           silence_seconds=ANSWER_SILENCE_SECONDS,
                           start_timeout=timeout)
            if getattr(audio, "size", 0) == 0:
                return None
            text = transcriber.transcribe(audio).strip()
            log.info("Spoken answer: %r", text)
            return text or None
        finally:
            if listener is not None:
                listener.resume()

    return ask
