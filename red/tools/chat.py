"""'Open chat': Red's chat window (red/chat_window.py) by voice."""

from __future__ import annotations

from typing import Callable

from .base import Tool, ToolError


class OpenChat(Tool):
    name = "open_chat"
    description = ("Open Red's own chat window, where the user types to Red: 'open chat', 'open the "
                   "chat window', 'show me the chat', 'let me type to you'. Only when they ask for "
                   "the window or to type; 'let's chat' or 'let's talk' is just conversation (none), "
                   "and other apps go to open_app.")
    args_schema = {"type": "object", "properties": {}, "required": [], "additionalProperties": False}

    def __init__(self):
        self._show: Callable[[], None] | None = None

    def bind_chat_window(self, show: Callable[[], None]) -> None:
        """Called by red.chat_window when the voice loop has a window."""
        self._show = show

    def run(self) -> str:
        if self._show is None:
            raise ToolError("The chat window needs Red's overlay running. "
                            "Set the overlay to glow or card in the Red app.")
        self._show()
        return "Here you go."
