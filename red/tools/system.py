"""System tools: folders, apps, shutdown, restart.

Every side effect (opening a folder, starting a program, running
shutdown.exe, reading the clock) is passed in through the constructor, so
tests use fakes and never open a window or schedule a shutdown.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, ClassVar

from .. import allowlist as _allowlist
from .. import known_folders as _known
from .. import windows as _windows
from .apps import AppPaths, FoundApp
from .base import Tool, ToolError

MAX_DELAY_MINUTES = 24 * 60

# shutdown.exe exit code when /a finds nothing scheduled.
ERROR_NO_SHUTDOWN_IN_PROGRESS = 1116
# CreateProcess error for programs that must start elevated (Task Manager).
ERROR_ELEVATION_REQUIRED = 740

_NO_ARGS = {"type": "object", "properties": {}, "additionalProperties": False}

_DELAY_ARGS = {
    "type": "object",
    "properties": {
        "minutes": {"type": "integer", "minimum": 0, "maximum": MAX_DELAY_MINUTES,
                    "description": "Delay in minutes. 0 means now."},
    },
    "required": ["minutes"],
    "additionalProperties": False,
}

AllowlistSource = Callable[[], "_allowlist.Allowlist"]


def _allowlist_source(allowlist) -> AllowlistSource:
    """None: reload RED_HOME's allowlist.toml on every command, so edits apply at once."""
    if allowlist is None:
        return _allowlist.load_allowlist
    if callable(allowlist):
        return allowlist
    return lambda: allowlist


def _default_startfile(path, *args, **kwargs):
    os.startfile(path, *args, **kwargs)  # type: ignore[attr-defined]  # Windows only


def _same_path(a: str | Path, b: str | Path) -> bool:
    def norm(p):
        return os.path.normcase(os.path.normpath(str(p))).rstrip("\\/")
    return norm(a) == norm(b)


def _looks_like_path(text: str) -> bool:
    text = text.strip()
    return "\\" in text or "/" in text or (len(text) >= 2 and text[1] == ":")


class OpenFolder(Tool):
    name = "open_folder"
    description = ("Open a folder in File Explorer. Use a known folder name such as "
                   "Downloads, Documents, Desktop, Pictures, Music, or Videos, or a full path.")
    args_schema = {
        "type": "object",
        "properties": {"folder": {"type": "string", "minLength": 1, "maxLength": 260}},
        "required": ["folder"],
        "additionalProperties": False,
    }

    def __init__(self, allowlist=None,
                 startfile: Callable[[str], None] = _default_startfile,
                 known: Callable[[], dict[str, Path]] = _known.all_known_folders,
                 watch: Callable | None = None):
        self._allowlist = _allowlist_source(allowlist)
        self._startfile = startfile
        self._known = known
        self._watch = watch      # None: red.windows.watch, looked up at run time

    def _find(self, folder: str) -> tuple[str, Path] | None:
        """(display name, path) for a folder name, or None. Never guesses."""
        allow = self._allowlist()
        known = self._known()
        if _looks_like_path(folder):
            # A full path is only a lookup key too: it must be one of the folders below.
            for name, path in list(allow.folders.items()) + list(known.items()):
                if _same_path(folder, path):
                    return (name.capitalize() if name in known else name), path
            return None
        path = allow.folder(folder)
        if path is not None:
            return _allowlist.normalize_folder(folder), path
        key = _known.canonical(folder)
        if key is not None and key in known:
            return key.capitalize(), known[key]
        return None

    def run(self, folder: str) -> str:
        found = self._find(folder)
        if found is None:
            raise ToolError(f"I don't know a folder called {folder}. "
                            "Add it to allowlist.toml to open it.")
        name, path = found
        # Also stops a file (or a program) from being "opened" as a folder.
        if not path.is_dir():
            raise ToolError(f"The {name} folder doesn't exist: {path}")
        watcher = (self._watch or _windows.watch)(_windows.folder_target(path.name or name))
        self._startfile(str(path))
        self.finish_later(watcher)       # bring the Explorer window to the front
        return f"Opening {name}."


class OpenApp(Tool):
    name = "open_app"
    description = ("Start an application by name, for example Notepad, Calculator, VS Code, "
                   "Word, Excel, PowerPoint, Outlook, or Chrome. Websites like YouTube or "
                   "GitHub are not apps: use open_url.")
    args_schema = {
        "type": "object",
        "properties": {"app": {"type": "string", "minLength": 1, "maxLength": 100}},
        "required": ["app"],
        "additionalProperties": False,
    }

    def __init__(self, allowlist=None, popen=subprocess.Popen, which=shutil.which,
                 startfile=_default_startfile, app_paths: AppPaths | None = None,
                 watch: Callable | None = None):
        self._allowlist = _allowlist_source(allowlist)
        self._popen = popen
        self._which = which
        self._startfile = startfile
        self._app_paths = app_paths or AppPaths()
        self._watch = watch      # None: red.windows.watch, looked up at run time

    def run(self, app: str) -> str:
        argv = self._allowlist().app(app)
        if argv is None:
            # Well-known apps (Office, browsers) that Windows says are installed.
            found = self._app_paths.find(app)
            if found is not None:
                return self._start_registered(found)
            known = self._app_paths.known(app)
            if known:
                raise ToolError(f"{known} doesn't seem to be installed.")
            raise ToolError(f"I don't know an app called {app}. "
                            "Add it to allowlist.toml to open it.")
        program = self._which(argv[0])
        if program is None:
            raise ToolError(f"I couldn't find the program for {app}: {argv[0]}")
        argv = (program,) + tuple(argv[1:])
        # .cmd and .bat launchers (like VS Code's "code") would flash a console window.
        flags = (getattr(subprocess, "CREATE_NO_WINDOW", 0)
                 if program.lower().endswith((".cmd", ".bat"))
                 else getattr(subprocess, "CREATE_NEW_CONSOLE", 0))
        watcher = (self._watch or _windows.watch)(_windows.app_target(program, app))
        try:
            # A list and no shell: nothing in argv is ever parsed as a command line.
            proc = self._popen(list(argv), shell=False, close_fds=True, creationflags=flags,
                               stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL)
            watcher.add_pid(getattr(proc, "pid", None))
        except OSError as e:
            if getattr(e, "winerror", None) != ERROR_ELEVATION_REQUIRED:
                raise ToolError(f"I couldn't start {app}: {e.strerror or e}") from e
            # Programs like Task Manager need the shell to start them elevated.
            self._startfile(program, arguments=subprocess.list2cmdline(argv[1:]))
        self.finish_later(watcher)       # bring its window to the front while Red speaks
        return f"Opening {app.strip()}."

    def _start_registered(self, found: FoundApp) -> str:
        # The shell starts the registered program: by its App Paths name for Store
        # apps (which can't be started by path), by full path for everything else.
        target = found.exe if found.packaged else str(found.path)
        watcher = (self._watch or _windows.watch)(_windows.app_target(found.exe, found.name))
        try:
            self._startfile(target)
        except OSError as e:
            raise ToolError(f"I couldn't start {found.name}: {e.strerror or e}") from e
        self.finish_later(watcher)
        return f"Opening {found.name}."


def _shutdown_exe() -> str:
    root = os.environ.get("SystemRoot")
    if root and (Path(root) / "System32" / "shutdown.exe").is_file():
        return str(Path(root) / "System32" / "shutdown.exe")
    return "shutdown.exe"


def run_shutdown_exe(runner, *args: str) -> subprocess.CompletedProcess:
    try:
        return runner([_shutdown_exe(), *args], capture_output=True, text=True,
                      errors="replace", timeout=15,
                      creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError) as e:
        raise ToolError(f"I couldn't run shutdown.exe: {e}") from e


def _output(result: subprocess.CompletedProcess) -> str:
    text = " ".join(f"{result.stdout or ''} {result.stderr or ''}".split())
    return text[:150] or f"exit code {result.returncode}"


def format_duration(minutes: int) -> str:
    """180 -> "3 hours", 90 -> "1 hour and 30 minutes"."""
    hours, mins = divmod(minutes, 60)
    parts = []
    if hours:
        parts.append(f"{hours} hour{'s' if hours != 1 else ''}")
    if mins or not hours:
        parts.append(f"{mins} minute{'s' if mins != 1 else ''}")
    return " and ".join(parts)


def format_clock(at: datetime, now: datetime) -> str:
    """"11:40 PM", or "1:15 AM tomorrow" when it's on the next day."""
    text = at.strftime("%I:%M %p").lstrip("0")
    days = (at.date() - now.date()).days
    if days == 1:
        text += " tomorrow"
    elif days > 1:
        text += at.strftime(" on %A")
    return text


class _PowerTool(Tool):
    """Shared code for shutdown and restart."""

    destructive = True
    args_schema = _DELAY_ARGS
    _flag: ClassVar[str]   # "/s" or "/r"
    _verb: ClassVar[str]   # "Shut down"
    _doing: ClassVar[str]  # "Shutting down"
    _noun: ClassVar[str]   # "shutdown"

    def __init__(self, runner=subprocess.run, now: Callable[[], datetime] = datetime.now):
        self._runner = runner
        self._now = now

    def _clock(self, minutes: int) -> str:
        now = self._now()
        return format_clock(now + timedelta(minutes=minutes), now)

    def describe(self, minutes: int) -> str:
        if minutes == 0:
            return f"{self._verb} now"
        return f"{self._verb} in {format_duration(minutes)} (at {self._clock(minutes)})"

    def run(self, minutes: int) -> str:
        if not 0 <= minutes <= MAX_DELAY_MINUTES:  # the schema already checks this
            raise ToolError(f"The delay must be between 0 and {MAX_DELAY_MINUTES} minutes.")
        # A new schedule replaces the old one. With nothing scheduled, /a fails; that's fine.
        run_shutdown_exe(self._runner, "/a")
        result = run_shutdown_exe(self._runner, self._flag, "/t", str(minutes * 60))
        if result.returncode != 0:
            raise ToolError(f"Windows didn't schedule the {self._noun}: {_output(result)}")
        if minutes == 0:
            return f"{self._doing} now."
        return (f"{self._doing} in {format_duration(minutes)}, at {self._clock(minutes)}. "
                f"Say cancel the {self._noun} to stop it.")


class Shutdown(_PowerTool):
    name = "shutdown"
    description = "Shut down the computer after a delay in minutes (convert hours to minutes)."
    _flag, _verb, _doing, _noun = "/s", "Shut down", "Shutting down", "shutdown"


class Restart(_PowerTool):
    name = "restart"
    description = "Restart the computer after a delay in minutes (convert hours to minutes)."
    _flag, _verb, _doing, _noun = "/r", "Restart", "Restarting", "restart"


class CancelShutdown(Tool):
    name = "cancel_shutdown"
    description = "Cancel a scheduled shutdown or restart."
    args_schema = _NO_ARGS

    def __init__(self, runner=subprocess.run):
        self._runner = runner

    def run(self) -> str:
        result = run_shutdown_exe(self._runner, "/a")
        if result.returncode == 0:
            return "Cancelled. Your PC won't shut down or restart."
        if result.returncode == ERROR_NO_SHUTDOWN_IN_PROGRESS:
            return "Nothing was scheduled, so there was nothing to cancel."
        raise ToolError(f"I couldn't cancel it: {_output(result)}")
