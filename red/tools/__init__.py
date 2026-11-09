"""Built-in tools."""

from .assistant import Answer
from .base import Tool, ToolRegistry
from .files import FindFile, OpenFoundFile
from .git_sync import CheckRepos
from .mail import ComposeMail
from .online import LookUp, News, Weather
from .quick import (EmptyRecycleBin, LockPC, NextMedia, OpenSettings, PauseMedia, PreviousTrack,
                    ResumeMedia, SleepPC, StopMedia, TakeScreenshot, TellStatus, Volume)
from .reminders import CancelReminder, ListReminders, SetReminder, SetTimer
from .screen import DescribeScreen
from .system import CancelShutdown, OpenApp, OpenFolder, Restart, Shutdown
from .web import OpenUrl, WebSearch
from .youtube import PlayOnline


def default_registry() -> ToolRegistry:
    # No local music: every "play ..." goes to play_online (YouTube), and pause,
    # resume, next, previous and stop are the media keys, which control it.
    return ToolRegistry([
        OpenFolder(), OpenApp(), OpenUrl(), WebSearch(), Answer(), DescribeScreen(),
        LookUp(), Weather(), News(),
        FindFile(), OpenFoundFile(), ComposeMail(),
        Shutdown(), Restart(), CancelShutdown(), SleepPC(), LockPC(),
        PlayOnline(), StopMedia(), PauseMedia(), ResumeMedia(), NextMedia(), PreviousTrack(),
        Volume(), OpenSettings(), TellStatus(), TakeScreenshot(), EmptyRecycleBin(),
        SetTimer(), SetReminder(), ListReminders(), CancelReminder(),
        CheckRepos(),
    ])


__all__ = ["Tool", "ToolRegistry", "default_registry"]
