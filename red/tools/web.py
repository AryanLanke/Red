"""Web tools."""

from __future__ import annotations

import webbrowser
from typing import Callable
from urllib.parse import urlsplit

from .base import Tool, ToolError


class OpenUrl(Tool):
    name = "open_url"
    description = ("Open a website in the default browser. Give a full URL starting with "
                   "https://, for example https://www.youtube.com for 'open YouTube'.")
    args_schema = {
        "type": "object",
        "properties": {"url": {"type": "string", "pattern": "^https?://[^ ]+$", "maxLength": 2000}},
        "required": ["url"],
        "additionalProperties": False,
    }

    def __init__(self, open_browser: Callable[[str], bool] = webbrowser.open):
        self._open = open_browser

    def run(self, url: str) -> str:
        url = url.strip()
        # The schema checks this too; check again so no other scheme ever reaches the shell.
        parts = urlsplit(url)
        if (parts.scheme.lower() not in {"http", "https"} or not parts.hostname
                or any(c.isspace() or ord(c) < 32 for c in url)):
            raise ToolError("I can only open web addresses that start with http or https.")
        if not self._open(url):
            raise ToolError("I couldn't open the browser.")
        host = parts.hostname.removeprefix("www.")
        return f"Opening {host}."
