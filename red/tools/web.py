"""Web tools."""

from __future__ import annotations

import os
import webbrowser
from typing import Callable
from urllib.parse import quote_plus, urlsplit

from .base import Tool, ToolError

# Fixed URL templates. Only the encoded query is ever inserted.
WEB_ENGINES = {
    "google": "https://www.google.com/search?q={q}",
    "bing": "https://www.bing.com/search?q={q}",
    "duckduckgo": "https://duckduckgo.com/?q={q}",
}
SITES = {
    "youtube": ("YouTube", "https://www.youtube.com/results?search_query={q}"),
    "images": ("images", "https://www.google.com/search?tbm=isch&q={q}"),
    "maps": ("maps", "https://www.google.com/maps/search/?api=1&query={q}"),
    "news": ("the news", "https://news.google.com/search?q={q}"),
    "wikipedia": ("Wikipedia", "https://en.wikipedia.org/w/index.php?search={q}"),
}
MAX_QUERY = 300


def web_engine() -> str:
    """RED_SEARCH_ENGINE (google, bing or duckduckgo), default google."""
    name = os.environ.get("RED_SEARCH_ENGINE", "").strip().lower()
    return name if name in WEB_ENGINES else "google"


def search_url(query: str, site: str = "web", engine: str = "google") -> str:
    q = quote_plus(" ".join(query.split()), safe="")
    if site in SITES:
        return SITES[site][1].format(q=q)
    return WEB_ENGINES.get(engine, WEB_ENGINES["google"]).format(q=q)


class WebSearch(Tool):
    name = "web_search"
    description = ("Search the internet for something and show the results in the browser, "
                   "including pictures, videos, places and news. Use site for YouTube videos, "
                   "images, maps, news or Wikipedia.")
    args_schema = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "minLength": 1, "maxLength": MAX_QUERY,
                      "description": "What to search for, in the user's words."},
            "site": {"type": "string", "enum": ["web", *SITES],
                     "description": "Where to search. Default web."},
        },
        "required": ["query"],
        "additionalProperties": False,
    }

    def __init__(self, open_browser: Callable[[str], bool] = webbrowser.open,
                 engine: Callable[[], str] = web_engine):
        self._open = open_browser
        self._engine = engine

    def run(self, query: str, site: str = "web") -> str:
        query = " ".join(query.split())
        if not query:
            raise ToolError("What should I search for?")
        if site not in SITES:
            site = "web"
        if not self._open(search_url(query, site, self._engine())):
            raise ToolError("I couldn't open the browser.")
        where = "the web" if site == "web" else SITES[site][0]
        return f"Searching {where} for {query}."


class OpenUrl(Tool):
    name = "open_url"
    description = ("Open a website the user names in the default browser. Give a full URL "
                   "starting with https://, for example https://www.youtube.com for 'open "
                   "YouTube'. Never build a search URL; use web_search to look things up.")
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
