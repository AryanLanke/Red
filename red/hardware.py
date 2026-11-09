"""What this PC can run: GPU memory and RAM, and the model that fits.

`python -m red setup` uses this to pick a starting model (plan.md task 4):

| PC                            | Model                 | Whisper              |
|-------------------------------|-----------------------|----------------------|
| No GPU                        | Qwen2.5 3B            | base.en on the CPU   |
| 4 to 8 GB GPU (RTX 3050/4050) | Qwen3.5 4B on the GPU | base.en on the CPU   |
| 8 GB+ GPU                     | Qwen3.5 9B            | small.en on the GPU  |

No GPU means Qwen2.5 3B, not Qwen3.5: with Ollama 0.40.11, Qwen3.5 can't
reuse the cached router prompt, so on a CPU it re-reads about 3,500 tokens
for every command. Measured on a Ryzen 7 7735HS (2026-11-09, progress.md
5): Qwen2.5 3B routes in 1.4 s, Qwen3.5 2B in 3.3 s, Qwen3.5 4B in 8.3 s.
A GPU with less than 3.5 GB (most integrated graphics) counts as no GPU.

GPU memory comes from nvidia-smi when there's an NVIDIA card, otherwise from
the display driver's registry entry (HardwareInformation.qwMemorySize, which
every WDDM driver writes). RAM comes from GlobalMemoryStatusEx. Only reads;
nothing is installed or changed.
"""

from __future__ import annotations

import ctypes
import shutil
import subprocess
import sys
from dataclasses import dataclass
from typing import Callable

GB = 1024 ** 3
MIN_GPU_GB = 3.5
BIG_GPU_GB = 7.5          # "8 GB" cards report a little under 8
CPU_MODEL = "qwen2.5-3b-instruct-q4_k_m"     # fastest on a CPU (see above)

_DISPLAY_CLASS = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"


@dataclass(frozen=True)
class Choice:
    model: str
    whisper_model: str
    whisper_device: str
    why: str


def recommend(gpu_gb: float | None, ram_gb: float | None) -> Choice:
    """The starting model for a PC with this much GPU memory and RAM."""
    gpu = gpu_gb or 0.0
    if gpu >= BIG_GPU_GB:
        return Choice("qwen3.5-9b", "small.en", "cuda", f"a {gpu:.0f} GB GPU")
    if gpu >= MIN_GPU_GB:
        return Choice("qwen3.5-4b", "base.en", "cpu", f"a {gpu:.0f} GB GPU")
    if gpu_gb is None and ram_gb is None:
        return Choice("qwen3.5-4b", "base.en", "cpu", "hardware that couldn't be read")
    ram = f" and {ram_gb:.0f} GB of RAM" if ram_gb else ""
    return Choice(CPU_MODEL, "base.en", "cpu", f"no GPU{ram}")


def nvidia_gpu_gb(run: Callable = subprocess.run, which: Callable = shutil.which) -> float | None:
    """The biggest NVIDIA GPU's memory in GB, from nvidia-smi, or None."""
    exe = which("nvidia-smi")
    if not exe:
        return None
    try:
        out = run([exe, "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
                  capture_output=True, text=True, timeout=10,
                  creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError):
        return None
    sizes = []
    for line in (out.stdout or "").splitlines():
        try:
            sizes.append(float(line.strip()) / 1024)      # MiB -> GiB
        except ValueError:
            continue
    return max(sizes) if sizes and out.returncode == 0 else None


def driver_gpu_gb() -> float | None:
    """The biggest display adapter's dedicated memory, from the driver's registry entry."""
    if sys.platform != "win32":
        return None
    import winreg
    best = 0
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _DISPLAY_CLASS) as cls:
            for i in range(64):
                try:
                    sub = winreg.EnumKey(cls, i)
                except OSError:
                    break
                try:
                    with winreg.OpenKey(cls, sub) as key:
                        value, _ = winreg.QueryValueEx(key, "HardwareInformation.qwMemorySize")
                except OSError:
                    continue
                if isinstance(value, int):
                    best = max(best, value)
                elif isinstance(value, bytes) and len(value) >= 8:
                    best = max(best, int.from_bytes(value[:8], "little"))
    except OSError:
        return None
    return best / GB if best else None


def gpu_gb() -> float | None:
    return nvidia_gpu_gb() or driver_gpu_gb()


def ram_gb() -> float | None:
    """Total physical memory in GB (GlobalMemoryStatusEx)."""
    if sys.platform != "win32":
        return None

    class MemoryStatus(ctypes.Structure):
        _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

    status = MemoryStatus()
    status.dwLength = ctypes.sizeof(MemoryStatus)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        return None
    return status.ullTotalPhys / GB


def detect() -> Choice:
    return recommend(gpu_gb(), ram_gb())
