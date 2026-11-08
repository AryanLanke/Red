"""Quick system actions: lock, volume, media keys, Settings pages, time, date,
battery, screenshots, sleep and emptying the Recycle Bin.

Volume, media and screenshots use the same global keys as a keyboard
(Windows handles them, whichever window is in front). Every side effect is
passed in through the constructor; tests use fakes. Sleep and emptying the
Recycle Bin are destructive, so Red asks first.
"""

from __future__ import annotations

import ctypes
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Callable

from .. import known_folders as _known
from . import music as _music
from .base import Tool, ToolError

_NO_ARGS = {"type": "object", "properties": {}, "additionalProperties": False}

# Virtual-key codes (WinUser.h).
VK_VOLUME_MUTE, VK_VOLUME_DOWN, VK_VOLUME_UP = 0xAD, 0xAE, 0xAF
VK_MEDIA_NEXT, VK_MEDIA_PREV, VK_MEDIA_PLAY_PAUSE = 0xB0, 0xB1, 0xB3
VK_LWIN, VK_SNAPSHOT = 0x5B, 0x2C
VOLUME_STEP = 2          # percent per volume key press on Windows 10 and 11


class Keyboard:
    """Presses keys through keybd_event. Volume and media keys are global."""

    KEYEVENTF_EXTENDEDKEY, KEYEVENTF_KEYUP = 0x1, 0x2

    def _event(self, vk: int, up: bool) -> None:
        flags = self.KEYEVENTF_EXTENDEDKEY | (self.KEYEVENTF_KEYUP if up else 0)
        ctypes.windll.user32.keybd_event(vk, 0, flags, 0)

    def press(self, vk: int, times: int = 1) -> None:
        for _ in range(times):
            self._event(vk, False)
            self._event(vk, True)

    def chord(self, *vks: int) -> None:
        """Hold each key in order, then release them in reverse (Win+PrtScn)."""
        for vk in vks:
            self._event(vk, False)
        for vk in reversed(vks):
            self._event(vk, True)


_keyboard = Keyboard()


def _require_windows() -> None:
    if sys.platform != "win32":
        raise ToolError("That only works on Windows.")


# --------------------------------------------------------------------------
# Lock and sleep
# --------------------------------------------------------------------------

def _lock_workstation() -> None:
    _require_windows()
    if not ctypes.windll.user32.LockWorkStation():
        raise ToolError("Windows didn't lock the PC.")


def _suspend() -> None:
    _require_windows()
    # SetSuspendState(hibernate=False, force=False, disable_wake_events=False)
    if not ctypes.WinDLL("powrprof").SetSuspendState(False, False, False):
        raise ToolError("Windows didn't go to sleep.")


class LockPC(Tool):
    name = "lock_pc"
    description = "Lock the computer (go to the sign-in screen)."
    args_schema = _NO_ARGS

    def __init__(self, lock: Callable[[], None] = _lock_workstation):
        self._lock = lock

    def run(self) -> str:
        self._lock()
        return "Locking your PC."


class SleepPC(Tool):
    name = "sleep_pc"
    description = "Put the computer to sleep now."
    args_schema = _NO_ARGS
    destructive = True

    def __init__(self, suspend: Callable[[], None] = _suspend):
        self._suspend = suspend

    def describe(self) -> str:
        return "Put the PC to sleep now"

    def run(self) -> str:
        self._suspend()
        return "Going to sleep."


# --------------------------------------------------------------------------
# Volume and media
# --------------------------------------------------------------------------

class Volume(Tool):
    name = "volume"
    description = ("Change the computer's sound volume: up, down, mute, unmute, or set "
                   "it to a percent.")
    args_schema = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["up", "down", "mute", "unmute", "set"]},
            "percent": {"type": "integer", "minimum": 0, "maximum": 100,
                        "description": "For set: the level. For up or down: how much "
                                       "(default 10)."},
        },
        "required": ["action"],
        "additionalProperties": False,
    }

    def __init__(self, keyboard: Keyboard = _keyboard):
        self._keys = keyboard

    def run(self, action: str, percent: int | None = None) -> str:
        if action in ("up", "down"):
            amount = 10 if percent is None else max(VOLUME_STEP, min(100, percent))
            self._keys.press(VK_VOLUME_UP if action == "up" else VK_VOLUME_DOWN,
                             max(1, round(amount / VOLUME_STEP)))
            return f"Volume {action} {amount} percent."
        if action == "unmute":
            # Any volume key unmutes; up then down leaves the level where it was.
            self._keys.press(VK_VOLUME_UP)
            self._keys.press(VK_VOLUME_DOWN)
            return "Sound is on."
        if action == "mute":
            # Unmute first, so the mute key (a toggle) always ends muted.
            self._keys.press(VK_VOLUME_UP)
            self._keys.press(VK_VOLUME_DOWN)
            self._keys.press(VK_VOLUME_MUTE)
            return "Muted."
        if action == "set":
            if percent is None:
                raise ToolError("What level should I set the volume to?")
            self._keys.press(VK_VOLUME_DOWN, 100 // VOLUME_STEP)     # to 0
            self._keys.press(VK_VOLUME_UP, round(percent / VOLUME_STEP))
            return f"Volume set to {percent} percent."
        raise ToolError("I can turn the volume up, down, mute, unmute, or set it.")


# Red's own player first; otherwise the media keys, which control whatever app
# is playing (Spotify, a YouTube tab, Windows Media Player).

class PauseMedia(_music.PauseMusic):
    description = ("Pause the music or video that is playing, in Red or in another app "
                   "like Spotify or YouTube.")

    def __init__(self, player=None, keyboard: Keyboard = _keyboard):
        super().__init__(player)
        self._keys = keyboard

    def run(self) -> str:
        if self.player.current is not None:
            return super().run()
        self._keys.press(VK_MEDIA_PLAY_PAUSE)
        return "Paused."


class ResumeMedia(_music.ResumeMusic):
    description = ("Resume (unpause) music or video that was paused, in Red or in another "
                   "app like Spotify or YouTube.")

    def __init__(self, player=None, keyboard: Keyboard = _keyboard):
        super().__init__(player)
        self._keys = keyboard

    def run(self) -> str:
        if self.player.current is not None:
            return super().run()
        self._keys.press(VK_MEDIA_PLAY_PAUSE)
        return "Resuming."


class NextMedia(_music.NextSong):
    description = ("Skip to the next song or track, in Red's music or in another app like "
                   "Spotify.")

    def __init__(self, player=None, keyboard: Keyboard = _keyboard):
        super().__init__(player)
        self._keys = keyboard

    def run(self) -> str:
        if self.player.current is not None:
            return super().run()
        self._keys.press(VK_MEDIA_NEXT)
        return "Next track."


class PreviousTrack(Tool):
    name = "previous_track"
    description = "Go back to the previous song or track in the app that is playing media."
    args_schema = _NO_ARGS

    def __init__(self, keyboard: Keyboard = _keyboard):
        self._keys = keyboard

    def run(self) -> str:
        self._keys.press(VK_MEDIA_PREV)
        return "Previous track."


# --------------------------------------------------------------------------
# Settings pages
# --------------------------------------------------------------------------

SETTINGS_PAGES = {
    "home": ("Settings", "ms-settings:"),
    "display": ("display settings", "ms-settings:display"),
    "sound": ("sound settings", "ms-settings:sound"),
    "bluetooth": ("Bluetooth settings", "ms-settings:bluetooth"),
    "wifi": ("Wi-Fi settings", "ms-settings:network-wifi"),
    "network": ("network settings", "ms-settings:network-status"),
    "vpn": ("VPN settings", "ms-settings:network-vpn"),
    "hotspot": ("mobile hotspot settings", "ms-settings:network-mobilehotspot"),
    "battery": ("battery settings", "ms-settings:batterysaver"),
    "power": ("power and sleep settings", "ms-settings:powersleep"),
    "notifications": ("notification settings", "ms-settings:notifications"),
    "apps": ("installed apps", "ms-settings:appsfeatures"),
    "default_apps": ("default apps", "ms-settings:defaultapps"),
    "windows_update": ("Windows Update", "ms-settings:windowsupdate"),
    "privacy": ("privacy settings", "ms-settings:privacy"),
    "background": ("background settings", "ms-settings:personalization-background"),
    "themes": ("theme settings", "ms-settings:themes"),
    "night_light": ("night light settings", "ms-settings:nightlight"),
    "mouse": ("mouse settings", "ms-settings:mousetouchpad"),
    "keyboard": ("keyboard settings", "ms-settings:typing"),
    "date_time": ("date and time settings", "ms-settings:dateandtime"),
    "language": ("language settings", "ms-settings:regionlanguage"),
    "storage": ("storage settings", "ms-settings:storagesense"),
    "about": ("About this PC", "ms-settings:about"),
    "accounts": ("account settings", "ms-settings:yourinfo"),
    "printers": ("printer settings", "ms-settings:printers"),
}


def _default_startfile(target: str) -> None:
    os.startfile(target)  # type: ignore[attr-defined]  # Windows only


class OpenSettings(Tool):
    name = "open_settings"
    description = "Open a page of Windows Settings, such as display, sound, Bluetooth or Wi-Fi."
    args_schema = {
        "type": "object",
        "properties": {"page": {"type": "string", "enum": list(SETTINGS_PAGES)}},
        "required": ["page"],
        "additionalProperties": False,
    }

    def __init__(self, startfile: Callable[[str], None] = _default_startfile):
        self._startfile = startfile

    def run(self, page: str) -> str:
        if page not in SETTINGS_PAGES:     # the schema checks this too
            raise ToolError("I don't know that Settings page.")
        title, uri = SETTINGS_PAGES[page]
        try:
            self._startfile(uri)
        except OSError as e:
            raise ToolError(f"I couldn't open {title}: {e.strerror or e}") from e
        return f"Opening {title}."


# --------------------------------------------------------------------------
# Time, date, battery
# --------------------------------------------------------------------------

def battery_status() -> tuple[int | None, bool | None]:
    """(percent, plugged in), or (None, None) when there's no battery."""
    _require_windows()

    class SYSTEM_POWER_STATUS(ctypes.Structure):
        _fields_ = [("ACLineStatus", ctypes.c_ubyte), ("BatteryFlag", ctypes.c_ubyte),
                    ("BatteryLifePercent", ctypes.c_ubyte), ("SystemStatusFlag", ctypes.c_ubyte),
                    ("BatteryLifeTime", ctypes.c_ulong), ("BatteryFullLifeTime", ctypes.c_ulong)]

    s = SYSTEM_POWER_STATUS()
    if not ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(s)):
        raise ToolError("Windows didn't report the battery.")
    if s.BatteryFlag == 128 or s.BatteryLifePercent == 255:     # no battery / unknown
        return None, None
    plugged = {0: False, 1: True}.get(s.ACLineStatus)
    return int(s.BatteryLifePercent), plugged


def _clock(t: datetime) -> str:
    return t.strftime("%I:%M %p").lstrip("0")


class TellStatus(Tool):
    name = "tell_status"
    description = "Say the current time, today's date, or the battery level."
    args_schema = {
        "type": "object",
        "properties": {"what": {"type": "string", "enum": ["time", "date", "battery"]}},
        "required": ["what"],
        "additionalProperties": False,
    }

    def __init__(self, now: Callable[[], datetime] = datetime.now,
                 battery: Callable[[], tuple[int | None, bool | None]] = battery_status):
        self._now = now
        self._battery = battery

    def run(self, what: str) -> str:
        if what == "time":
            return f"It's {_clock(self._now())}."
        if what == "date":
            d = self._now()
            return f"Today is {d.strftime('%A, %B')} {d.day}, {d.year}."
        if what == "battery":
            percent, plugged = self._battery()
            if percent is None:
                return "This PC doesn't have a battery."
            state = {True: ", and it's plugged in", False: ", on battery power"}.get(plugged, "")
            return f"The battery is at {percent} percent{state}."
        raise ToolError("I can tell you the time, the date, or the battery level.")


# --------------------------------------------------------------------------
# Screenshot
# --------------------------------------------------------------------------

SCREENSHOTS_ID = "{B7BEDE81-DF94-4682-A7D8-57A52620B86F}"   # FOLDERID_Screenshots
_IMAGE_TYPES = (".png", ".jpg", ".jpeg")


def screenshots_folder() -> Path | None:
    path = _known._shell_folder_path(SCREENSHOTS_ID)
    if path is not None:
        return path
    pictures = _known.known_folder("pictures")
    return pictures / "Screenshots" if pictures else None


def _newest(folder: Path) -> tuple[float, Path | None]:
    try:
        images = [p for p in folder.iterdir() if p.suffix.lower() in _IMAGE_TYPES]
    except OSError:
        return 0.0, None
    if not images:
        return 0.0, None
    p = max(images, key=lambda q: q.stat().st_mtime)
    return p.stat().st_mtime, p


class TakeScreenshot(Tool):
    name = "take_screenshot"
    description = "Take a screenshot of the whole screen and save it in Pictures."
    args_schema = _NO_ARGS

    def __init__(self, keyboard: Keyboard = _keyboard,
                 folder: Callable[[], Path | None] = screenshots_folder,
                 wait_seconds: float = 3.0, sleep: Callable[[float], None] = time.sleep):
        self._keys = keyboard
        self._folder = folder
        self._wait = wait_seconds
        self._sleep = sleep

    def run(self) -> str:
        folder = self._folder()
        if folder is None:
            raise ToolError("I couldn't find your Pictures folder.")
        before, _ = _newest(folder)
        # Windows+Print Screen: Windows saves the full screen to Pictures\Screenshots.
        self._keys.chord(VK_LWIN, VK_SNAPSHOT)
        waited = 0.0
        while waited <= self._wait:
            stamp, newest = _newest(folder)
            if newest is not None and stamp > before:
                return f"Saved a screenshot to Pictures, as {newest.name}."
            self._sleep(0.2)
            waited += 0.2
        raise ToolError(f"I pressed Windows and Print Screen, but no screenshot appeared "
                        f"in {folder}.")


# --------------------------------------------------------------------------
# Recycle Bin
# --------------------------------------------------------------------------

def recycle_bin_size() -> tuple[int, int]:
    """(items, bytes) across all drives. Read-only."""
    _require_windows()

    class SHQUERYRBINFO(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_ulong), ("i64Size", ctypes.c_longlong),
                    ("i64NumItems", ctypes.c_longlong)]

    info = SHQUERYRBINFO(ctypes.sizeof(SHQUERYRBINFO), 0, 0)
    hr = ctypes.windll.shell32.SHQueryRecycleBinW(None, ctypes.byref(info))
    if hr != 0:
        raise ToolError("Windows didn't report what's in the Recycle Bin.")
    return int(info.i64NumItems), int(info.i64Size)


def empty_recycle_bin() -> None:
    _require_windows()
    SHERB_NOCONFIRMATION, SHERB_NOPROGRESSUI, SHERB_NOSOUND = 0x1, 0x2, 0x4
    hr = ctypes.windll.shell32.SHEmptyRecycleBinW(
        None, None, SHERB_NOCONFIRMATION | SHERB_NOPROGRESSUI | SHERB_NOSOUND)
    if hr != 0:
        raise ToolError(f"Windows couldn't empty the Recycle Bin (error {hr & 0xFFFFFFFF:#x}).")


def _size(n: int) -> str:
    for unit in ("bytes", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "bytes" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n} bytes"


class EmptyRecycleBin(Tool):
    name = "empty_recycle_bin"
    description = "Permanently delete everything in the Recycle Bin."
    args_schema = _NO_ARGS
    destructive = True

    def __init__(self, query: Callable[[], tuple[int, int]] = recycle_bin_size,
                 empty: Callable[[], None] = empty_recycle_bin):
        self._query = query
        self._empty = empty

    def describe(self) -> str:
        try:
            items, size = self._query()
        except ToolError:
            return "Permanently delete everything in the Recycle Bin"
        if items == 0:
            return "Empty the Recycle Bin (it's already empty)"
        return (f"Permanently delete {items} item{'s' if items != 1 else ''} "
                f"({_size(size)}) from the Recycle Bin")

    def run(self) -> str:
        items, _ = self._query()
        if items == 0:
            return "The Recycle Bin is already empty."
        self._empty()
        return f"Emptied the Recycle Bin: {items} item{'s' if items != 1 else ''} deleted."
