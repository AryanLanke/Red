"""describe_screen: "what's on my screen?", "what am I doing?", "read this error".

Red looks at the active window and the text on the screen (see red.screen),
and the local model says what's going on in a sentence or two. It only
happens when you ask, and nothing leaves the PC.
"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Callable

from ..config import red_home
from ..screen import ScreenInfo, read_screen
from .assistant import _UsesLLM, ask_model
from .base import ToolError

SCREEN_SYSTEM = """You are Red, a friendly voice assistant on the user's Windows PC. The user asked about their screen. You get the active window's title, its program, and the text read from the screen by OCR (messy, top to bottom, menus and tabs mixed in).
Say what's on the screen or what they're doing, in 1 or 2 short, natural spoken sentences, like a friend glancing over: name the app or website and the page, for example "You're on YouTube's home page, just browsing" or "You've got VS Code open on a Python file called overlay.py". If they asked something specific (an error, a word, a number), answer that from the text. Don't read out long text, don't guess beyond what's there, no lists, markdown or emoji.
Reply with JSON only: {"answer": "<what you say>"}"""

# Models that can see also get a small screenshot (red.screen.screenshot_jpeg).
SEES_SCREEN = """
You also get a screenshot of the screen. Use it with the text: it shows pictures, videos and layout the OCR can't. Describe only what you can actually see."""


class DescribeScreen(_UsesLLM):
    name = "describe_screen"
    description = ("Look at the user's screen and say what's on it or what they're doing, or answer "
                   "a question about it, for example 'what's on my screen', 'what am I doing right "
                   "now', 'read this error', 'what does my screen say'.")
    args_schema = {
        "type": "object",
        "properties": {"question": {"type": "string", "maxLength": 300,
                                    "description": "What the user wants to know about the screen, in their words."}},
        "additionalProperties": False,
    }

    def __init__(self, llm=None, read: Callable[[Path], ScreenInfo] | None = None,
                 cache_dir: Path | None = None):
        super().__init__(llm)
        self._read = read or read_screen
        self._cache_dir = cache_dir

    def run(self, question: str = "") -> str:
        cache = self._cache_dir or red_home() / "cache"
        sees = bool(getattr(self._llm, "vision", False))
        info = self._read(cache, with_image=True) if sees else self._read(cache)
        if not info.title and not info.lines and not info.image:
            raise ToolError("I couldn't see anything on the screen right now.")
        asked = " ".join((question or "").split()) or "What's on my screen?"
        prompt = f"The user asked: {asked}\n\n{info.as_prompt()}"
        if sees and info.image:
            return ask_model(self._llm, SCREEN_SYSTEM + SEES_SCREEN, prompt,
                             images=[base64.b64encode(info.image).decode("ascii")])
        return ask_model(self._llm, SCREEN_SYSTEM, prompt)
