"""The allowlist: the only folders and apps Red may open besides the built-ins.

It lives in RED_HOME\\config\\allowlist.toml (copied from
allowlist.example.toml). A missing file means only the built-in defaults.
Names are lookup keys. Text from the LLM is never used as a path or a
command line, only to find an entry here.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from .config import red_home
from .known_folders import normalize as normalize_folder
from .tools.base import ToolError

# Built-in apps: name -> argv. Plain program names are found on PATH.
DEFAULT_APPS: dict[str, tuple[str, ...]] = {
    "notepad": ("notepad.exe",),
    "calculator": ("calc.exe",),
    "calc": ("calc.exe",),
    "file explorer": ("explorer.exe",),
    "explorer": ("explorer.exe",),
    "task manager": ("taskmgr.exe",),
}


class AllowlistError(ToolError):
    """allowlist.toml exists but can't be used."""


def default_path() -> Path:
    return red_home() / "config" / "allowlist.toml"


def normalize_app(name: str) -> str:
    """Lowercase an app name and drop filler words: "the Notepad app" -> "notepad"."""
    words = name.strip().lower().split()
    while words and words[0] in {"the", "my"}:
        words = words[1:]
    while words and words[-1] in {"app", "application", "program"}:
        words = words[:-1]
    key = " ".join(words)
    if key.endswith(".exe"):
        key = key[:-4]
    return key


@dataclass(frozen=True)
class Allowlist:
    folders: dict[str, Path] = field(default_factory=dict)       # normalized name -> path
    apps: dict[str, tuple[str, ...]] = field(default_factory=dict)  # normalized name -> argv

    def folder(self, name: str) -> Path | None:
        return self.folders.get(normalize_folder(name))

    def app(self, name: str) -> tuple[str, ...] | None:
        """The argv for an app: allowlist entries first, then the built-ins."""
        key = normalize_app(name)
        return self.apps.get(key) or DEFAULT_APPS.get(key)

    def app_names(self) -> list[str]:
        return sorted(set(self.apps) | set(DEFAULT_APPS))


def _expand(value: str) -> str:
    # Only values the user wrote in the file are expanded, never LLM text.
    return os.path.expandvars(os.path.expanduser(value.strip()))


def parse_allowlist(text: str, source: str = "allowlist.toml") -> Allowlist:
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise AllowlistError(f"{source} has a syntax error: {e}") from e

    folders_raw = data.get("folders", {})
    apps_raw = data.get("apps", {})
    if not isinstance(folders_raw, dict) or not isinstance(apps_raw, dict):
        raise AllowlistError(f"{source}: [folders] and [apps] must be tables")

    folders: dict[str, Path] = {}
    for name, value in folders_raw.items():
        if not isinstance(value, str) or not value.strip():
            raise AllowlistError(f"{source}: folder {name!r} must be a path in quotes")
        path = Path(_expand(value))
        if not path.is_absolute():
            raise AllowlistError(f"{source}: folder {name!r} must be a full path, got {value!r}")
        folders[normalize_folder(name)] = path

    apps: dict[str, tuple[str, ...]] = {}
    for name, value in apps_raw.items():
        if isinstance(value, str):
            argv = (value,)
        elif isinstance(value, list) and all(isinstance(v, str) for v in value):
            argv = tuple(value)
        else:
            raise AllowlistError(
                f"{source}: app {name!r} must be a program or a list like [\"program\", \"arg\"]")
        if not argv or not argv[0].strip():
            raise AllowlistError(f"{source}: app {name!r} has no program")
        apps[normalize_app(name)] = (_expand(argv[0]),) + argv[1:]

    return Allowlist(folders=folders, apps=apps)


def load_allowlist(path: Path | None = None) -> Allowlist:
    """Load the allowlist. A missing file gives only the built-in defaults."""
    path = path or default_path()
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return Allowlist()
    except OSError as e:
        raise AllowlistError(f"Can't read {path}: {e}") from e
    return parse_allowlist(text, source=str(path))
