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

from .confirm import DEFAULT_TIMEOUT, Ask, confirm, is_yes, typed_ask
from .router import Route
from .smalltalk import is_casual_yes
from .tools.base import ToolError, ToolRegistry

log = logging.getLogger(__name__)

MAX_REPLY = 300

# Tools that only look something up. "Can you check the weather?" just gets
# the answer; there's nothing to agree to first.
NO_OFFER = {"answer", "describe_screen", "look_up", "weather", "news", "tell_status",
            "list_reminders", "check_repos", "find_file"}
OFFER = "Yes, I can do that."
DECLINED = "Okay, I won't."
NO_ANSWER = "No answer, so I left it."


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
        # Longer text from the last tool run, for the overlay (e.g. one line per repo).
        self.last_details = ""

    def execute(self, command: str, route: Route, offer: bool = False) -> str:
        """Run a route and return the reply for the user.

        offer=True means the user asked whether Red can do it ("can you turn
        off my laptop in 3 hours?"): Red says it can and asks before running.
        """
        self.last_details = ""
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
        risky = route.destructive or tool.destructive
        if offer and route.tool not in NO_OFFER:
            if risky:
                try:
                    what = tool.describe(**route.args).rstrip("?. ")
                except Exception:
                    log.exception("describe() failed for %s", route.tool)
                    what = ""
                question = f"{OFFER} {what}. Should I go ahead?" if what else f"{OFFER} Should I go ahead?"
            else:
                question = f"{OFFER} Should I go ahead?"
            answer = self.ask(question, self.confirm_timeout)
            # Risky actions still need a plain "yes"; others take "sure", "go ahead"...
            confirmed = is_yes(answer) or (not risky and is_casual_yes(answer))
            if not confirmed:
                reply = NO_ANSWER if answer is None else DECLINED
                self._log(command, route, status="cancelled", confirmed=False, result=reply,
                          answer=answer, offered=True)
                return reply
        elif risky:
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
        details = getattr(tool, "last_details", "")
        self.last_details = details if isinstance(details, str) else ""
        extra = {"details": self.last_details} if self.last_details else {}
        self._log(command, route, status="ok", confirmed=confirmed, result=reply, **extra)
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
