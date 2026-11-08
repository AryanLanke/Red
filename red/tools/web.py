"""Web tools. Action built on Day 2."""

from __future__ import annotations

from .base import Tool


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

    def run(self, url: str) -> str:
        raise NotImplementedError("open_url is built on Day 2")
