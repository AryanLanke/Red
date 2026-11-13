"""Intent router: turns a command into a validated tool call.

The LLM's output is constrained to a JSON schema built from the tool
registry. Red then validates that JSON itself before anything runs, so a
model or server that ignores the schema still can't trigger a bad call.
"""

from __future__ import annotations

import json
import re
import logging
from dataclasses import dataclass
from typing import Callable

from jsonschema import Draft202012Validator

from . import fastpath as _fastpath
from .llm import LLM
from .tools.base import ToolRegistry

log = logging.getLogger(__name__)

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
- none: no tool fits: chatting, feelings, personal talk, opinions, jokes, or an unclear command. args: {{"reply": "<one short sentence for the user>"}}

Rules:
- Use only the tools listed. Never invent tools or arguments.
- Convert durations to the unit the tool asks for (for example "3 hours" is 180 minutes).
- If the command is ambiguous or missing a required value, use "none" and ask a short question.
- A repeated or corrected request ("I told you to open YouTube") is a command: use the tool. Never reply that you will do something; do it.
- A single word or phrase with no request in it (for example "banana") is unclear: use "none".
- Talk about Red itself (who are you, tell me about yourself, how are you, what are you thinking), feelings, personal problems, opinions or jokes: use "none". Only facts about the world go to answer.
- Questions: a general knowledge question or "explain X" goes to answer. "Look up X" or anything ending in "and tell me" goes to look_up, which says the answer aloud. web_search only opens results in the browser ("google X", "search for X", "show me pictures of X"), and never open_url for a search.
- A debate, a quiz, a discussion or "back and forth" is a conversation, not one answer: use "none" so Red can keep talking.
- Recent things: questions about products, apps, AI assistants or gadgets that may be new (from 2024 on), and "latest", "newest" or "compare" questions about products, go to look_up, so the facts come from a real source.
- Playing: every "play X", "put on X" or "open a podcast/video" (a song, artist, album, genre, podcast, video, trailer), "shuffle my songs", or just "music" or "anything", goes to play_online. "Search YouTube for X" only shows results: web_search with site youtube.
- A browser named in the command ("in Edge", "from Chrome") only fills the browser argument; it never changes the tool.
- Waiting for something to finish ("tell me when the build is done", "when VS Code finishes, remind me") goes to notify_when_done, not set_reminder. "Stop watching X" goes to cancel_watch.
- Pick the most specific tool: open_settings (not open_app) for a Windows Settings page; find_file (not open_folder) when the user says find, locate or where is.

Examples:
"search online for the mars rover and tell me about it" -> {{"tool": "look_up", "args": {{"topic": "mars rover"}}}}
"find the folder named taxes" -> {{"tool": "find_file", "args": {{"name": "taxes", "kind": "folder"}}}}
"Open YouTube." -> {{"tool": "open_url", "args": {{"url": "https://www.youtube.com"}}}}
"Can you just read my screen? What's going on?" -> {{"tool": "describe_screen", "args": {{"question": "What's going on on my screen?"}}}}
"open the second one" -> {{"tool": "open_found_file", "args": {{"number": 2}}}}
"mail mom that I'll be late" -> {{"tool": "compose_mail", "args": {{"to": "mom", "subject": "Running late", "body": "I'll be late."}}}}"""


# "Open Chrome and search flights to Delhi", "mute and lock the PC": a sentence is
# cut where "and", "then" or a comma is followed by one of these command words.
# "search for cats and dogs" stays whole ("dogs" isn't a command), and so does
# "search ... and tell me about it" (a look_up), because "tell me" isn't here.
MAX_STEPS = 4
# "Let's have a debate", "quiz me", "let's discuss AI": a conversation that
# should keep going turn after turn, not one answer. Routed to Chat (none).
_MULTI_TURN = re.compile(r"\b(?:debate|quiz me|quiz|argue|discuss(?:ion)?|"
                         r"back[- ]and[- ]forth)\b", re.IGNORECASE)


def is_multi_turn(text: str) -> bool:
    """True when the user is starting (or continuing) a back-and-forth conversation."""
    return bool(_MULTI_TURN.search(text))
_COMMAND_WORDS = (r"open|launch|start|close|search|google|find|look up|play|put on|pause|resume|"
                  r"stop|skip|mute|unmute|lock|turn|set|check|read|reply|mail|email|send|add|move|"
                  r"cancel|delete|remind|show|take|empty|shut down|restart|volume")
_SPLIT = re.compile(r"\s*(?:,\s*)?(?:\band then\b|\bthen\b|\band also\b|\band\b|,)\s+"
                    r"(?=(?:please\s+|also\s+)?(?:%s)\b)" % _COMMAND_WORDS, re.IGNORECASE)


def split_commands(text: str) -> list[str]:
    """'mute and lock the PC' -> ['mute', 'lock the PC']; one part when it isn't a list of commands."""
    parts = [p.strip(" ,.") for p in _SPLIT.split(text.strip())]
    parts = [p for p in parts if p]
    return parts if 1 < len(parts) <= MAX_STEPS else [text.strip()]


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


CHARS_PER_TOKEN = 3.6          # measured: 17,492 characters of router prompt = 4,383 tokens
CONTEXT_HEADROOM = 1_500       # the sentence, the conversation and the reply
CONTEXT_STEP = 2_048
DEFAULT_CONTEXT = 4_096        # red/llm.py's num_ctx


def fit_context(llm, system_prompt: str) -> int | None:
    """Make sure the router prompt fits the model's context window. Returns the new size, if changed.

    Ollama silently cuts the start of a prompt that doesn't fit num_ctx, and the
    router's instructions are at the start: on 2026-11-13 the prompt was 4,383
    tokens against 4,096, and 5,204 with the built-in plugins, which sent "check
    my repos" to list_reminders. Every call shares this one client, so Ollama
    loads the model once at the new size instead of switching back and forth.
    """
    options = getattr(llm, "options", None)
    if not isinstance(options, dict):
        return None                        # not Ollama (or a test fake): nothing to fit
    need = int(len(system_prompt) / CHARS_PER_TOKEN) + CONTEXT_HEADROOM
    have = int(options.get("num_ctx", DEFAULT_CONTEXT))
    if need <= have:
        return None
    size = -(-need // CONTEXT_STEP) * CONTEXT_STEP
    options["num_ctx"] = size
    log.info("Router prompt is about %d tokens; the model's context is now %d (was %d)",
             need - CONTEXT_HEADROOM, size, have)
    return size


class Router:
    def __init__(self, registry: ToolRegistry, llm: LLM | None = None, *,
                 fast: Callable[[str], dict | None] | None = _fastpath.match):
        self.registry = registry
        self.llm = llm
        # Clear, common commands ("open YouTube", "pause") skip the model
        # (red/fastpath.py). None turns that off.
        self.fast = fast
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
        fit_context(llm, self.system_prompt)

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

    def route(self, command: str, context: str = "") -> Route:
        """Route one command. `context` is the last few lines of the conversation
        (Chat.history()), so "what's that series about?" knows which series."""
        command = command.strip()
        if not command:
            raise RouteError("Empty command")
        if is_multi_turn(command):
            # Chat answers these itself, in several turns; never a one-shot answer.
            log.info("Multi-turn request: %r -> chat", command)
            return self.parse(json.dumps({"tool": NONE_TOOL,
                                          "args": {"reply": "Let's get into it."}}))
        call = self.fast(command) if self.fast is not None else None
        if call is not None and call.get("tool") == "look_up" and context.strip():
            call = None          # mid-conversation, "who is the actor" may mean the one just named
        if call is not None and call.get("tool") in self.registry:
            route = self.parse(json.dumps(call))      # the same checks as a model's call
            log.info("Fast path: %r -> %s", command, route.to_json())
            return route
        if self.llm is None:
            raise RuntimeError("Router has no LLM")
        user = command
        if context.strip():
            # In the user message, not the system prompt: with no conversation
            # the prompt (and so routing) is exactly as before.
            user = (f"Earlier in this conversation (only to understand words like it, that or "
                    f"more; route only the command, and a question about something named "
                    f"earlier goes to look_up or answer with its name):\n{context.strip()}"
                    f"\n\nCommand: {command}")
        raw = self.llm.complete_json(self.system_prompt, user, self.schema)
        return self.parse(raw)

    def route_many(self, command: str, context: str = "") -> list[tuple[str, Route]]:
        """[(the words, its route)] for each command in the sentence, in order (up to MAX_STEPS).

        A sentence that isn't a list of commands, or where any part would be chat
        ("none"), is routed whole, exactly as route() does.
        """
        parts = split_commands(command)
        if len(parts) > 1:
            routes = []
            for part in parts:
                route = self.route(part, context)
                if route.is_none:
                    break
                routes.append((part, route))
            else:
                log.info("Several commands in one: %s", " | ".join(r.to_json() for _, r in routes))
                return routes
        return [(command, self.route(command, context))]

    def parse(self, raw: str) -> Route:
        """Validate a raw LLM reply. Raises RouteError if it isn't a valid call."""
        try:
            # The first JSON value, ignoring anything after it: Qwen3.5 on Ollama
            # sometimes keeps writing ("```json {...") after a complete call.
            # What it wrote first is still checked against the schema below.
            data, _end = json.JSONDecoder().raw_decode(raw.strip())
        except (json.JSONDecodeError, TypeError, AttributeError) as e:
            raise RouteError(f"Not valid JSON: {str(raw)[:300]!r}") from e
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
