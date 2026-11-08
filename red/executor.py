"""Runs one routed command: confirm if destructive, run, log.

Every outcome (done, cancelled, failed, or a "none" reply) is one JSON line
in the command log. A failing tool becomes a short reply, never a crash.
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime
from pathlib import Path

from .confirm import DEFAULT_TIMEOUT, Ask, confirm, typed_ask
from .router import Route
from .tools.base import ToolError, ToolRegistry

log = logging.getLogger(__name__)

MAX_REPLY = 300


def _short(text: str) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= MAX_REPLY else text[:MAX_REPLY - 3] + "..."


class Executor:
    def __init__(self, registry: ToolRegistry, ask: Ask = typed_ask, log_path: Path | None = None,
                 confirm_timeout: float = DEFAULT_TIMEOUT):
        self.registry = registry
        self.ask = ask
        self.log_path = log_path            # None: don't write a command log
        self.confirm_timeout = confirm_timeout
        self._lock = threading.Lock()

    def execute(self, command: str, route: Route) -> str:
        """Run a route and return the reply for the user."""
        if route.is_none:
            reply = _short(route.args.get("reply") or "Sorry, I can't do that.")
            self._log(command, route, status="none", confirmed=None, result=reply)
            return reply

        if route.tool not in self.registry:
            reply = f"I don't have a tool called {route.tool}."
            self._log(command, route, status="error", confirmed=None, result=reply)
            return reply
        tool = self.registry.get(route.tool)

        confirmed = None
        if route.destructive or tool.destructive:
            try:
                question = tool.describe(**route.args)
            except Exception:
                log.exception("describe() failed for %s", route.tool)
                question = f"Run {route.tool} with {json.dumps(route.args)}"
            answers: list[str | None] = []

            def ask(q: str, timeout: float) -> str | None:
                answers.append(self.ask(q, timeout))
                return answers[-1]

            confirmed = confirm(question.rstrip("?.") + "?", ask, self.confirm_timeout)
            if not confirmed:
                reply = ("No answer, so I cancelled it." if answers == [None] or not answers
                         else "Cancelled.")
                self._log(command, route, status="cancelled", confirmed=False, result=reply,
                          answer=answers[-1] if answers else None)
                return reply

        try:
            reply = _short(tool.run(**route.args))
        except ToolError as e:
            reply = _short(str(e)) or f"{route.tool} failed."
            self._log(command, route, status="error", confirmed=confirmed, result=reply)
            return reply
        except Exception as e:
            log.exception("%s failed", route.tool)
            reply = _short(f"Sorry, {route.tool.replace('_', ' ')} failed: {e}")
            self._log(command, route, status="error", confirmed=confirmed, result=reply,
                      error=f"{type(e).__name__}: {e}")
            return reply
        self._log(command, route, status="ok", confirmed=confirmed, result=reply)
        return reply

    def _log(self, command: str, route: Route, **fields) -> None:
        if self.log_path is None:
            return
        entry = {
            "time": datetime.now().astimezone().isoformat(timespec="seconds"),
            "command": command,
            "tool": route.tool,
            "args": route.args,
            **fields,
        }
        try:
            with self._lock:
                self.log_path.parent.mkdir(parents=True, exist_ok=True)
                with self.log_path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
        except OSError:
            # A full disk or a locked file must not stop the command itself.
            log.exception("Couldn't write the command log %s", self.log_path)
