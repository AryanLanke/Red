"""play_online: every "play ...": a song, artist, podcast, video or trailer on YouTube, with no API key.

Red has no local music player: the user plays everything online.

Red fetches YouTube's public results page for the user's words, reads the
first video in it, and opens https://www.youtube.com/watch?v=<id> in the
browser (RED_BROWSER, Chrome by default), which starts playing, and brings
the window showing it to the front. Only the search words leave the PC. If the
page can't be fetched or read, Red opens the results page instead, so you
can still pick one.

The video id must be 11 letters, digits, - or _, and the URL is built from a
fixed template, so nothing from the page reaches the shell.
"""

from __future__ import annotations

import json
import re
import socket
import unicodedata
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Callable
from urllib.parse import quote_plus

from .. import browser as _browser
from .. import windows as _windows
from .base import Tool, ToolError

SEARCH_URL = "https://www.youtube.com/results?search_query={q}"
WATCH_URL = "https://www.youtube.com/watch?v={id}"
TIMEOUT_SECONDS = 6.0
# The results page is about 1.6 MB, and the first video comes after ~0.8 MB
# of page setup. Red reads in chunks and stops at the first video.
CHUNK = 128 * 1024
MAX_BYTES = 4_000_000
MAX_QUERY = 150
MAX_SPOKEN_TITLE = 80
# YouTube serves the full results page to browsers. A plain browser
# User-Agent is used, with no account, cookies or anything about the user.
BROWSER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                 "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")

_VIDEO = re.compile(r'"videoRenderer":\{"videoId":"([A-Za-z0-9_-]{11})"')
_ANY_ID = re.compile(r'"videoId":"([A-Za-z0-9_-]{11})"')
_TITLE = re.compile(r'"title":\{"runs":\[\{"text":"((?:[^"\\]|\\.)*)"')
_ID_OK = re.compile(r"[A-Za-z0-9_-]{11}")
# "Play some music", "play anything": no song named, so start a mix of popular songs.
_ANYTHING = re.compile(r"(?:some |any |a |the |my )?(?:music|songs?|tunes|anything|something|"
                       r"all|all (?:the |my )?songs|whatever)", re.I)
ANYTHING_QUERY = "popular songs mix"


def search_words(query: str) -> str:
    """What to search YouTube for: the user's words, or a mix when they named nothing."""
    query = " ".join(query.split())[:MAX_QUERY]
    return ANYTHING_QUERY if _ANYTHING.fullmatch(query.strip(" .!?")) else query

Opener = Callable[..., object]


@dataclass(frozen=True)
class Video:
    id: str
    title: str = ""

    @property
    def url(self) -> str:
        if not _ID_OK.fullmatch(self.id):
            raise ValueError(f"not a YouTube video id: {self.id!r}")
        return WATCH_URL.format(id=self.id)


def search_url(query: str) -> str:
    return SEARCH_URL.format(q=quote_plus(" ".join(query.split()), safe=""))


def _json_text(raw: str) -> str:
    try:
        return json.loads(f'"{raw}"')
    except json.JSONDecodeError:
        return raw


def first_video(page: str) -> Video | None:
    """The first real video in a YouTube results page (not a channel, playlist or Short)."""
    m = _VIDEO.search(page)
    if m is None:
        m = _ANY_ID.search(page)
        return Video(m.group(1)) if m else None
    title = _TITLE.search(page, m.end(), m.end() + 8000)
    return Video(m.group(1), _json_text(title.group(1)) if title else "")


def spoken_title(title: str) -> str:
    """'Punisher | Official Trailer | Netflix #shorts' -> 'Punisher', short enough to say."""
    title = re.sub(r"\s#\w+", "", title)
    # Emoji and other pictures don't read aloud.
    title = "".join(c for c in title if unicodedata.category(c) not in {"So", "Sk", "Cs", "Co", "Cn"}
                    and c != "️")
    title = title.split(" | ")[0].strip(" -|")
    title = " ".join(title.split())
    if len(title) > MAX_SPOKEN_TITLE:
        title = title[:MAX_SPOKEN_TITLE].rsplit(" ", 1)[0].rstrip(" ,-:;") + "..."
    return title


def fetch_results(query: str, opener: Opener = urllib.request.urlopen,
                  timeout: float = TIMEOUT_SECONDS) -> Video | None:
    """Fetch the results page and return its first video. Raises OSError if YouTube can't be reached."""
    req = urllib.request.Request(search_url(query), headers={
        "User-Agent": BROWSER_AGENT, "Accept-Language": "en-US,en;q=0.9"})
    page = b""
    with opener(req, timeout=timeout) as r:
        while len(page) < MAX_BYTES:
            chunk = r.read(CHUNK)
            if not chunk:
                break
            page += chunk
            # Stop once the first video and a little after it (its title) are in.
            m = _VIDEO.search(page.decode("utf-8", "ignore"))
            if m is not None and len(page) - m.end() > 8000:
                break
    return first_video(page.decode("utf-8", "replace"))


class PlayOnline(Tool):
    name = "play_online"
    description = ("Play anything the user asks to play, online on YouTube: a song, artist, "
                   "album, genre, podcast, video, trailer or talk, for example 'play Believer', "
                   "'play some Arijit Singh', 'play a podcast about loneliness', 'play the "
                   "Punisher trailer'. Starts the first result.")
    args_schema = {
        "type": "object",
        "properties": {"query": {
            "type": "string", "minLength": 1, "maxLength": MAX_QUERY,
            "description": "What to play, as words to search YouTube for, e.g. \"Believer\", "
                           "\"Arijit Singh songs\" or \"podcast about loneliness\"."}},
        "required": ["query"],
        "additionalProperties": False,
    }

    def __init__(self, open_browser: Callable[[str], bool] | None = None,
                 find: Callable[[str], Video | None] = fetch_results, watch: Callable | None = None,
                 browsers: _browser.Browsers | None = None):
        # open_browser on its own (tests) is the Windows-default opener.
        self._browsers = browsers or _browser.Browsers(default_open=open_browser)
        self._find = find
        self._watch = watch

    def _open_and_front(self, url: str) -> bool:
        choice = self._browsers.pick()
        # A watch page's title ends in "- YouTube".
        watcher = (self._watch or _windows.watch)(_windows.browser_target(choice.exe, "youtube"))
        if not self._browsers.open(url, choice):
            return False
        self.finish_later(watcher)       # bring the browser to the front while Red speaks
        return True

    def run(self, query: str) -> str:
        if not " ".join(query.split()):
            raise ToolError("What should I play?")
        query = search_words(query)
        try:
            video = self._find(query)
        except (OSError, urllib.error.URLError, socket.timeout, ValueError) as e:
            # Offline, slow or a changed page: the results page still lets you pick.
            if not self._open_and_front(search_url(query)):
                raise ToolError("I couldn't open the browser.") from e
            return f"I couldn't reach YouTube's results, so I opened the search for {query}."
        if video is None:
            if not self._open_and_front(search_url(query)):
                raise ToolError("I couldn't open the browser.")
            return f"I didn't find a video to start, so here's the YouTube search for {query}."
        if not self._open_and_front(video.url):
            raise ToolError("I couldn't open the browser.")
        title = spoken_title(video.title)
        return f"Playing {title} on YouTube." if title else f"Playing {query} on YouTube."
