"""Built-in tools."""

from .assistant import Answer
from .base import Tool, ToolRegistry
from .files import FindFile, OpenFoundFile
from .git_sync import CheckRepos
from .mail import ComposeMail
from .music import PlayMusic, StopMusic
from .quick import (EmptyRecycleBin, LockPC, NextMedia, OpenSettings, PauseMedia, PreviousTrack,
                    ResumeMedia, SleepPC, TakeScreenshot, TellStatus, Volume)
from .reminders import CancelReminder, ListReminders, SetReminder, SetTimer
from .system import CancelShutdown, OpenApp, OpenFolder, Restart, Shutdown
from .web import OpenUrl, WebSearch


def default_registry() -> ToolRegistry:
    # The music tools share one player, created on the first play. Pause, resume
    # and next fall back to the media keys when Red's own player is idle.
    return ToolRegistry([
        OpenFolder(), OpenApp(), OpenUrl(), WebSearch(), Answer(),
        FindFile(), OpenFoundFile(), ComposeMail(),
        Shutdown(), Restart(), CancelShutdown(), SleepPC(), LockPC(),
        PlayMusic(), StopMusic(), PauseMedia(), ResumeMedia(), NextMedia(), PreviousTrack(),
        Volume(), OpenSettings(), TellStatus(), TakeScreenshot(), EmptyRecycleBin(),
        SetTimer(), SetReminder(), ListReminders(), CancelReminder(),
        CheckRepos(),
    ])


__all__ = ["Tool", "ToolRegistry", "default_registry"]
