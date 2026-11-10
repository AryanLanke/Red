"""Reading and writing RED_HOME\\config\\.env without wrecking what's in it.

The app only owns the keys it shows. Everything else - comments, blank
lines, keys the user added, keys from a newer Red - is left exactly as it
was. Keys already in the file are changed in place (keeping any comment at
the end of the line); keys that aren't there yet are appended once, under a
short marker, so saving twice never duplicates them.
"""

from __future__ import annotations

import os
from pathlib import Path

from red.config import Settings

EXAMPLE_ENV = Path(__file__).resolve().parents[2] / ".env.example"
MARKER = "# --- Saved by the Red app ---"


def _format(value: str) -> str:
    """One .env value: bare when it's simple, quoted when it has spaces or #."""
    text = str(value)
    if text == "":
        return ""
    if any(ch.isspace() or ch in '#"\'`' for ch in text):
        escaped = text.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return text


def _split_comment(rest: str) -> tuple[str, str]:
    """' x  # why' -> (' x', '  # why'); a # inside quotes is part of the value."""
    quote = ""
    escaped = False
    for i, ch in enumerate(rest):
        if escaped:
            escaped = False
            continue
        if quote:
            if ch == "\\":
                escaped = True
            elif ch == quote:
                quote = ""
            continue
        if ch in "\"'":
            quote = ch
        elif ch == "#" and (i == 0 or rest[i - 1].isspace()):
            end = i
            while end > 0 and rest[end - 1].isspace():
                end -= 1
            return rest[:end], rest[end:]
    return rest, ""


def update_env(text: str, values: dict[str, str]) -> str:
    """`text` with each KEY in `values` set, comments and other keys untouched."""
    newline = "\r\n" if "\r\n" in text else "\n"
    lines = text.splitlines()
    seen: set[str] = set()
    for i, line in enumerate(lines):
        stripped = line.lstrip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            continue
        key, rest = line.split("=", 1)
        key = key.strip()
        if key not in values:
            continue
        _, comment = _split_comment(rest)
        lines[i] = f"{key}={_format(values[key])}{comment}"
        seen.add(key)
    missing = [key for key in values if key not in seen]
    if missing:
        if lines and lines[-1].strip():
            lines.append("")
        lines.append(MARKER)
        lines.extend(f"{key}={_format(values[key])}" for key in missing)
    return newline.join(lines) + newline


def read_env(path: Path) -> str:
    """The .env text, or an empty string when it isn't there yet."""
    try:
        return Path(path).read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""


def save_values(settings: Settings, values: dict[str, str]) -> Path:
    """Write the app's values into RED_HOME\\config\\.env; returns the path."""
    env = settings.config_dir / ".env"
    text = read_env(env)
    if not text and EXAMPLE_ENV.is_file():
        text = EXAMPLE_ENV.read_text(encoding="utf-8")
    if not text:
        text = "# Red's settings, as saved by the Red app.\n"
    env.parent.mkdir(parents=True, exist_ok=True)
    temp = env.with_name(env.name + ".tmp")
    temp.write_text(update_env(text, values), encoding="utf-8")
    os.replace(temp, env)
    return env
