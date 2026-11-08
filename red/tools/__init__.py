"""Built-in tools."""

from .base import Tool, ToolRegistry
from .files import FindFile, OpenFoundFile
from .git_sync import CheckRepos
from .music import NextSong, PauseMusic, PlayMusic, ResumeMusic, StopMusic
from .system import CancelShutdown, OpenApp, OpenFolder, Restart, Shutdown
from .web import OpenUrl, WebSearch


def default_registry() -> ToolRegistry:
    # The music tools share one player, created on the first play.
    return ToolRegistry([OpenFolder(), OpenApp(), OpenUrl(), WebSearch(),
                         Shutdown(), Restart(), CancelShutdown(),
                         PlayMusic(), StopMusic(), PauseMusic(), ResumeMusic(), NextSong(),
                         CheckRepos(), FindFile(), OpenFoundFile()])


__all__ = ["Tool", "ToolRegistry", "default_registry"]
