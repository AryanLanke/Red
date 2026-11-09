"""Intent router: turns a command into a validated tool call.

The LLM's output is constrained to a JSON schema built from the tool
registry. Red then validates that JSON itself before anything runs, so a
model or server that ignores the schema still can't trigger a bad call.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from jsonschema import Draft202012Validator

from .llm import LLM
from .tools.base import ToolRegistry

NONE_TOOL = "none"
_NONE_ARGS = {
    "type": "object",
    "properties": {"reply": {"type": "string", "maxLength": 300}},
    "required": ["reply"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """You are the intent router for Red, a voice assistant on a Windows laptop.
Pick exactly one tool for the user's command and reply with JSON only:
{{"tool": "<tool name>", "args": {{...}}}}

Tools:
{tools}
- none: no tool fits, or the command is unclear. args: {{"reply": "<one short sentence for the user>"}}

Rules:
- Use only the tools listed. Never invent tools or arguments.
- Convert durations to the unit the tool asks for (for example "3 hours" is 180 minutes).
- If the command is ambiguous or missing a required value, use "none" and ask a short question.
- A single word or phrase with no request in it (for example "banana") is unclear: use "none".
- Questions: a general knowledge question or "explain X" goes to answer. "Look up X" or anything ending in "and tell me" goes to look_up, which says the answer aloud. web_search only opens results in the browser ("google X", "search for X", "show me pictures of X"), and never open_url for a search.
- Pick the most specific tool: open_settings (not open_app) for a Windows Settings page; find_file (not open_folder) when the user says find, locate or where is.

Examples:
"search online for the mars rover and tell me about it" -> {{"tool": "look_up", "args": {{"topic": "mars rover"}}}}
"find the folder named taxes" -> {{"tool": "find_file", "args": {{"name": "taxes", "kind": "folder"}}}}"""


class RouteError(ValueError):
    """The LLM's reply was not a valid tool call."""


@dataclass(frozen=True)
class Route:
    tool: str
    args: dict
    destructive: bool

    @property
    def is_none(self) -> bool:
        return self.tool == NONE_TOOL

    def to_json(self) -> str:
        return json.dumps({"tool": self.tool, "args": self.args})


class Router:
    def __init__(self, registry: ToolRegistry, llm: LLM | None = None):
        self.registry = registry
        self.llm = llm
        # Tools that need the local model themselves (answers, summaries) get it here,
        # so default_registry() needs no arguments.
        if llm is not None:
            for tool in registry:
                bind = getattr(tool, "bind_llm", None)
                if callable(bind):
                    bind(llm)
        self.schema = self._build_schema()
        self._validator = Draft202012Validator(self.schema)
        self.system_prompt = SYSTEM_PROMPT.format(tools="\n".join(
            f"- {t.name}: {t.description} args schema: {json.dumps(t.args_schema, separators=(',', ':'), ensure_ascii=False)}"
            for t in registry
        ))

    def _build_schema(self) -> dict:
        options = [(t.name, t.args_schema) for t in self.registry]
        options.append((NONE_TOOL, _NONE_ARGS))
        return {"anyOf": [
            {
                "type": "object",
                "properties": {"tool": {"const": name}, "args": args},
                "required": ["tool", "args"],
                "additionalProperties": False,
            }
            for name, args in options
        ]}

    def route(self, command: str) -> Route:
        if self.llm is None:
            raise RuntimeError("Router has no LLM")
        command = command.strip()
        if not command:
            raise RouteError("Empty command")
        raw = self.llm.complete_json(self.system_prompt, command, self.schema)
        return self.parse(raw)

    def parse(self, raw: str) -> Route:
        """Validate a raw LLM reply. Raises RouteError if it isn't a valid call."""
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError) as e:
            raise RouteError(f"Not valid JSON: {raw!r}") from e
        if not isinstance(data, dict) or not isinstance(data.get("tool"), str):
            raise RouteError(f"Missing 'tool': {raw!r}")

        name = data["tool"]
        if name != NONE_TOOL and name not in self.registry:
            raise RouteError(f"Unknown tool: {name!r}")
        if not self._validator.is_valid(data):
            # Report the error against the chosen tool's schema, which is clearer
            # than the anyOf error.
            args_schema = _NONE_ARGS if name == NONE_TOOL else self.registry.get(name).args_schema
            errors = [e.message for e in Draft202012Validator(args_schema).iter_errors(data.get("args"))]
            raise RouteError(f"Invalid args for {name}: {'; '.join(errors) or raw!r}")

        destructive = name != NONE_TOOL and self.registry.get(name).destructive
        return Route(tool=name, args=data["args"], destructive=destructive)
