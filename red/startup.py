"""Start Red when you sign in: two shortcuts in your Startup folder.

    python -m red startup on       create the shortcuts
    python -m red startup off      remove them
    python -m red startup          say whether they're on

"Red.lnk" runs pythonw.exe with "-m red --home <RED_HOME> background", so Red
starts hidden with no console window. "Red Hotkey.lnk" runs a tiny watcher
(red/background.py watch) that keeps Ctrl+Alt+R working even when Red isn't
running: the hotkey then starts Red. The .lnk files are written by a fixed
PowerShell script; the paths reach it only through environment variables, so
nothing is parsed as script.
"""

from __future__ import annotations

import base64
import os
import subprocess
import sys
from pathlib import Path
from typing import Callable

SHORTCUT_NAME = "Red.lnk"
HOTKEY_SHORTCUT_NAME = "Red Hotkey.lnk"
STARTUP_FOLDER_ID = "{B97D20BB-F46A-4C97-BA10-5E3608430854}"   # FOLDERID_Startup
WINDOW_MINIMIZED = 7

_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:RED_LNK_PATH)
$s.TargetPath = $env:RED_LNK_TARGET
$s.Arguments = $env:RED_LNK_ARGS
$s.WorkingDirectory = $env:RED_LNK_CWD
$s.WindowStyle = [int]$env:RED_LNK_STYLE
$s.Description = 'Red voice assistant'
$s.Save()
"""


class StartupError(RuntimeError):
    pass


def startup_folder() -> Path:
    """The user's Startup folder (shell:startup)."""
    from .known_folders import _shell_folder_path
    path = _shell_folder_path(STARTUP_FOLDER_ID)
    if path is not None:
        return path
    appdata = os.environ.get("APPDATA", "").strip()
    if not appdata:
        raise StartupError("Can't find your Startup folder")
    return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def _python() -> str:
    # pythonw.exe has no console window, so Red starts hidden at sign-in.
    exe = Path(sys.executable)
    if exe.name.lower() != "pythonw.exe":
        candidate = exe.with_name("pythonw.exe")
        if candidate.is_file():
            exe = candidate
    return str(exe)


def _powershell() -> str:
    root = os.environ.get("SystemRoot")
    if root:
        ps = Path(root) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
        if ps.is_file():
            return str(ps)
    return "powershell.exe"


class Startup:
    def __init__(self, home: Path, folder: Callable[[], Path] = startup_folder,
                 runner=subprocess.run, python: Callable[[], str] = _python,
                 workdir: Path | None = None):
        self.home = Path(home)
        self._folder = folder
        self._runner = runner
        self._python = python
        self.workdir = workdir or Path(__file__).resolve().parent.parent

    @property
    def shortcut(self) -> Path:
        return self._folder() / SHORTCUT_NAME

    @property
    def hotkey_shortcut(self) -> Path:
        return self._folder() / HOTKEY_SHORTCUT_NAME

    def is_on(self) -> bool:
        return self.shortcut.is_file()

    def on(self) -> str:
        path = self.shortcut
        path.parent.mkdir(parents=True, exist_ok=True)
        self._write_shortcut(path, ["-m", "red", "--home", str(self.home), "background"])
        self._write_shortcut(self.hotkey_shortcut,
                             ["-m", "red", "--home", str(self.home), "hotkey"])
        return (f"Red will start when you sign in ({path}), and Ctrl+Alt+R will start it "
                f"if it isn't running ({self.hotkey_shortcut}).")

    def _write_shortcut(self, path: Path, args: list[str]) -> None:
        env = dict(os.environ,
                   RED_LNK_PATH=str(path),
                   RED_LNK_TARGET=self._python(),
                   RED_LNK_ARGS=subprocess.list2cmdline(args),
                   RED_LNK_CWD=str(self.workdir),
                   RED_LNK_STYLE=str(WINDOW_MINIMIZED))
        encoded = base64.b64encode(_SCRIPT.encode("utf-16-le")).decode("ascii")
        try:
            result = self._runner(
                [_powershell(), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                 "-EncodedCommand", encoded],
                env=env, capture_output=True, text=True, timeout=30,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except (OSError, subprocess.SubprocessError) as e:
            raise StartupError(f"Couldn't create the shortcut: {e}") from e
        if result.returncode != 0 or not path.is_file():
            detail = " ".join(f"{result.stdout or ''} {result.stderr or ''}".split())[:200]
            raise StartupError(f"Couldn't create the shortcut {path}: {detail or result.returncode}")

    def off(self) -> str:
        removed = []
        for path in (self.shortcut, self.hotkey_shortcut):
            if path.is_file():
                try:
                    path.unlink()
                    removed.append(path.name)
                except OSError as e:
                    raise StartupError(f"Couldn't remove {path}: {e}") from e
        if not removed:
            return "Red wasn't set to start at sign-in."
        return "Red won't start at sign-in any more."

    def status(self) -> str:
        if self.is_on():
            return (f"Red starts when you sign in ({self.shortcut}), and Ctrl+Alt+R starts it "
                    f"if it isn't running ({self.hotkey_shortcut}).")
        return "Red doesn't start at sign-in. Turn it on with: python -m red startup on"


def main(action: str | None, home: Path, startup: Startup | None = None) -> int:
    startup = startup or Startup(home)
    try:
        if action == "on":
            print(startup.on())
        elif action == "off":
            print(startup.off())
        else:
            print(startup.status())
    except StartupError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0
