"""Built-in tools."""

from .. import google_auth as _google

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
from .watch import CancelWatch, NotifyWhenDone, Watchers
from .web import OpenUrl, WebSearch
from .youtube import PlayOnline


def default_registry(google: bool | None = None) -> ToolRegistry:
    """Every tool. google: the Gmail and Calendar tools (None: if Red is signed in)."""
    # No local music: every "play ..." goes to play_online (YouTube), and pause,
    # resume, next, previous and stop are the media keys, which control it.
    watchers = Watchers()              # notify_when_done and cancel_watch share the watches
    registry = ToolRegistry([
        OpenFolder(), OpenApp(), OpenUrl(), WebSearch(), Answer(), DescribeScreen(),
        LookUp(), Weather(), News(),
        FindFile(), OpenFoundFile(), ComposeMail(),
        Shutdown(), Restart(), CancelShutdown(), SleepPC(), LockPC(),
        PlayOnline(), StopMedia(), PauseMedia(), ResumeMedia(), NextMedia(), PreviousTrack(),
        Volume(), OpenSettings(), TellStatus(), TakeScreenshot(), EmptyRecycleBin(),
        SetTimer(), SetReminder(), ListReminders(), CancelReminder(),
        NotifyWhenDone(watchers), CancelWatch(watchers),
        CheckRepos(),
    ])
    if google if google is not None else _google.signed_in():
        # After python -m red google-login: one API, shared by mail, calendar and contacts.
        from .calendar import calendar_tools
        from .gmail import mail_tools
        api = _google.GoogleApi()
        for tool in mail_tools(api) + calendar_tools(api):
            registry.add(tool)
    return registry


__all__ = ["Tool", "ToolRegistry", "default_registry"]
