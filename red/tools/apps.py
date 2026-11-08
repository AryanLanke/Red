"""Well-known apps found through the registry's App Paths, never by guessing paths.

Installers register their main program under
HKCU or HKLM\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\App Paths\\<exe>.
Red maps a fixed list of spoken names ("PowerPoint", "Word") to those exe
names, and opens an app only if Windows says it's installed.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

_APP_PATHS = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths"

# Display name, the App Paths keys to try in order, and other ways to say it.
KNOWN_APPS: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...] = (
    ("PowerPoint", ("powerpnt.exe",), ("powerpoint", "power point", "ppt", "powerpoint presentation")),
    ("Word", ("winword.exe",), ("word", "ms word", "word document")),
    ("Excel", ("excel.exe",), ("excel", "ms excel", "excel spreadsheet", "spreadsheet")),
    ("Outlook", ("outlook.exe", "olk.exe"), ("outlook", "outlook mail")),
    ("OneNote", ("onenote.exe",), ("onenote", "one note")),
    ("Access", ("msaccess.exe",), ("access", "ms access")),
    ("Publisher", ("mspub.exe",), ("publisher",)),
    ("Teams", ("ms-teams.exe", "teams.exe"), ("teams", "ms teams")),
    ("Chrome", ("chrome.exe",), ("chrome", "google chrome")),
    ("Edge", ("msedge.exe",), ("edge", "edge browser")),
    ("Firefox", ("firefox.exe",), ("firefox", "mozilla firefox")),
    ("VS Code", ("code.exe",), ("vs code", "vscode", "visual studio code", "code")),
    ("Paint", ("mspaint.exe",), ("paint", "ms paint")),
    ("Snipping Tool", ("snippingtool.exe",), ("snipping tool",)),
    ("Terminal", ("wt.exe",), ("terminal", "windows terminal")),
    ("VLC", ("vlc.exe",), ("vlc", "vlc player", "vlc media player")),
    ("Windows Media Player", ("wmplayer.exe",), ("windows media player", "media player")),
    ("WinRAR", ("winrar.exe",), ("winrar",)),
)

_ALIASES = {alias: entry for entry in KNOWN_APPS for alias in entry[2]}


def app_key(name: str) -> str:
    """'Microsoft PowerPoint app' -> 'powerpoint'.

    Same rules as allowlist.normalize_app (not imported: allowlist imports tools).
    """
    words = name.strip().lower().split()
    while words and words[0] in {"the", "my", "microsoft", "office"}:
        words = words[1:]
    while words and words[-1] in {"app", "application", "program"}:
        words = words[:-1]
    key = " ".join(words)
    return key[:-4] if key.endswith(".exe") else key


def read_app_path(exe: str) -> str | None:
    """The registered full path for an exe name, from HKCU then HKLM (both views)."""
    if sys.platform != "win32":
        return None
    import winreg

    places = [(winreg.HKEY_CURRENT_USER, 0),
              (winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_64KEY),
              (winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_32KEY)]
    for hive, view in places:
        try:
            with winreg.OpenKey(hive, rf"{_APP_PATHS}\{exe}", 0,
                                winreg.KEY_READ | view) as key:
                value, _ = winreg.QueryValueEx(key, "")
        except OSError:
            continue
        if isinstance(value, str) and value.strip():
            return winreg.ExpandEnvironmentStrings(value.strip().strip('"'))
    return None


@dataclass(frozen=True)
class FoundApp:
    name: str          # "PowerPoint"
    exe: str           # the App Paths key, e.g. "powerpnt.exe"
    path: Path         # where it's installed

    @property
    def packaged(self) -> bool:
        """Store apps live under WindowsApps and must be started through the shell."""
        return "windowsapps" in (p.lower() for p in self.path.parts)


class AppPaths:
    def __init__(self, read: Callable[[str], str | None] = read_app_path,
                 exists: Callable[[Path], bool] = Path.exists):
        self._read = read
        self._exists = exists

    def known(self, name: str) -> str | None:
        """The display name if `name` is one of the well-known apps (installed or not)."""
        entry = _ALIASES.get(app_key(name))
        return entry[0] if entry else None

    def find(self, name: str) -> FoundApp | None:
        """The installed app for a spoken name, or None."""
        entry = _ALIASES.get(app_key(name))
        if entry is None:
            return None
        display, exes, _ = entry
        for exe in exes:
            value = self._read(exe)
            if not value:
                continue
            path = Path(value)
            # Packaged apps can't be checked with exists(); Windows resolves them.
            found = FoundApp(display, exe, path)
            if found.packaged or self._exists(path):
                return found
        return None
