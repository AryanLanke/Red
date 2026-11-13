"""Questions answered by the local model: the offline `answer` tool.

The router's model picks the tool; this makes a second call to the same local
model for a spoken answer. There's no cloud model. The Router gives the tool
its LLM through `bind_llm()`, so `default_registry()` needs no arguments.

Answers know the conversation (`bind_context()`, from red.chat), so "what's
that series about?" knows the series, and their length follows the request:
2 to 4 sentences normally, up to about 12 for "a big summary", "tell me the
whole story" or "in detail".
"""

from __future__ import annotations

import json
import logging
import re
from typing import Callable

from .. import speech as _speech
from ..llm import LLM, LLMError, complete
from .base import Tool, ToolError

log = logging.getLogger(__name__)

MAX_SENTENCES = 4
MAX_ANSWER = 700
DETAIL_SENTENCES = 12
MAX_DETAIL_ANSWER = 2400
DETAIL_MAX_TOKENS = 900          # about 12 sentences, plus the JSON around them

ANSWER_SYSTEM = """You are Red, the user's friend who lives on their Windows PC. Answer the question from your own knowledge in 2 to 4 short sentences of plain spoken English, like a smart friend: the answer first, no preamble, and a short reaction or opinion only if it fits. Never corporate ("Great question", "I'd be happy to"). No lists, markdown, links or emoji. If it needs live information (today's news, weather, prices, scores) or you don't know, say so in one sentence.
Never guess: if the question names a product, app, assistant, person or anything else you don't recognise, or that may be newer than what you know, say plainly that you don't know it (for example "I don't know Hey CD.") and answer only the parts you do know.
If there's an earlier conversation, use it to work out what "it", "that" or "the series" means, and answer about that.
Reply with JSON only: {"answer": "<your answer>"}"""

DETAIL_SYSTEM = """You are Red, the user's friend who lives on their Windows PC. The user wants a long, detailed answer. Tell it like a story, in 8 to 12 sentences of plain spoken English: the setup, the main people, what happens and how it turns out, or for other topics the full explanation step by step. No lists, markdown, links or emoji. Don't promise to give more later: give it now. If you aren't sure of details, say which parts you're unsure of.
Never guess: if the question names a product, app, assistant, person or anything else you don't recognise, or that may be newer than what you know, say plainly that you don't know it (for example "I don't know Hey CD.") and answer only the parts you do know.
If there's an earlier conversation, use it to work out what "it", "that" or "the series" means, and answer about that.
Reply with JSON only: {"answer": "<your answer>"}"""


def _schema(max_length: int) -> dict:
    return {
        "type": "object",
        "properties": {"answer": {"type": "string", "minLength": 1, "maxLength": max_length}},
        "required": ["answer"],
        "additionalProperties": False,
    }


ANSWER_SCHEMA = _schema(MAX_ANSWER)
DETAIL_SCHEMA = _schema(MAX_DETAIL_ANSWER)

# "A big summary", "tell me the whole story", "in detail", "explain fully".
_DETAIL = re.compile(
    r"\b(?:big|long|longer|full|whole|detailed|complete|proper|bigger|deep)\s+"
    r"(?:summary|story|explanation|answer|version|overview|recap|plot)\b"
    r"|\bin (?:more |full |great |much )?detail\b|\bdetailed\b|\bin depth\b|\bdeep dive\b"
    r"|\bexplain (?:it |that |this |everything )?(?:fully|completely|properly|thoroughly)\b"
    r"|\btell me (?:the |its |the whole |the full |whole )?(?:story|plot)\b"
    r"|\bstory thing\b|\belaborate\b|\bmore details?\b|\btell me (?:much )?more\b"
    r"|\beverything about\b|\bsmall summary\b|\bnot (?:so |that )?short\b",
    re.I,
)


def wants_detail(text: str) -> bool:
    """True when the user asks for a long answer ("I want a big summary")."""
    return bool(text) and _DETAIL.search(text) is not None


def spoken(text: str, max_sentences: int = MAX_SENTENCES, max_chars: int = MAX_ANSWER) -> str:
    """Make model text fit to say aloud: no markdown or links, at most N sentences."""
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"^\s*(?:[-•*]|\d+[.)])\s+", "", text, flags=re.M)   # list markers
    text = re.sub(r"[*_`#>|]+", "", text)
    text = " ".join(text.split())
    sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9\"'])", text)
    text = " ".join(sentences[:max_sentences]).strip()
    if len(text) > max_chars:
        text = text[:max_chars].rsplit(" ", 1)[0] + "…"
    return text


def with_history(history: str, text: str) -> str:
    """The prompt text, with the earlier conversation in front when there is one."""
    if not history.strip():
        return text
    return f"Earlier in this conversation:\n{history.strip()}\n\n{text}"


def ask_model(llm: LLM | None, system: str, user: str, *, detail: bool = False,
              images: list[str] | None = None, prefix: str = "") -> str:
    """One local-model call that returns {"answer": ...}; the text, cleaned for speech.

    With a SpeechStream open (the voice loop), each sentence is spoken as soon
    as the model has written it, `prefix` ("From Wikipedia:") first. The text
    returned is the same either way, without the prefix.
    """
    if llm is None:
        raise ToolError("I need the local model to answer that, and it isn't connected.")
    stream = _speech.current()
    if stream is not None and hasattr(llm, "stream_json"):
        return _ask_streaming(llm, stream, system, user, detail=detail, images=images, prefix=prefix)
    try:
        if detail:
            raw = complete(llm, system, user, DETAIL_SCHEMA, max_tokens=DETAIL_MAX_TOKENS, images=images)
        elif images:
            raw = complete(llm, system, user, ANSWER_SCHEMA, images=images)
        else:
            raw = llm.complete_json(system, user, ANSWER_SCHEMA)
        answer = json.loads(raw)["answer"]
    except LLMError as e:
        raise ToolError("The local model didn't answer. Try again in a moment.") from e
    except (ValueError, KeyError, TypeError) as e:
        raise ToolError("The local model gave an answer I couldn't read.") from e
    if detail:
        text = spoken(str(answer), DETAIL_SENTENCES, MAX_DETAIL_ANSWER)
    else:
        text = spoken(str(answer))
    if not text:
        raise ToolError("I don't have an answer for that.")
    return text


def _ask_streaming(llm, stream, system: str, user: str, *, detail: bool,
                   images: list[str] | None, prefix: str) -> str:
    """ask_model, speaking each sentence while the model writes the next one."""
    max_sentences, max_chars = (DETAIL_SENTENCES, MAX_DETAIL_ANSWER) if detail else (MAX_SENTENCES, MAX_ANSWER)
    options = {"max_tokens": DETAIL_MAX_TOKENS} if detail else {}
    said: list[str] = []
    size = 0
    pieces = _speech.stream_field(llm, system, user, DETAIL_SCHEMA if detail else ANSWER_SCHEMA,
                                  "answer", images=images, **options)
    try:
        for sentence in _speech.sentences(pieces):
            text = spoken(sentence, max_sentences=50, max_chars=max_chars)   # cleaned, not cut
            if not text:
                continue
            if not said and prefix:
                stream.say(prefix)
            stream.say(text)
            said.append(text)
            size += len(text) + 1
            if len(said) >= max_sentences or size >= max_chars or stream.cancelled:
                break
    except LLMError as e:
        if not said:
            raise ToolError("The local model didn't answer. Try again in a moment.") from e
        log.warning("The answer stopped part way: %s", e)
    finally:
        close = getattr(pieces, "close", None)
        if close:
            close()               # stop the model; the rest isn't needed
    if not said:
        raise ToolError("I don't have an answer for that.")
    return " ".join(said)


class _UsesLLM(Tool):
    max_reply = MAX_DETAIL_ANSWER + 100     # long answers aren't cut off by the Executor

    def __init__(self, llm: LLM | None = None):
        self._llm = llm
        self._history: Callable[[], str] = lambda: ""
        self._command = ""

    def bind_llm(self, llm: LLM) -> None:
        """Called by the Router with its model, unless one was passed in."""
        if self._llm is None:
            self._llm = llm

    def bind_context(self, history: Callable[[], str]) -> None:
        """Called by the voice or typed loop: the conversation so far (Chat.history)."""
        self._history = history

    def set_command(self, command: str) -> None:
        """Called by the Executor before run(): what the user actually said.

        The router's arguments can be a paraphrase; "I want a big summary"
        must still mean a long answer.
        """
        self._command = " ".join(command.split())

    def history(self) -> str:
        try:
            return self._history() or ""
        except Exception:  # noqa: BLE001 - an answer without context beats no answer
            return ""


class Answer(_UsesLLM):
    name = "answer"
    description = ("Explain an idea or answer a question from the model's own knowledge, "
                   "offline, for example 'explain recursion', 'why is the sky blue' or 'tell me "
                   "the whole story of it'. For a fact about a named thing, person, place or "
                   "event ('what is Hugging Face', 'who made Siri') use look_up instead, since "
                   "it checks sources. Not for live facts like weather or news, and not for chat "
                   "or questions about Red itself.")
    args_schema = {
        "type": "object",
        "properties": {"question": {"type": "string", "minLength": 1, "maxLength": 300,
                                    "description": "The question in the user's words."}},
        "required": ["question"],
        "additionalProperties": False,
    }

    def run(self, question: str) -> str:
        question = " ".join(question.split())
        said = self._command or question
        self._command = ""
        if not said:
            raise ToolError("What's the question?")
        # The user's own words win: the router's "question" is sometimes a
        # paraphrase, or even a reply it made up.
        detail = wants_detail(said)
        history = self.history()
        prompt = with_history(history, f"Question: {said}") if history.strip() else said
        return ask_model(self._llm, DETAIL_SYSTEM if detail else ANSWER_SYSTEM, prompt, detail=detail)
