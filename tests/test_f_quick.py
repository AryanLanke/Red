"""Quick system actions with fakes. No key is pressed, nothing locks or sleeps."""

import time
from datetime import datetime
from pathlib import Path

import pytest

from red.router import Router
from red.tools import default_registry
from red.tools import quick as q
from red.tools.base import ToolError


class FakeKeys:
    def __init__(self):
        self.log = []

    def press(self, vk, times=1):
        self.log.append(("press", vk, times))

    def chord(self, *vks):
        self.log.append(("chord", *vks))

    def presses(self, vk):
        return sum(t for kind, v, *rest in self.log if kind == "press" and v == vk
                   for t in rest)


def test_lock():
    calls = []
    assert q.LockPC(lock=lambda: calls.append(1)).run() == "Locking your PC."
    assert calls == [1]
    assert q.LockPC.destructive is False


def test_sleep_is_destructive_and_describes_itself():
    calls = []
    tool = q.SleepPC(suspend=lambda: calls.append(1))
    assert q.SleepPC.destructive is True
    assert tool.describe() == "Put the PC to sleep now"
    assert calls == []                 # describe() has no side effects
    assert tool.run() == "Going to sleep."
    assert calls == [1]


@pytest.mark.parametrize("action, percent, reply, presses", [
    ("up", None, "Volume up 10 percent.", {q.VK_VOLUME_UP: 5}),
    ("down", 20, "Volume down 20 percent.", {q.VK_VOLUME_DOWN: 10}),
    ("up", 1, "Volume up 2 percent.", {q.VK_VOLUME_UP: 1}),
    ("set", 30, "Volume set to 30 percent.", {q.VK_VOLUME_DOWN: 50, q.VK_VOLUME_UP: 15}),
    ("set", 0, "Volume set to 0 percent.", {q.VK_VOLUME_DOWN: 50, q.VK_VOLUME_UP: 0}),
    ("unmute", None, "Sound is on.", {q.VK_VOLUME_UP: 1, q.VK_VOLUME_DOWN: 1}),
    ("mute", None, "Muted.", {q.VK_VOLUME_UP: 1, q.VK_VOLUME_DOWN: 1, q.VK_VOLUME_MUTE: 1}),
])
def test_volume(action, percent, reply, presses):
    keys = FakeKeys()
    assert q.Volume(keyboard=keys).run(action=action, percent=percent) == reply
    for vk, n in presses.items():
        assert keys.presses(vk) == n, (hex(vk), keys.log)


def test_mute_ends_with_the_mute_key():
    keys = FakeKeys()
    q.Volume(keyboard=keys).run(action="mute")
    assert keys.log[-1][1] == q.VK_VOLUME_MUTE


def test_set_volume_needs_a_level():
    with pytest.raises(ToolError):
        q.Volume(keyboard=FakeKeys()).run(action="set")


class FakePlayer:
    def __init__(self, current=None):
        self.current, self.paused, self.calls = current, False, []

    def pause(self):
        self.calls.append("pause")
        self.paused = True
        return True

    def resume(self):
        self.calls.append("resume")
        self.paused = False
        return True

    def next(self):
        self.calls.append("next")
        return Path("02 - Next One.mp3")


@pytest.mark.parametrize("cls, vk, reply", [
    (q.PauseMedia, q.VK_MEDIA_PLAY_PAUSE, "Paused."),
    (q.ResumeMedia, q.VK_MEDIA_PLAY_PAUSE, "Resuming."),
    (q.NextMedia, q.VK_MEDIA_NEXT, "Next track."),
])
def test_media_keys_when_red_is_not_playing(cls, vk, reply):
    keys, player = FakeKeys(), FakePlayer()
    assert cls(player, keyboard=keys).run() == reply
    assert keys.log == [("press", vk, 1)] and player.calls == []


def test_reds_own_music_comes_first():
    keys = FakeKeys()
    player = FakePlayer(current=Path("01 - Song.mp3"))
    assert q.PauseMedia(player, keyboard=keys).run() == "Paused."
    assert q.ResumeMedia(player, keyboard=keys).run() == "Resuming Song."
    assert q.NextMedia(player, keyboard=keys).run() == "Playing Next One."
    assert player.calls == ["pause", "resume", "next"] and keys.log == []


def test_previous_track():
    keys = FakeKeys()
    assert q.PreviousTrack(keyboard=keys).run() == "Previous track."
    assert keys.log == [("press", q.VK_MEDIA_PREV, 1)]


def test_media_tools_keep_the_music_tool_names():
    assert (q.PauseMedia.name, q.ResumeMedia.name, q.NextMedia.name) == \
        ("pause_music", "resume_music", "next_song")


def test_settings_pages_are_a_fixed_list():
    opened = []
    tool = q.OpenSettings(startfile=opened.append)
    assert tool.run(page="bluetooth") == "Opening Bluetooth settings."
    assert opened == ["ms-settings:bluetooth"]
    assert all(uri.startswith("ms-settings:") for _, uri in q.SETTINGS_PAGES.values())
    assert q.OpenSettings.args_schema["properties"]["page"]["enum"] == list(q.SETTINGS_PAGES)
    with pytest.raises(ToolError):
        tool.run(page="ms-settings:../../evil")


def test_settings_open_error():
    def broken(uri):
        raise OSError("no handler")
    with pytest.raises(ToolError, match="couldn't open display settings"):
        q.OpenSettings(startfile=broken).run(page="display")


NOW = datetime(2026, 11, 8, 9, 5)


@pytest.mark.parametrize("what, battery, reply", [
    ("time", None, "It's 9:05 AM."),
    ("date", None, "Today is Sunday, November 8, 2026."),
    ("battery", (76, True), "The battery is at 76 percent, and it's plugged in."),
    ("battery", (12, False), "The battery is at 12 percent, on battery power."),
    ("battery", (50, None), "The battery is at 50 percent."),
    ("battery", (None, None), "This PC doesn't have a battery."),
])
def test_tell_status(what, battery, reply):
    tool = q.TellStatus(now=lambda: NOW, battery=lambda: battery)
    assert tool.run(what=what) == reply


def test_real_battery_read_is_safe():
    percent, plugged = q.battery_status()
    assert percent is None or 0 <= percent <= 100


def test_screenshot_waits_for_the_new_file(tmp_path):
    old = tmp_path / "Screenshot 1.png"
    old.write_bytes(b"x")
    keys = FakeKeys()

    class SaveOnChord(FakeKeys):
        def chord(self, *vks):
            super().chord(*vks)
            new = tmp_path / "Screenshot 2.png"
            new.write_bytes(b"y")
            t = time.time() + 5
            import os
            os.utime(new, (t, t))

    keys = SaveOnChord()
    tool = q.TakeScreenshot(keyboard=keys, folder=lambda: tmp_path, sleep=lambda s: None)
    assert tool.run() == "Saved a screenshot to Pictures, as Screenshot 2.png."
    assert keys.log == [("chord", q.VK_LWIN, q.VK_SNAPSHOT)]


def test_screenshot_reports_when_nothing_appears(tmp_path):
    tool = q.TakeScreenshot(keyboard=FakeKeys(), folder=lambda: tmp_path, wait_seconds=0.4,
                            sleep=lambda s: None)
    with pytest.raises(ToolError, match="no screenshot appeared"):
        tool.run()


def test_screenshot_folder_is_found():
    folder = q.screenshots_folder()
    assert folder is None or folder.name.lower() == "screenshots" or folder.is_absolute()


def test_empty_recycle_bin():
    emptied = []
    tool = q.EmptyRecycleBin(query=lambda: (3, 5 * 1024 * 1024),
                             empty=lambda: emptied.append(1))
    assert q.EmptyRecycleBin.destructive is True
    assert tool.describe() == "Permanently delete 3 items (5.0 MB) from the Recycle Bin"
    assert emptied == []
    assert tool.run() == "Emptied the Recycle Bin: 3 items deleted."
    assert emptied == [1]


def test_empty_recycle_bin_when_already_empty():
    emptied = []
    tool = q.EmptyRecycleBin(query=lambda: (0, 0), empty=lambda: emptied.append(1))
    assert tool.describe() == "Empty the Recycle Bin (it's already empty)"
    assert tool.run() == "The Recycle Bin is already empty."
    assert emptied == []


def test_recycle_bin_query_is_read_only_and_works():
    items, size = q.recycle_bin_size()
    assert items >= 0 and size >= 0


def test_registry_has_every_quick_tool_and_routes_parse():
    reg = default_registry()
    for name in ("lock_pc", "sleep_pc", "volume", "previous_track", "open_settings",
                 "tell_status", "take_screenshot", "empty_recycle_bin"):
        assert name in reg
    assert isinstance(reg.get("pause_music"), q.PauseMedia)
    router = Router(reg)
    assert router.parse('{"tool": "sleep_pc", "args": {}}').destructive
    assert router.parse('{"tool": "empty_recycle_bin", "args": {}}').destructive
    assert not router.parse('{"tool": "volume", "args": {"action": "up"}}').destructive
