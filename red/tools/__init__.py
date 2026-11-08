"""Built-in tools."""

from .base import Tool, ToolRegistry
from .system import CancelShutdown, OpenApp, OpenFolder, Restart, Shutdown
from .web import OpenUrl


def default_registry() -> ToolRegistry:
    return ToolRegistry([OpenFolder(), OpenApp(), OpenUrl(),
                         Shutdown(), Restart(), CancelShutdown()])


__all__ = ["Tool", "ToolRegistry", "default_registry"]
