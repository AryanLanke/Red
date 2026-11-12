"""Run Red with no window, so closing PowerShell doesn't stop it.

    python -m red background     start Red hidden, then give you the prompt back
    python -m red stop           stop the hidden Red (and turn the microphone off)
    python -m red status         say whether a hidden Red is running

The hidden Red is the same program with no console. It keeps its process
number in RED_HOME\\logs\\red.pid, and writes to the usual logs. Spoken
confirmations work as usual; typed ones can't, because there is no console.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Callable

log = logging.getLogger(__name__)

PID_NAME = "red.pid"
HOTKEY_PID_NAME = "red-hotkey.pid"
DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_NO_WINDOW = 0x08000000


class BackgroundError(RuntimeError):
    pass


def pid_file(home: Path) -> Path:
    return home / "logs" / PID_NAME


def hotkey_pid_file(home: Path) -> Path:
    return home / "logs" / HOTKEY_PID_NAME


def read_pid(home: Path) -> int | None:
    try:
        return int(pid_file(home).read_text(encoding="ascii").strip())
    except (OSError, ValueError):
        return None


def _read(path: Path) -> int | None:
    try:
        return int(path.read_text(encoding="ascii").strip())
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


def _start_if_needed(home: Path, *, runner: Callable = subprocess.run,
                     popen: Callable = subprocess.Popen, python: str | None = None) -> bool:
    """Start a hidden Red if none is running. True when one was started."""
    pid = read_pid(home)
    if pid is not None and is_running(pid, runner):
        return False
    try:
        start(home, popen=popen, runner=runner, python=python)
    except BackgroundError:
        return False              # another press (or the sign-in shortcut) started it first
    return True


def watch(home: Path, *, hotkey: str, runner: Callable = subprocess.run,
          popen: Callable = subprocess.Popen) -> None:
    """Register the hotkey and start Red whenever it isn't running. Runs until killed.

    Red's own listener handles the hotkey while Red is running, so this only
    acts when Red is down (the pid file says so). A second watcher is refused.
    """
    from .listener import normalize_hotkey
    try:
        key = normalize_hotkey(hotkey)
    except ValueError as e:
        log.warning("Hotkey watcher won't start: %s", e)
        return
    own = hotkey_pid_file(home)
    existing = _read(own)
    if existing is not None and is_running(existing, runner):
        log.info("A hotkey watcher is already running (process %s).", existing)
        return
    own.parent.mkdir(parents=True, exist_ok=True)
    own.write_text(str(os.getpid()), encoding="ascii")
    try:
        from pynput import keyboard
        hotkeys = keyboard.GlobalHotKeys({key: lambda: _start_if_needed(home, runner=runner,
                                                                        popen=popen)})
        hotkeys.start()
        try:
            hotkeys.join()
        finally:
            hotkeys.stop()
    finally:
        own.unlink(missing_ok=True)


def main(action: str, home: Path, hotkey: str | None = None) -> int:
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
            print("Red stopped. The microphone is off. (The Ctrl+Alt+R watcher stays on, "
                  "so the hotkey can start Red again.)")
        else:
            print("No hidden Red is running.")
        return 0
    if action == "hotkey":
        if hotkey is None:
            print("Red's hotkey is turned off (RED_HOTKEY), so there's nothing to watch.")
            return 1
        watch(home, hotkey=hotkey)
        return 0
    pid = read_pid(home)
    running = pid is not None and is_running(pid)
    print(f"Red is running in the background (process {pid})." if running
          else "No hidden Red is running.")
    return 0
