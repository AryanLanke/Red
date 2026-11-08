"""The Tool interface every capability implements."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import ClassVar, Iterable


class ToolError(Exception):
    """A failure whose message is short and fit to say to the user."""


class Tool(ABC):
    name: ClassVar[str]          # "shutdown"
    description: ClassVar[str]   # shown to the LLM so it knows when to use it
    args_schema: ClassVar[dict]  # JSON schema for arguments
    destructive: ClassVar[bool] = False  # if True, Red asks for confirmation first

    @abstractmethod
    def run(self, **kwargs) -> str:
        """Do the action and return a short reply for the user."""

    def describe(self, **kwargs) -> str:
        """The action in plain words, used for the confirmation question.

        Destructive tools should override this, for example
        "Shut down in 2 hours (at 11:40 PM)". It must not have side effects.
        """
        words = self.name.replace("_", " ")
        if not kwargs:
            return words.capitalize()
        details = ", ".join(f"{k} {v}" for k, v in kwargs.items())
        return f"{words.capitalize()} ({details})"


class ToolRegistry:
    def __init__(self, tools: Iterable[Tool] = ()):
        self._tools: dict[str, Tool] = {}
        for tool in tools:
            self.add(tool)

    def add(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"Duplicate tool name: {tool.name}")
        if tool.name == "none":
            raise ValueError("'none' is reserved for 'no tool fits'")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        return self._tools[name]

    def __iter__(self):
        return iter(self._tools.values())

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name: str) -> bool:
        return name in self._tools
