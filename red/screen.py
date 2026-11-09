"""Reading the screen, only when you ask ("what's on my screen?").

What Red looks at:
- the window you're using: its title and the program's name,
- the text on the screen, read with the OCR engine built into Windows.

Everything stays on this PC. The screenshot goes to a temporary file under
RED_HOME\\cache only for the OCR step and is deleted straight away; the
text goes only to the local model, and nothing is logged except the window
title. Windows' OCR runs through Windows PowerShell because Smart App
Control blocks the unsigned Python OCR packages.
"""

from __future__ import annotations

import base64
import ctypes
import logging
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

log = logging.getLogger(__name__)

OCR_TIMEOUT = 45          # seconds; the first run after boot is the slow one
MAX_TEXT = 2500           # characters of screen text handed to the model

# A fixed script: the image path arrives in an environment variable, so
# nothing from the screen or the user is ever parsed as script.
OCR_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
    $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
function Await($op, [Type]$type) {
    $t = $asTask.MakeGenericMethod($type).Invoke($null, @($op)); $t.Wait(-1) | Out-Null; $t.Result
}
[Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime] | Out-Null
[Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime] | Out-Null
[Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics, ContentType = WindowsRuntime] | Out-Null
$file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($env:RED_OCR_IMAGE)) ([Windows.Storage.StorageFile])
$stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
try {
    $decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
    $bitmap = Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
    $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
    $result = Await ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
} finally { $stream.Dispose() }
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
foreach ($line in $result.Lines) { $line.Text }
"""


@dataclass
class ScreenInfo:
    title: str = ""                 # the active window's title
    app: str = ""                   # its program, e.g. "chrome"
    lines: list[str] = field(default_factory=list)   # text read from the screen
    ocr_ok: bool = True

    def as_prompt(self) -> str:
        text = "\n".join(self.lines)
        if len(text) > MAX_TEXT:
            text = text[:MAX_TEXT] + "\n[...]"
        parts = [f"Active window title: {self.title or '(none)'}",
                 f"Program: {self.app or '(unknown)'}"]
        if self.ocr_ok:
            parts.append("Text read from the screen (OCR, top to bottom, may be messy):\n"
                         + (text or "(no text found)"))
        else:
            parts.append("The screen text couldn't be read this time.")
        return "\n".join(parts)


def foreground_window() -> tuple[str, str]:
    """(title, program name) of the window you're using."""
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return "", ""
    buf = ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(hwnd, buf, 512)
    title = buf.value
    pid = ctypes.c_ulong()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    app = ""
    handle = kernel32.OpenProcess(0x1000, False, pid.value)   # PROCESS_QUERY_LIMITED_INFORMATION
    if handle:
        try:
            size = ctypes.c_ulong(1024)
            path = ctypes.create_unicode_buffer(1024)
            if kernel32.QueryFullProcessImageNameW(handle, 0, path, ctypes.byref(size)):
                app = Path(path.value).stem
        finally:
            kernel32.CloseHandle(handle)
    return title, app


def ocr_command() -> list[str]:
    encoded = base64.b64encode(OCR_SCRIPT.encode("utf-16-le")).decode("ascii")
    return ["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded]


def screen_text(cache_dir: Path, *, grab: Callable[[], object] | None = None,
                runner: Callable = subprocess.run) -> list[str]:
    """The text on the screen, line by line. Raises OSError if it can't be read."""
    if grab is None:
        from PIL import ImageGrab
        grab = ImageGrab.grab
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / "screen-ocr.png"
    try:
        grab().save(path)
        out = runner(ocr_command(), capture_output=True, timeout=OCR_TIMEOUT,
                     env=dict(os.environ, RED_OCR_IMAGE=str(path)),
                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except subprocess.TimeoutExpired as e:
        raise OSError("reading the screen took too long") from e
    finally:
        path.unlink(missing_ok=True)       # the screenshot never stays on disk
    if out.returncode != 0:
        raise OSError(f"Windows OCR failed ({out.returncode})")
    text = out.stdout.decode("utf-8", errors="replace") if isinstance(out.stdout, bytes) else out.stdout
    return [line.strip() for line in text.splitlines() if line.strip()]


def read_screen(cache_dir: Path, *, window: Callable[[], tuple[str, str]] = foreground_window,
                text: Callable[[Path], list[str]] = screen_text) -> ScreenInfo:
    """What's on the screen right now. The window is always known; the text may not be."""
    try:
        title, app = window()
    except OSError:
        title, app = "", ""
    info = ScreenInfo(title=title, app=app)
    try:
        info.lines = text(cache_dir)
    except Exception as e:  # noqa: BLE001 - no Pillow, OCR missing, timeout: the title still helps
        log.warning("Couldn't read the screen text: %s", e)
        info.ocr_ok = False
    log.info("Read the screen: window %r (%s), %d lines of text", title[:80], app, len(info.lines))
    return info
