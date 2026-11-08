"""Child processes that can't outlive Red.

On Windows, each server runs inside a Job Object with "kill on close". If Red
exits or crashes, Windows ends the server and anything it started (such as
Ollama's model runner), so nothing is left holding GPU memory.
"""

from __future__ import annotations

import atexit
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def http_ok(url: str, timeout: float = 2) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status == 200
    except (urllib.error.URLError, ConnectionError, TimeoutError, OSError):
        return False


class _KillOnCloseJob:
    """Windows Job Object that ends all its processes when closed."""

    def __init__(self) -> None:
        import ctypes
        from ctypes import wintypes

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateJobObjectW.restype = wintypes.HANDLE
        k32.CreateJobObjectW.argtypes = (wintypes.LPVOID, wintypes.LPCWSTR)
        k32.SetInformationJobObject.argtypes = (wintypes.HANDLE, ctypes.c_int,
                                                wintypes.LPVOID, wintypes.DWORD)
        k32.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
        k32.TerminateJobObject.argtypes = (wintypes.HANDLE, wintypes.UINT)
        k32.CloseHandle.argtypes = (wintypes.HANDLE,)

        class IO_COUNTERS(ctypes.Structure):
            _fields_ = [(n, ctypes.c_ulonglong) for n in (
                "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

        class BASIC(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_int64),
                ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class EXTENDED(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", BASIC),
                ("IoInfo", IO_COUNTERS),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        self._k32 = k32
        self._handle = k32.CreateJobObjectW(None, None)
        if not self._handle:
            raise OSError(ctypes.get_last_error(), "CreateJobObject failed")
        info = EXTENDED()
        info.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not k32.SetInformationJobObject(self._handle, 9, ctypes.byref(info), ctypes.sizeof(info)):
            raise OSError(ctypes.get_last_error(), "SetInformationJobObject failed")

    def add(self, proc: subprocess.Popen) -> None:
        self._k32.AssignProcessToJobObject(self._handle, int(proc._handle))

    def close(self) -> None:
        if self._handle:
            self._k32.TerminateJobObject(self._handle, 1)
            self._k32.CloseHandle(self._handle)
            self._handle = None


class ManagedServer:
    """Start a local server, wait until it answers, and stop it with Red."""

    def __init__(self, name: str, cmd: list[str], health_url: str, log_path: Path,
                 env: dict[str, str] | None = None):
        self.name, self.cmd, self.health_url, self.log_path = name, cmd, health_url, log_path
        self.env = env
        self._proc: subprocess.Popen | None = None
        self._job: _KillOnCloseJob | None = None
        self._log = None

    @property
    def returncode(self) -> int | None:
        return self._proc.poll() if self._proc else None

    def start(self, timeout: float) -> None:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._log = self.log_path.open("ab")
        self._proc = subprocess.Popen(
            self.cmd, env=self.env, stdout=self._log, stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if sys.platform == "win32":
            self._job = _KillOnCloseJob()
            self._job.add(self._proc)
        atexit.register(self.stop)

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._proc.poll() is not None:
                code = self._proc.returncode
                self.stop()
                raise ServerExited(self.name, code, self.log_path)
            if http_ok(self.health_url):
                return
            time.sleep(0.5)
        self.stop()
        raise TimeoutError(f"{self.name} did not become ready in {timeout:.0f}s. See {self.log_path}")

    def stop(self) -> None:
        if self._job:
            self._job.close()  # ends the server and its child processes
            self._job = None
        if self._proc and self._proc.poll() is None:
            self._proc.kill()
        if self._proc:
            try:
                self._proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                pass
        self._proc = None
        if self._log:
            self._log.close()
            self._log = None


class ServerExited(RuntimeError):
    def __init__(self, name: str, code: int, log_path: Path):
        self.code = code & 0xFFFFFFFF if code is not None else None
        super().__init__(f"{name} exited early (code 0x{self.code:08X}). See {log_path}")


def child_env(**overrides: str) -> dict[str, str]:
    env = os.environ.copy()
    env.update(overrides)
    return env
