"""To-dos and "what did I do today?" (plan.md B4). Only when asked, never spoken unasked.

The list is RED_HOME\\memory\\todo.json (never in git). The recap is counted from
logs\\commands.jsonl, today's commits in the repos.toml repos (read-only git
log) and the to-dos finished today. The Google calendar part waits for a
signed-in tool to lend its events.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tomllib
from collections import Counter
from datetime import datetime
from pathlib import Path

from red.config import red_home
from red.tools.base import Tool, ToolError

MAX_ITEMS = 200


def todo_path() -> Path:
    return red_home() / "memory" / "todo.json"


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > 2}


def _load() -> list[dict]:
    try:
        data = json.loads(todo_path().read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def _save(items: list[dict]) -> None:
    path = todo_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")


def _find(items: list[dict], text: str) -> dict:
    wanted = _words(text)
    best = max((i for i in items if not i.get("done")),
               key=lambda i: len(wanted & _words(i["text"])), default=None)
    if best is None or not wanted & _words(best["text"]):
        raise ToolError(f"I don't see \"{text.strip()}\" on your list.")
    return best


class Todo(Tool):
    name = "todo"
    description = ("The user's to-do list: 'add finish the slides', 'what's left?', 'mark the slides "
                   "done', 'clear done ones'. Not for reminders at a time.")
    args_schema = {"type": "object",
                   "properties": {"action": {"type": "string", "enum": ["add", "list", "done", "clear"]},
                                  "text": {"type": "string", "maxLength": 200}},
                   "required": ["action"], "additionalProperties": False}
    max_reply = 500
    _command = ""

    def set_command(self, command: str) -> None:
        """The user's own words (the Executor sets them): a fallback when the router drops the text."""
        self._command = " ".join(command.split())

    def run(self, action: str, text: str = "") -> str:
        text = " ".join(text.split())
        if not text and action == "done":
            text = re.sub(r"\b(?:mark|tick|check|cross|off|done|finished|complete[d]?|as|the|my|it|"
                          r"to-?do|list|red|please|hey)\b", " ", self._command, flags=re.I)
            text = " ".join(text.split())
        self._command = ""
        items = _load()
        now = datetime.now().isoformat(timespec="seconds")
        if action == "add":
            if not text:
                raise ToolError("Add what?")
            if len([i for i in items if not i.get("done")]) >= MAX_ITEMS:
                raise ToolError("Your list is full. Clear the done ones first.")
            items.append({"text": text[:200], "added": now, "done": False})
            _save(items)
            return f"Added: {text}."
        if action == "done":
            if not text:
                raise ToolError("Which one is done?")
            item = _find(items, text)
            item["done"], item["finished"] = True, now
            _save(items)
            left = sum(1 for i in items if not i.get("done"))
            return f"Ticked off: {item['text']}. {left} left." if left else f"Ticked off: {item['text']}. That's everything."
        if action == "clear":
            kept = [i for i in items if not i.get("done")]
            gone = len(items) - len(kept)
            _save(kept)
            return f"Cleared {gone} done." if gone else "Nothing done to clear."
        todo = [i["text"] for i in items if not i.get("done")]
        if not todo:
            return "Nothing left on your list."
        shown = "; ".join(todo[:6])
        more = f", and {len(todo) - 6} more" if len(todo) > 6 else ""
        return f"{len(todo)} left: {shown}{more}."


def _commands_today(day: str) -> list[dict]:
    path = red_home() / "logs" / "commands.jsonl"
    out = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if str(entry.get("time", "")).startswith(day) and entry.get("status") == "ok":
                out.append(entry)
    except OSError:
        pass
    return out


def _commits_today(day: str) -> dict[str, list[str]]:
    git = shutil.which("git")
    try:
        repos = tomllib.loads((red_home() / "config" / "repos.toml").read_text(encoding="utf-8")).get("repos", {})
    except (OSError, tomllib.TOMLDecodeError):
        return {}
    found = {}
    for name, folder in repos.items():
        if git is None or not Path(str(folder)).is_dir():
            continue
        try:
            done = subprocess.run([git, "-C", str(folder), "log", "--format=%s", f"--since={day} 00:00"],
                                  capture_output=True, text=True, encoding="utf-8", errors="replace",
                                  timeout=8, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except (OSError, subprocess.TimeoutExpired):
            continue
        lines = [s.strip() for s in done.stdout.splitlines() if s.strip()]
        if done.returncode == 0 and lines:
            found[str(name)] = lines
    return found


class DayRecap(Tool):
    name = "day_recap"
    description = "Recap what the user did today: 'what did I do today?', 'recap my day'."
    args_schema = {"type": "object", "properties": {}, "required": [], "additionalProperties": False}
    max_reply = 600
    commands = staticmethod(_commands_today)
    commits = staticmethod(_commits_today)

    def __init__(self, today=None):
        self._today = today or datetime.now

    def run(self) -> str:
        day = self._today().date().isoformat()
        commands = self.commands(day)
        commits = self.commits(day)
        finished = [i["text"] for i in _load() if i.get("done") and str(i.get("finished", "")).startswith(day)]
        parts = []
        if commits:
            n = sum(len(v) for v in commits.values())
            where = " and ".join(f"{k}" for k in list(commits)[:3])
            parts.append(f"{n} commit{'' if n == 1 else 's'} in {where}, latest \"{next(iter(commits.values()))[0][:60]}\"")
        if finished:
            parts.append(f"finished {len(finished)} to-do{'' if len(finished) == 1 else 's'}: {'; '.join(finished[:3])}")
        tools = Counter(c.get("tool") for c in commands if c.get("tool") and c.get("tool") != "none")
        if tools:
            top = ", ".join(f"{t.replace('_', ' ')} x{n}" for t, n in tools.most_common(3))
            parts.append(f"{sum(tools.values())} things done with me, mostly {top}")
        if not parts:
            return "Honestly, I don't have much on you today."
        return "Today: " + "; ".join(parts) + "."
