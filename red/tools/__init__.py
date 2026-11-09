"""Built-in tools."""

from .assistant import Answer
from .base import Tool, ToolRegistry
from .files import FindFile, OpenFoundFile
from .git_sync import CheckRepos
from .mail import ComposeMail
from .music import PlayMusic, StopMusic
from .online import LookUp, News, Weather
from .quick import (EmptyRecycleBin, LockPC, NextMedia, OpenSettings, PauseMedia, PreviousTrack,
                    ResumeMedia, SleepPC, TakeScreenshot, TellStatus, Volume)
from .reminders import CancelReminder, ListReminders, SetReminder, SetTimer
from .screen import DescribeScreen
from .system import CancelShutdown, OpenApp, OpenFolder, Restart, Shutdown
from .web import OpenUrl, WebSearch
from .youtube import PlayOnline


def default_registry() -> ToolRegistry:
    # The music tools share one player, created on the first play. Pause, resume
    # and next fall back to the media keys when Red's own player is idle.
    # play_music hands over to play_online when the song isn't on this PC.
    online = PlayOnline()
    return ToolRegistry([
        OpenFolder(), OpenApp(), OpenUrl(), WebSearch(), Answer(), DescribeScreen(),
        LookUp(), Weather(), News(),
        FindFile(), OpenFoundFile(), ComposeMail(),
        Shutdown(), Restart(), CancelShutdown(), SleepPC(), LockPC(),
        PlayMusic(online=online), online, StopMusic(), PauseMedia(), ResumeMedia(), NextMedia(), PreviousTrack(),
        Volume(), OpenSettings(), TellStatus(), TakeScreenshot(), EmptyRecycleBin(),
        SetTimer(), SetReminder(), ListReminders(), CancelReminder(),
        CheckRepos(),
    ])


__all__ = ["Tool", "ToolRegistry", "default_registry"]
