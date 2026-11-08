"""Questions answered by the local model: the offline `answer` tool.

The router's model picks the tool; this makes a second call to the same local
model for a short spoken answer. There's no cloud model. The Router gives the
tool its LLM through `bind_llm()`, so `default_registry()` needs no arguments.
"""

from __future__ import annotations

import json
import re

from ..llm import LLM, LLMError
from .base import Tool, ToolError

MAX_SENTENCES = 4
MAX_ANSWER = 700

ANSWER_SYSTEM = """You are Red, a voice assistant on the user's Windows PC. Answer the question from your own knowledge in 2 to 4 short sentences of plain spoken English. No lists, markdown, links or emoji. If it needs live information (today's news, weather, prices, scores) or you don't know, say so in one sentence.
Reply with JSON only: {"answer": "<your answer>"}"""

ANSWER_SCHEMA = {
    "type": "object",
    "properties": {"answer": {"type": "string", "minLength": 1, "maxLength": MAX_ANSWER}},
    "required": ["answer"],
    "additionalProperties": False,
}


def spoken(text: str, max_sentences: int = MAX_SENTENCES) -> str:
    """Make model text fit to say aloud: no markdown or links, at most N sentences."""
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"^\s*(?:[-•*]|\d+[.)])\s+", "", text, flags=re.M)   # list markers
    text = re.sub(r"[*_`#>|]+", "", text)
    text = " ".join(text.split())
    sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9\"'])", text)
    text = " ".join(sentences[:max_sentences]).strip()
    if len(text) > MAX_ANSWER:
        text = text[:MAX_ANSWER].rsplit(" ", 1)[0] + "…"
    return text


def ask_model(llm: LLM | None, system: str, user: str) -> str:
    """One local-model call that returns {"answer": ...}; the text, cleaned for speech."""
    if llm is None:
        raise ToolError("I need the local model to answer that, and it isn't connected.")
    try:
        raw = llm.complete_json(system, user, ANSWER_SCHEMA)
        answer = json.loads(raw)["answer"]
    except LLMError as e:
        raise ToolError("The local model didn't answer. Try again in a moment.") from e
    except (ValueError, KeyError, TypeError) as e:
        raise ToolError("The local model gave an answer I couldn't read.") from e
    text = spoken(str(answer))
    if not text:
        raise ToolError("I don't have an answer for that.")
    return text


class _UsesLLM(Tool):
    def __init__(self, llm: LLM | None = None):
        self._llm = llm

    def bind_llm(self, llm: LLM) -> None:
        """Called by the Router with its model, unless one was passed in."""
        if self._llm is None:
            self._llm = llm


class Answer(_UsesLLM):
    name = "answer"
    description = ("Answer a general knowledge question or explain something from the "
                   "model's own knowledge, offline, in a few sentences, for example 'what is "
                   "Hugging Face' or 'explain recursion'. Not for live facts like weather "
                   "or news.")
    args_schema = {
        "type": "object",
        "properties": {"question": {"type": "string", "minLength": 1, "maxLength": 300,
                                    "description": "The question in the user's words."}},
        "required": ["question"],
        "additionalProperties": False,
    }

    def run(self, question: str) -> str:
        question = " ".join(question.split())
        if not question:
            raise ToolError("What's the question?")
        return ask_model(self._llm, ANSWER_SYSTEM, question)
