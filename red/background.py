"""Run Red with no window, so closing PowerShell doesn't stop it.

    python -m red background     start Red hidden, then give you the prompt back
    python -m red stop           stop the hidden Red (and turn the microphone off)
    python -m red status         say whether a hidden Red is running

The hidden Red is the same program with no console. It keeps its process
number in RED_HOME\\logs\\red.pid, and writes to the usual logs. Spoken
confirmations work as usual; typed ones can't, because there is no console.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Callable

PID_NAME = "red.pid"
DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_NO_WINDOW = 0x08000000


class BackgroundError(RuntimeError):
    pass


def pid_file(home: Path) -> Path:
    return home / "logs" / PID_NAME


def read_pid(home: Path) -> int | None:
    try:
        return int(pid_file(home).read_text(encoding="ascii").strip())
    except (OSError, ValueError):
        return None


def is_running(pid: int, runner: Callable = subprocess.run) -> bool:
    """Whether a python process with this id exists (asked through tasklist)."""
    out = runner(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                 capture_output=True, text=True, timeout=20)
    return f'"{pid}"' in out.stdout and "python" in out.stdout.lower()


def _pythonw() -> str:
    exe = Path(sys.executable)
    candidate = exe.with_name("pythonw.exe")
    return str(candidate if candidate.is_file() else exe)


def start(home: Path, *, popen: Callable = subprocess.Popen,
          runner: Callable = subprocess.run, python: str | None = None) -> int:
    """Start a hidden Red. Returns its process id."""
    existing = read_pid(home)
    if existing is not None and is_running(existing, runner):
        raise BackgroundError(f"Red is already running in the background (process {existing}). "
                              "Use 'python -m red stop' first to restart it.")
    pid_file(home).parent.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, RED_HOME=str(home))
    proc = popen([python or _pythonw(), "-m", "red", "--home", str(home)],
                 env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                 stderr=subprocess.DEVNULL,
                 creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW)
    pid_file(home).write_text(str(proc.pid), encoding="ascii")
    return proc.pid


def stop(home: Path, *, runner: Callable = subprocess.run) -> bool:
    """Stop the hidden Red and everything it started. Returns False if none was running."""
    pid = read_pid(home)
    try:
        if pid is None or not is_running(pid, runner):
            return False
        runner(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, timeout=30)
        return True
    finally:
        pid_file(home).unlink(missing_ok=True)


def main(action: str, home: Path) -> int:
    if action == "background":
        try:
            pid = start(home)
        except BackgroundError as e:
            print(e)
            return 1
        print(f"Red is running in the background (process {pid}). It takes about 40 seconds to "
              "load; then say \"Hey Red\" or press Ctrl+Alt+R.\nStop it with: python -m red stop")
        return 0
    if action == "stop":
        if stop(home):
            print("Red stopped. The microphone is off.")
        else:
            print("No hidden Red is running.")
        return 0
    pid = read_pid(home)
    running = pid is not None and is_running(pid)
    print(f"Red is running in the background (process {pid})." if running
          else "No hidden Red is running.")
    return 0
