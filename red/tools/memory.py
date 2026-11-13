"""Red's long-term memory as tools: remember, what_you_know, forget (plan.md A2).

The memory itself is red/memory.py. The voice and typed loops hand it over
with `bind_memory()` (through red.__main__.bind_conversation); without it the
tools say memory isn't set up, so a test can never write the user's real files.
"""

from __future__ import annotations

import re

from .assistant import _UsesLLM, ask_model
from .base import Tool, ToolError

MEMORY_ANSWER_SYSTEM = """You are Red, the user's friend who lives on their PC. Answer their question about themselves from your memory below, in 1 or 2 short spoken sentences, talking to them ("your sister is Priya"). The memory is their own words. If the answer isn't in it, say you don't know that yet and ask them. Never guess or invent. No lists or markdown.
Reply with JSON only: {"answer": "<your answer>"}"""

_ALL = re.compile(r"^(?:all|everything|it all|all of it|everything you know(?: about me)?|all facts)$", re.I)
_THAT = re.compile(r"^(?:that|it|this|the last (?:one|thing)|what i just said|what i (?:just )?told you)$", re.I)
_GENERIC = re.compile(
    r"^(?:what|tell me what)?\s*(?:do |else do )?you (?:know|remember)(?: about me)?\??$|^about me$|^me$|"
    r"^everything$|^what you know$", re.I)


class _MemoryTool(Tool):
    def __init__(self):
        self._memory = None

    def bind_memory(self, memory) -> None:
        """Called by the voice or typed loop with Chat's red.memory.Memory."""
        self._memory = memory

    @property
    def memory(self):
        if self._memory is None:
            raise ToolError("My memory isn't set up here, so I can't do that.")
        return self._memory


class Remember(_MemoryTool):
    name = "remember"
    description = ("Remember something about the user for good, when they ask you to remember "
                   "it, for example 'remember my sister is Priya', 'remember that I hate "
                   "mornings' or 'don't forget my exam is on Friday'. Not for reminders at a "
                   "time (set_reminder) and not for notes.")
    args_schema = {
        "type": "object",
        "properties": {"fact": {"type": "string", "minLength": 2, "maxLength": 200,
                                "description": "What to remember, in the user's own words "
                                               "('my sister is Priya')."}},
        "required": ["fact"],
        "additionalProperties": False,
    }

    def run(self, fact: str) -> str:
        from ..memory import clean_fact, looks_secret, name_said
        text = clean_fact(fact)
        if not text:
            raise ToolError("Remember what?")
        if looks_secret(text):
            raise ToolError("I'd rather not keep passwords, codes or card numbers. "
                            "A password manager is the place for those.")
        name = name_said(text.rstrip("."))
        if name:
            self.memory.set_name(name)
            self.memory.mark_asked_name()
            return f"Got it, {name}."
        if self.memory.add(text, source="told") is None:
            return "I already knew that."
        return "Got it. I'll remember that."


class WhatYouKnow(_MemoryTool, _UsesLLM):
    name = "what_you_know"
    description = ("Answer a question about the user themselves from Red's memory: 'what do you "
                   "know about me?', 'what's my sister's name?', 'when is my exam?', 'what's my "
                   "name?'. Only for things about the user, their people and their life, not "
                   "general knowledge.")
    args_schema = {
        "type": "object",
        "properties": {"question": {"type": "string", "maxLength": 200,
                                    "description": "Their question, or empty for everything."}},
        "required": [],
        "additionalProperties": False,
    }

    def __init__(self, llm=None):
        _MemoryTool.__init__(self)
        _UsesLLM.__init__(self, llm)

    def run(self, question: str = "") -> str:
        from ..memory import to_you
        memory = self.memory
        said = self._command or question
        self._command = ""
        question = " ".join((question or said).split()).strip(" ?.!")
        name = memory.name()
        facts = memory.facts()
        if not name and not facts and not memory.profile_for_prompt():
            return "Honestly? Not much yet. Tell me about yourself and I'll remember."
        if not question or _GENERIC.match(question):
            return self._summary(name, facts, to_you)
        if re.search(r"\bmy name\b|\bwho am i\b|\bcall me\b", question, re.I):
            return f"You're {name}." if name else "You haven't told me your name yet. What should I call you?"
        found = memory.relevant(question, 8)
        profile = memory.profile_for_prompt()
        if not found and not profile:
            return "I don't know that yet. Tell me and I'll remember."
        lines = ([profile] if profile else []) + [f"- {f.text}" for f in found]
        prompt = "Your memory of them:\n" + "\n".join(lines) + f"\n\nTheir question: {question}?"
        if self._llm is None:
            if found:
                return to_you(found[0].text)[:1].upper() + to_you(found[0].text)[1:]
            raise ToolError("I need the local model to answer that, and it isn't connected.")
        return ask_model(self._llm, MEMORY_ANSWER_SYSTEM, prompt)

    @staticmethod
    def _summary(name, facts, to_you) -> str:
        parts = [f"You're {name}." if name else "I don't know your name yet."]
        if facts:
            told = [to_you(f.text).rstrip(".") for f in facts[-5:]]
            parts.append("You told me " + "; ".join(told) + ".")
            if len(facts) > 5:
                parts.append(f"Plus {len(facts) - 5} more things. The Memory page in the Red app "
                             "has all of it.")
        return " ".join(parts)


class Forget(_MemoryTool):
    name = "forget"
    description = ("Forget something Red remembered about the user: 'forget that', 'forget my "
                   "sister's name', 'forget everything you know about me'. Asks first.")
    destructive = True
    args_schema = {
        "type": "object",
        "properties": {"what": {"type": "string", "minLength": 1, "maxLength": 200,
                                "description": "'that' for the last thing, 'everything', or "
                                               "the thing to forget in the user's words."}},
        "required": ["what"],
        "additionalProperties": False,
    }

    def __init__(self):
        super().__init__()
        self._found: tuple[str, list] = ("", [])     # (what, the facts prepare() found for it)

    def _targets(self, what: str) -> list:
        said, targets = self._found
        return targets if said == what and targets else self._find(what)

    def _find(self, what: str) -> list:
        what = " ".join(what.split()).strip(" ?.!")
        what = re.sub(r"^(?:about\s+)", "", what, flags=re.I)
        memory = self.memory
        if _ALL.match(what):
            facts = memory.facts()
            if not facts:
                raise ToolError("There's nothing to forget. I don't remember anything yet.")
            return facts
        if _THAT.match(what):
            newest = memory.newest()
            if newest is None:
                raise ToolError("There's nothing to forget. I don't remember anything yet.")
            return [newest]
        fact = memory.find(what)
        if fact is None:
            raise ToolError(f"I don't remember anything about {what}.")
        return [fact]

    def prepare(self, what: str) -> None:
        """Find it before asking, so Red never asks about something it doesn't remember."""
        self._found = (what, self._find(what))

    def describe(self, what: str = "") -> str:
        from ..memory import to_you
        targets = self._targets(what)
        if len(targets) > 1:
            return f"Forget all {len(targets)} things I know about you"
        return f'Forget that {to_you(targets[0].text).rstrip(".")}'

    def run(self, what: str) -> str:
        targets = self._targets(what)
        self._found = ("", [])
        gone = sum(1 for f in targets if self.memory.delete(f.id))
        if not gone:
            return "That was already gone."
        return "Done. It's forgotten." if gone == 1 else f"Done. I forgot all {gone} of them."


def memory_tools() -> list[Tool]:
    return [Remember(), WhatYouKnow(), Forget()]
