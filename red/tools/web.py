"""Web tools."""

from __future__ import annotations

import os
from typing import Callable
from urllib.parse import quote_plus, urlsplit

from .. import browser as _browser
from .. import windows as _windows
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

# "open YouTube from Chrome", "search this in Edge". Unset means RED_BROWSER.
BROWSER_ARG = {"type": "string", "enum": list(_browser.EXES),
               "description": "Only if the user names a browser, e.g. 'in Edge' or 'from Chrome'."}


def web_engine() -> str:
    """RED_SEARCH_ENGINE (google, bing or duckduckgo), default google."""
    name = os.environ.get("RED_SEARCH_ENGINE", "").strip().lower()
    return name if name in WEB_ENGINES else "google"


def search_url(query: str, site: str = "web", engine: str = "google") -> str:
    q = quote_plus(" ".join(query.split()), safe="")
    if site in SITES:
        return SITES[site][1].format(q=q)
    return WEB_ENGINES.get(engine, WEB_ENGINES["google"]).format(q=q)


def _browsers(open_browser, browsers) -> _browser.Browsers:
    """open_browser on its own (tests, older callers) is the Windows-default opener."""
    return browsers or _browser.Browsers(default_open=open_browser)


def _where(asked: str | None, choice: _browser.Choice) -> tuple[str, str]:
    """(prefix, suffix) for the reply when the user named a browser.

    ("", " in Chrome") when it opened there; ("Edge isn't installed, so ", "")
    when it isn't installed and the Windows default opened the page instead.
    """
    if asked not in _browser.NAMES:
        return "", ""
    if choice.path:
        return "", f" in {choice.name}"
    return f"{_browser.NAMES[asked]} isn't installed, so ", " in your default browser"


class _BrowserTool(Tool):
    """open_url and web_search: the browser is the one the user named, if any."""

    def set_command(self, command: str) -> None:
        self._said = command            # the user's own words (Executor)

    def _named(self, asked: str | None) -> str | None:
        return _browser.from_words(self.__dict__.pop("_said", None), asked)


class WebSearch(_BrowserTool):
    name = "web_search"
    description = ("Open a search in the browser so the user can read the results, "
                   "including pictures, videos and places. Use site for YouTube videos, "
                   "images, maps, news or Wikipedia. Set browser only if the user names one "
                   "('search lofi in Edge').")
    args_schema = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "minLength": 1, "maxLength": MAX_QUERY,
                      "description": "What to search for, in the user's words."},
            "site": {"type": "string", "enum": ["web", *SITES],
                     "description": "Where to search. Default web."},
            "browser": BROWSER_ARG,
        },
        "required": ["query"],
        "additionalProperties": False,
    }

    def __init__(self, open_browser: Callable[[str], bool] | None = None,
                 engine: Callable[[], str] = web_engine, watch: Callable | None = None,
                 browsers: _browser.Browsers | None = None):
        self._browsers = _browsers(open_browser, browsers)
        self._engine = engine
        self._watch = watch

    def run(self, query: str, site: str = "web", browser: str | None = None) -> str:
        browser = self._named(browser)
        query = " ".join(query.split())
        if not query:
            raise ToolError("What should I search for?")
        if site not in SITES:
            site = "web"
        choice = self._browsers.pick(browser)
        # Results pages put the search words in the title: "lofi - YouTube".
        watcher = (self._watch or _windows.watch)(_windows.browser_target(choice.exe, query))
        if not self._browsers.open(search_url(query, site, self._engine()), choice):
            raise ToolError("I couldn't open the browser.")
        self.finish_later(watcher)
        where = "the web" if site == "web" else SITES[site][0]
        prefix, suffix = _where(browser, choice)
        if prefix:
            return f"{prefix}I searched {where} for {query}{suffix}."
        return f"Searching {where} for {query}{suffix}."


class OpenUrl(_BrowserTool):
    name = "open_url"
    description = ("Open a website the user names in the browser. Give a full URL "
                   "starting with https://, for example https://www.youtube.com for 'open "
                   "YouTube'. Set browser only if the user names one ('open YouTube from "
                   "Chrome'). Never build a search URL; use web_search to look things up.")
    args_schema = {
        "type": "object",
        "properties": {
            "url": {"type": "string", "pattern": "^https?://[^ ]+$", "maxLength": 2000},
            "browser": BROWSER_ARG,
        },
        "required": ["url"],
        "additionalProperties": False,
    }

    def __init__(self, open_browser: Callable[[str], bool] | None = None,
                 watch: Callable | None = None, browsers: _browser.Browsers | None = None):
        self._browsers = _browsers(open_browser, browsers)
        self._watch = watch

    def run(self, url: str, browser: str | None = None) -> str:
        browser = self._named(browser)
        url = url.strip()
        # The schema checks this too; check again so no other scheme, and nothing
        # that could pass for a command-line switch, ever reaches the browser.
        parts = urlsplit(url)
        if (parts.scheme.lower() not in {"http", "https"} or not parts.hostname
                or not _browser.safe_url(url)):
            raise ToolError("I can only open web addresses that start with http or https.")
        host = parts.hostname.removeprefix("www.")
        choice = self._browsers.pick(browser)
        target = _windows.browser_target(choice.exe, _windows.site_name(parts.hostname))
        watcher = (self._watch or _windows.watch)(target)
        if not self._browsers.open(url, choice):
            raise ToolError("I couldn't open the browser.")
        self.finish_later(watcher)
        prefix, suffix = _where(browser, choice)
        if prefix:
            return f"{prefix}I opened {host}{suffix}."
        return f"Opening {host}{suffix}."
