"""What the Start menu's "Red" does:  pythonw -m red.app.launch

- the first time (no config\\first-run.json yet): the first-run wizard, then Red starts
- after that: start Red in the background if it isn't running, and say so; if it is, open the settings window

From the installer, RED_HOME is the install folder (python\\ and app\\ sit inside it), unless RED_HOME is set.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Callable

MARKER = "first-run.json"


def install_root(executable: str | None = None) -> Path | None:
    """The folder the installer made (<root>\\python\\pythonw.exe and <root>\\app\\red), else None."""
    exe = Path(executable or sys.executable)
    root = exe.resolve().parent.parent
    return root if (root / "app" / "red").is_dir() and exe.parent.name.lower() == "python" else None


def marker_path(home: Path) -> Path:
    return Path(home) / "config" / MARKER


def first_run_done(home: Path) -> bool:
    return marker_path(home).is_file()


def mark_first_run_done(home: Path, **details) -> Path:
    path = marker_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"done": datetime.now().isoformat(timespec="seconds"), **details}), encoding="utf-8")
    return path


def main(argv: list[str] | None = None, *, wizard: Callable | None = None, start: Callable | None = None,
         running: Callable | None = None, open_settings: Callable | None = None) -> int:
    root = install_root()
    if root is not None:
        os.environ.setdefault("RED_HOME", str(root))
    from red import background
    from red.config import load_settings
    settings = load_settings()
    home = settings.home
    if not first_run_done(home):
        if wizard is None:
            from .first_run import run_wizard as wizard
        if not wizard(settings):
            return 0                       # closed without finishing: nothing is started, it asks again next time
    pid = background.read_pid(home)
    is_on = (running or (lambda: pid is not None and background.is_running(pid)))()
    if not is_on:
        (start or (lambda: background.start(home)))()
        return 0
    if open_settings is None:
        from . import main as open_app
        return open_app(settings)
    return open_settings(settings)


if __name__ == "__main__":
    raise SystemExit(main())
