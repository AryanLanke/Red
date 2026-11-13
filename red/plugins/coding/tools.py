"""Red at the desk with your coding tools (plan.md B3.1).

- open_in_coding_tool: "open Red in Qoder", "open Freebuff", "open plan.md in
  VS Code at line 40". Project names come from repos.toml and files must
  exist inside them; only those paths reach the tool's command line (a list
  of arguments, never a shell), never model text.
- tell_coding_agent: "tell Qoder to fix the failing tests in Red". Red reads
  the task back once (the Executor asks), opens the project, brings the tool
  to the front and puts the task on the clipboard. Where the tool has a known
  chat shortcut (VS Code's Ctrl+Alt+I, or one you set), Red opens the chat,
  pastes and presses Enter, but only if that tool's window is still in front.
  Otherwise it tells you to paste. The task is your own words, typed into the
  app as text, never run.
- what_did_it_change: a short summary of what changed in that repo since the
  hand-off (read-only git: status, diff --shortstat, log).
- "Tell me when it's done" is notify_when_done (red/tools/watch.py).

Tools found on this PC (2026-11-13): VS Code (code.cmd on PATH), Qoder (its
launcher's state.ini names the real Qoder.exe), Freebuff, the Antigravity IDE
and the Antigravity app. Add others, or chat shortcuts, in allowlist.toml:

    [coding.cursor]
    label = "Cursor"
    exe = '%LOCALAPPDATA%\\Programs\\cursor\\Cursor.exe'
    folder_arg = true
    aliases = ["cursor"]

    [coding.qoder]
    chat_key = "ctrl+l"
"""

from __future__ import annotations

import configparser
import json
import os
import re
import shutil
import subprocess
import time
import tomllib
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from red.config import red_home
from red.desk import Desk, parse_keys
from red.tools.base import Tool, ToolError

SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", ".next"}
MAX_SEARCH = 4000          # files looked at when finding a file by name


@dataclass
class Coder:
    key: str
    label: str
    exe: Path | None
    aliases: list[str]
    folder_arg: bool = True
    goto: bool = False
    chat_key: str = ""
    exes: set[str] = field(default_factory=set)


def _local(*parts: str) -> Path:
    return Path(os.environ.get("LOCALAPPDATA", "")).joinpath(*parts)


def find_vscode() -> Path | None:
    cmd = shutil.which("code.cmd") or shutil.which("code")
    if cmd:
        exe = Path(cmd).resolve().parent.parent / "Code.exe"
        if exe.is_file():
            return exe
    exe = _local("Programs", "Microsoft VS Code", "Code.exe")
    return exe if exe.is_file() else None


def find_qoder() -> Path | None:
    """Qoder's launcher keeps the real app's path in state.ini (installDir + appExecutable)."""
    ini = _local("Qoder", "Qoder Launcher", "state.ini")
    parser = configparser.ConfigParser()
    try:
        parser.read(ini, encoding="utf-8")
        section = parser["launcher"]
        exe = Path(section["installDir"]) / section["appExecutable"]
        if exe.is_file():
            return exe
    except (KeyError, OSError, configparser.Error):
        pass
    launcher = _local("Qoder", "Qoder Launcher", "Qoder Launcher.exe")
    return launcher if launcher.is_file() else None


def _exists(path: Path) -> Path | None:
    return path if path.is_file() else None


def builtin_coders() -> dict[str, Coder]:
    return {
        "vscode": Coder("vscode", "VS Code", find_vscode(),
                        ["vs code", "vscode", "visual studio code", "code"], True, True,
                        "ctrl+alt+i", {"code.exe"}),
        "qoder": Coder("qoder", "Qoder", find_qoder(), ["qoder", "q coder", "cooder"], True, True,
                       "", {"qoder.exe"}),
        "antigravity": Coder("antigravity", "Antigravity", _exists(
            _local("Programs", "Antigravity IDE", "_", "Antigravity IDE.exe")),
            ["antigravity", "antigravity ide", "anti gravity", "anti-gravity"], True, True, "",
            {"antigravity ide.exe"}),
        "antigravity-app": Coder("antigravity-app", "the Antigravity app", _exists(
            _local("Programs", "antigravity", "Antigravity.exe")),
            ["antigravity app", "the antigravity app"], False, False, "", {"antigravity.exe"}),
        "freebuff": Coder("freebuff", "Freebuff", _exists(
            _local("Programs", "@codebufffreebuff-desktop", "Freebuff.exe")),
            ["freebuff", "free buff", "codebuff", "code buff"], False, False, "", {"freebuff.exe"}),
    }


def _expand(value: str) -> str:
    return os.path.expandvars(value.strip())


def load_coders(allowlist: Path | None = None) -> dict[str, Coder]:
    """The built-in tools, with the [coding] table of allowlist.toml on top."""
    coders = builtin_coders()
    path = allowlist or red_home() / "config" / "allowlist.toml"
    try:
        table = tomllib.loads(path.read_text(encoding="utf-8")).get("coding", {})
    except (OSError, tomllib.TOMLDecodeError):
        table = {}
    for key, spec in table.items() if isinstance(table, dict) else ():
        if not isinstance(spec, dict):
            continue
        key = str(key).lower()
        coder = coders.get(key) or Coder(key, str(spec.get("label", key)), None, [key])
        if "label" in spec:
            coder.label = str(spec["label"])
        if "exe" in spec:
            exe = Path(_expand(str(spec["exe"])))
            coder.exe = exe if exe.is_file() else None
            coder.exes = {exe.name.lower()}
        if "aliases" in spec:
            coder.aliases = [str(a).lower() for a in spec["aliases"]] + [key]
        for flag in ("folder_arg", "goto"):
            if flag in spec:
                setattr(coder, flag, bool(spec[flag]))
        if "chat_key" in spec:
            keys = str(spec["chat_key"]).strip()
            if keys:
                parse_keys(keys)           # a typo shows up as an error, not a stray key press
            coder.chat_key = keys
        coders[key] = coder
    return coders


def load_repos(path: Path | None = None) -> dict[str, Path]:
    path = path or red_home() / "config" / "repos.toml"
    try:
        table = tomllib.loads(path.read_text(encoding="utf-8")).get("repos", {})
    except (OSError, tomllib.TOMLDecodeError):
        return {}
    return {str(k).lower(): Path(_expand(str(v))) for k, v in table.items() if isinstance(v, str)}


def _norm(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9 +#.-]", " ", text.lower()).split())


class _CodingTool(Tool):
    coders = staticmethod(load_coders)
    repos = staticmethod(load_repos)

    def __init__(self, desk=None):
        self.desk = desk or Desk()
        self.last_details = ""

    def coder(self, name: str) -> Coder:
        said = _norm(name).removeprefix("the ").strip()
        for coder in self.coders().values():
            if said == coder.key or said in coder.aliases or said == _norm(coder.label):
                if coder.exe is None:
                    raise ToolError(f"{coder.label} doesn't seem to be installed here.")
                return coder
        raise ToolError(f"I don't know a coding tool called {name}. VS Code, Qoder, Antigravity "
                        "and Freebuff work; others go in allowlist.toml under [coding].")

    def project(self, name: str) -> tuple[str, Path] | None:
        said = _norm(name).removesuffix(" project").removesuffix(" repo").strip()
        if not said:
            return None
        repos = self.repos()
        for key, folder in repos.items():
            if said == _norm(key):
                if not folder.is_dir():
                    raise ToolError(f"{key}'s folder isn't there anymore: {folder}")
                return key, folder
        names = ", ".join(sorted(repos)) or "none yet"
        raise ToolError(f"I don't know a project called {name}. The ones in repos.toml: {names}.")

    def find_file(self, name: str, roots: list[Path]) -> Path:
        name = name.strip().strip("\"'")
        if not name or Path(name).is_absolute() or ".." in Path(name).parts:
            raise ToolError("Give me a file inside one of your projects.")
        for root in roots:
            direct = root / name
            if direct.is_file():
                return direct
        wanted = Path(name).name.lower()
        for root in roots:
            seen = 0
            for folder, dirs, files in os.walk(root):
                dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
                for f in files:
                    seen += 1
                    if f.lower() == wanted:
                        return Path(folder) / f
                if seen > MAX_SEARCH:
                    break
        raise ToolError(f"I couldn't find {name} in your projects.")


class OpenInCodingTool(_CodingTool):
    name = "open_in_coding_tool"
    description = ("Open a coding tool, optionally with one of the user's projects or a file at a "
                   "line: 'open Qoder', 'open Freebuff', 'open Antigravity', 'open Red in Qoder', "
                   "'open plan.md in VS Code at line 40'. Always this, not open_app, for Qoder, "
                   "Freebuff and Antigravity, and for VS Code with a project or file.")
    args_schema = {
        "type": "object",
        "properties": {
            "tool": {"type": "string", "minLength": 1, "maxLength": 40,
                     "description": "VS Code, Qoder, Antigravity, Freebuff..."},
            "project": {"type": "string", "maxLength": 60, "description": "A project name, if said."},
            "file": {"type": "string", "maxLength": 120, "description": "A file name, if said."},
            "line": {"type": "integer", "minimum": 1, "maximum": 1_000_000},
        },
        "required": ["tool"],
        "additionalProperties": False,
    }

    def run(self, tool: str, project: str = "", file: str = "", line: int | None = None) -> str:
        coder = self.coder(tool)
        found = self.project(project) if project else None
        args = [str(coder.exe)]
        what = coder.label
        if file:
            roots = [found[1]] if found else list(self.repos().values())
            path = self.find_file(file, [r for r in roots if r.is_dir()])
            if not coder.folder_arg:
                raise ToolError(f"{coder.label} can't open a file from outside, as far as I know.")
            if found:
                args.append(str(found[1]))
            args += ["--goto", f"{path}:{line}"] if coder.goto and line else [str(path)]
            what = f"{path.name}{f' at line {line}' if line else ''} in {coder.label}"
        elif found:
            if coder.folder_arg:
                args.append(str(found[1]))
                what = f"{found[0]} in {coder.label}"
        self.desk.launch(args)
        self.finish_later(lambda: self.desk.front_app(coder.exes))
        if found and not coder.folder_arg and not file:
            return f"Opening {coder.label}. It doesn't take a folder, so pick {found[0]} in it."
        return f"Opening {what}."


class TellCodingAgent(_CodingTool):
    name = "tell_coding_agent"
    description = ("Hand a task to a coding agent in a coding tool, in the user's words: 'tell Qoder "
                   "to fix the failing tests in Red', 'ask Antigravity to add a dark mode to my "
                   "website', 'have VS Code's chat explain this repo'. Reads the task back first.")
    destructive = True
    args_schema = {
        "type": "object",
        "properties": {
            "tool": {"type": "string", "minLength": 1, "maxLength": 40},
            "task": {"type": "string", "minLength": 3, "maxLength": 1000,
                     "description": "The task, in the user's own words."},
            "project": {"type": "string", "maxLength": 60, "description": "A project name, if said."},
        },
        "required": ["tool", "task"],
        "additionalProperties": False,
    }
    max_reply = 400

    def project_in(self, task: str) -> str:
        """'fix the failing tests in Red' -> 'red', when the router left the project out."""
        m = re.search(r"\b(?:in|for|on)\s+(?:the\s+|my\s+)?([\w .-]{1,40}?)(?:\s+(?:project|repo))?[.!?]?$",
                      task, re.I)
        if m and _norm(m.group(1)) in {_norm(k) for k in self.repos()}:
            return m.group(1)
        return ""

    def prepare(self, tool: str, task: str, project: str = "") -> None:
        self.coder(tool)
        project = project or self.project_in(task)
        if project:
            self.project(project)

    def describe(self, tool: str = "", task: str = "", project: str = "") -> str:
        label = self.coder(tool).label
        project = project or self.project_in(task)
        where = f" in {self.project(project)[0]}" if project else ""
        return f'Tell {label}{where}: "{task.strip()}"'

    def run(self, tool: str, task: str, project: str = "") -> str:
        coder = self.coder(tool)
        task = " ".join(task.split())
        project = project or self.project_in(task)
        found = self.project(project) if project else None
        args = [str(coder.exe)] + ([str(found[1])] if found and coder.folder_arg else [])
        self.desk.launch(args)
        if found:
            remember_handoff(found[0], found[1])
        if not self.desk.front_app(coder.exes, wait=12.0):
            self.desk.set_clipboard(task)
            return f"{coder.label} didn't come up in time. The task is on your clipboard to paste."
        self.desk.set_clipboard(task)
        if not coder.chat_key:
            return (f"{coder.label} is open and the task is on your clipboard. Paste it into its chat "
                    "and hit Enter. Say \"tell me when it's done\" and I'll keep an eye on it.")
        self.desk.press(coder.chat_key)
        time.sleep(0.6)
        self.desk.press("ctrl+v")
        time.sleep(0.3)
        if self.desk.foreground_exe() not in coder.exes:
            return (f"Something else jumped in front, so I didn't press Enter. The task is pasted in "
                    f"{coder.label}'s chat; send it when you're ready.")
        self.desk.press("enter")
        return f"Told {coder.label}. Say \"tell me when it's done\" and I'll keep an eye on it."


# --- what did it change? ----------------------------------------------------------------

def handoffs_path() -> Path:
    return red_home() / "cache" / "coding-handoffs.json"


def _git(folder: Path, *args: str, timeout: float = 10.0) -> str:
    git = shutil.which("git")
    if git is None:
        raise ToolError("Git isn't installed, so I can't see what changed.")
    try:
        done = subprocess.run([git, "-C", str(folder), *args], capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=timeout,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.TimeoutExpired) as e:
        raise ToolError(f"Git didn't answer: {e}") from e
    if done.returncode != 0:
        raise ToolError(f"Git couldn't read {folder.name}: {done.stderr.strip()[:120]}")
    return done.stdout


def remember_handoff(name: str, folder: Path, git=_git) -> None:
    try:
        head = git(folder, "rev-parse", "HEAD").strip()
    except ToolError:
        head = ""
    path = handoffs_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    data[name] = {"head": head, "at": datetime.now().isoformat(timespec="seconds")}
    data["_last"] = name
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding="utf-8")
    except OSError:
        pass


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


class WhatDidItChange(_CodingTool):
    name = "what_did_it_change"
    description = ("Say what changed in one of the user's projects since a coding agent was given a "
                   "task (or in the last few hours): 'what did it change?', 'what did Qoder do in "
                   "Red?', 'what changed in my website?'. Read-only.")
    args_schema = {
        "type": "object",
        "properties": {"project": {"type": "string", "maxLength": 60}},
        "required": [],
        "additionalProperties": False,
    }
    max_reply = 500
    git = staticmethod(_git)

    def run(self, project: str = "") -> str:
        try:
            handoffs = json.loads(handoffs_path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            handoffs = {}
        if not project:
            project = handoffs.get("_last", "")
            if not project:
                raise ToolError("Which project? Say \"what changed in Red\", for example.")
        name, folder = self.project(project)
        since = handoffs.get(name, {})
        head = since.get("head", "")
        status = [line for line in self.git(folder, "status", "--porcelain").splitlines() if line.strip()]
        stat = self.git(folder, "diff", "HEAD", "--shortstat").strip()
        if head:
            log_lines = self.git(folder, "log", "--format=%s", f"{head}..HEAD").splitlines()
        else:
            log_lines = self.git(folder, "log", "--format=%s", "--since=3 hours ago").splitlines()
        log_lines = [line.strip() for line in log_lines if line.strip()]
        parts = []
        if status:
            parts.append(f"{_plural(len(status), 'file')} changed and not committed")
            m_add = re.search(r"(\d+) insertion", stat)
            m_del = re.search(r"(\d+) deletion", stat)
            if m_add or m_del:
                parts[-1] += (f", {int(m_add.group(1)) if m_add else 0} lines added and "
                              f"{int(m_del.group(1)) if m_del else 0} removed")
        if log_lines:
            quoted = "; ".join(f'"{s[:70]}"' for s in log_lines[:3])
            more = f" and {len(log_lines) - 3} more" if len(log_lines) > 3 else ""
            parts.append(f"{_plural(len(log_lines), 'new commit')}: {quoted}{more}")
        self.last_details = "\n".join(status[:20] + [f"commit: {s}" for s in log_lines[:10]])
        when = " since the hand-off" if head else " in the last few hours"
        if not parts:
            return f"Nothing's changed in {name}{when}."
        return f"In {name}{when}: " + ". ".join(parts) + "."
