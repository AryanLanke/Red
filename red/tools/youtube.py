"""play_online: every "play ...": a song, artist, podcast, video or trailer on YouTube, with no API key.

Red has no local music player: the user plays everything online.

"Play whatever you like", "surprise me", "something calm": the active companion picks one of its own
songs (red/taste.py), searches its real title and artist, and says what and why in one line.

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
import logging
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

log = logging.getLogger(__name__)

SEARCH_URL = "https://www.youtube.com/results?search_query={q}"
WATCH_URL = "https://www.youtube.com/watch?v={id}"
# The user's own liked songs ("play my liked songs"). LL is YouTube's own name
# for that private playlist, available to anyone signed in in the browser.
LIKED_URL = "https://www.youtube.com/playlist?list=LL"
TIMEOUT_SECONDS = 6.0
MIN_VIDEO_SECONDS = 60         # below this it's usually a Short or a clip, not the song/video
MAX_RENDERERS = 3              # read enough of the page to have a few real results to choose from
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

_ANY_ID = re.compile(r'"videoId":"([A-Za-z0-9_-]{11})"')
_ID_OK = re.compile(r"[A-Za-z0-9_-]{11}")
# "Play some music", "play anything": no song named, so start a mix of popular songs.
_ANYTHING = re.compile(r"(?:some |any |a |the |my )?(?:music|songs?|tunes|anything|something|"
                       r"all|all (?:the |my )?songs|whatever)", re.I)
ANYTHING_QUERY = "popular songs mix"
# "Play my liked songs", "my favorites", "liked videos": YouTube's own Liked playlist.
_LIKED = re.compile(r"\b(?:my\s+)?(?:liked|favorite|favourite|loved)\s+(?:songs?|videos?|music|"
                    r"playlist)\b|\bmy\s+(?:likes|favorites|favourites)\b", re.I)
# "Play a short", "cat shorts": the only time a clip under a minute is wanted.
_SHORT = re.compile(r"\b(?:shorts?|clips?)\b", re.I)

# Words in a search that don't help choose a video ("play the official video").
_STOP = frozenset({"the", "and", "for", "with", "from", "official", "video", "music", "song",
                   "songs", "audio", "lyrics", "lyric", "full", "new", "play", "please", "short",
                   "shorts", "clip", "clips", "on", "youtube", "a", "an", "my", "of", "in", "to"})


def search_words(query: str) -> str:
    """What to search YouTube for: the user's words, or a mix when they named nothing."""
    query = " ".join(query.split())[:MAX_QUERY]
    return ANYTHING_QUERY if _ANYTHING.fullmatch(query.strip(" .!?")) else query


def is_liked_songs(query: str) -> bool:
    """'play my liked songs', 'my favorites': open the Liked playlist itself."""
    return bool(_LIKED.search(query))


def wants_short(query: str) -> bool:
    return bool(_SHORT.search(query))


def query_words(query: str) -> list[str]:
    """The words that should appear in a result's title (lower case, stop words dropped)."""
    return [w for w in re.findall(r"[a-z0-9']+", query.lower())
            if len(w) >= 3 and w not in _STOP]


def is_short_url(url: str) -> bool:
    return "/shorts/" in url.lower()


def duration_seconds(text: str) -> int | None:
    """'59:29' -> 3569, '1:02:03' -> 3723, '12 minutes, 25 seconds' -> 745."""
    text = " ".join(text.split()).lower()
    if ":" in text:
        parts = text.split(":")
        try:
            values = [int(p) for p in parts]
        except ValueError:
            return None
        if not 1 <= len(values) <= 3:
            return None
        seconds = 0
        for value in values:
            seconds = seconds * 60 + value
        return seconds
    minutes = re.search(r"(\d+)\s*minutes?", text)
    seconds = re.search(r"(\d+)\s*seconds?", text)
    if minutes or seconds:
        return (int(minutes.group(1)) * 60 if minutes else 0) + (int(seconds.group(1)) if seconds else 0)
    return None

Opener = Callable[..., object]


@dataclass(frozen=True)
class Video:
    id: str
    title: str = ""
    seconds: int | None = None      # length, when the results page says it

    @property
    def url(self) -> str:
        if not _ID_OK.fullmatch(self.id):
            raise ValueError(f"not a YouTube video id: {self.id!r}")
        return WATCH_URL.format(id=self.id)


def own_pick(query: str):
    """'play whatever you like': one of the active companion's own songs (red/taste.py), or None."""
    from .. import companions, taste
    return taste.own_pick(query, companions.active())


def search_url(query: str) -> str:
    return SEARCH_URL.format(q=quote_plus(" ".join(query.split()), safe=""))


def _json_text(raw: str) -> str:
    try:
        return json.loads(f'"{raw}"')
    except json.JSONDecodeError:
        return raw


def _balanced(text: str, begin: int) -> int:
    """The index just past the JSON object opening at `begin` (strings and escapes respected)."""
    depth, i, quoted, escaped = 0, begin, False, False
    while i < len(text):
        c = text[i]
        if quoted:
            if escaped:
                escaped = False
            elif c == "\\":
                escaped = True
            elif c == '"':
                quoted = False
        elif c == '"':
            quoted = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return -1


def _renderers(page: str):
    """(the raw JSON text, the parsed object) for each videoRenderer in the page."""
    i = page.find('"videoRenderer":')
    while i >= 0:
        begin = page.find("{", i + len('"videoRenderer":'))
        end = _balanced(page, begin) if begin >= 0 else -1
        if end < 0:
            return
        raw = page[begin:end]
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            data = None
        if isinstance(data, dict):
            yield raw, data
        i = page.find('"videoRenderer":', end)


def _title_of(data: dict) -> str:
    title = data.get("title") or {}
    runs = title.get("runs") or []
    if runs and isinstance(runs[0], dict):
        return _json_text(str(runs[0].get("text", "")))
    return str(title.get("simpleText", ""))


def _length_of(data: dict) -> int | None:
    length = data.get("lengthText") or {}
    text = length.get("simpleText")
    if not text:
        label = ((length.get("accessibility") or {}).get("accessibilityData") or {}).get("label", "")
        text = label
    return duration_seconds(str(text)) if text else None


def _is_short(data: dict, raw: str) -> bool:
    """A Short from the Shorts shelf, or a video that opens in the Shorts player."""
    return ("reelWatchEndpoint" in raw or "/shorts/" in raw
            or '"isShort":true' in raw.replace(" ", ""))


def all_videos(page: str) -> list[Video]:
    """Every ordinary video in the results page, in YouTube's order (Shorts left out)."""
    found = []
    for raw, data in _renderers(page):
        video_id = data.get("videoId")
        if not isinstance(video_id, str) or not _ID_OK.fullmatch(video_id):
            continue
        if _is_short(data, raw):
            continue
        found.append(Video(video_id, _title_of(data), _length_of(data)))
    return found


def first_video(page: str) -> Video | None:
    """The first real video in a YouTube results page (not a channel, playlist, Short or clip)."""
    for video in all_videos(page):
        if video.seconds is None or video.seconds >= MIN_VIDEO_SECONDS:
            return video
    m = _ANY_ID.search(page)
    return Video(m.group(1)) if m else None


def pick_video(page: str, query: str) -> Video | None:
    """The best video for `query`: no Shorts or clips, and a title with the search's words.

    None means nothing matched well; the caller then shows the search results
    so the user can pick, rather than opening the wrong song.
    """
    candidates = [v for v in all_videos(page)
                  if wants_short(query) or v.seconds is None or v.seconds >= MIN_VIDEO_SECONDS]
    if not candidates:
        return None
    if query == ANYTHING_QUERY:
        return candidates[0]
    words = query_words(query)
    for video in candidates:
        title = video.title.lower()
        if any(word in title for word in words):
            return video
    return None


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
    """Fetch the results page and pick the best video for `query`.

    Raises OSError if YouTube can't be reached. None means the page was read
    but nothing matched (the caller opens the search results instead).
    """
    req = urllib.request.Request(search_url(query), headers={
        "User-Agent": BROWSER_AGENT, "Accept-Language": "en-US,en;q=0.9"})
    page = b""
    with opener(req, timeout=timeout) as r:
        while len(page) < MAX_BYTES:
            chunk = r.read(CHUNK)
            if not chunk:
                break
            page += chunk
            text = page.decode("utf-8", "ignore")
            # Stop once a few real results (not just the Shorts shelf) are in.
            if text.count('"videoRenderer":') >= MAX_RENDERERS:
                last = text.rfind('"videoRenderer":')
                if len(text) - last > 8000:
                    break
    return pick_video(page.decode("utf-8", "replace"), query)


class PlayOnline(Tool):
    name = "play_online"
    description = ("Play anything the user asks to play, online on YouTube: a song, artist, "
                   "album, genre, podcast, video, trailer or talk, for example 'play Believer', "
                   "'play some Arijit Singh', 'play a podcast about loneliness', 'play the "
                   "Punisher trailer', 'play my liked songs' or 'play my favorites'. Starts "
                   "the best matching result, never a Short.")
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
                 browsers: _browser.Browsers | None = None, pick: Callable[[str], object] | None = None):
        # open_browser on its own (tests) is the Windows-default opener.
        self._browsers = browsers or _browser.Browsers(default_open=open_browser)
        self._find = find
        self._watch = watch
        self._pick = pick or own_pick       # "play whatever you like": the companion's own song (red/taste.py)

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
        picked = self._own_pick(query)
        if picked is not None:
            query = picked.query            # the real title and artist, never "whatever you like"
        elif is_liked_songs(query):
            if not self._open_and_front(LIKED_URL):
                raise ToolError("I couldn't open the browser.")
            return "Opening your liked songs on YouTube."
        query = search_words(query)
        try:
            video = self._find(query)
        except (OSError, urllib.error.URLError, socket.timeout, ValueError) as e:
            # Offline, slow or a changed page: the results page still lets you pick.
            if not self._open_and_front(search_url(query)):
                raise ToolError("I couldn't open the browser.") from e
            if picked is not None:
                return f"{picked.line} YouTube didn't answer, so I opened the search for it."
            return f"I couldn't reach YouTube's results, so I opened the search for {query}."
        if video is None:
            if not self._open_and_front(search_url(query)):
                raise ToolError("I couldn't open the browser.")
            if picked is not None:
                return f"{picked.line} I couldn't start it, so here's the search for it."
            return f"I didn't find a video to start, so here's the YouTube search for {query}."
        if not self._open_and_front(video.url):
            raise ToolError("I couldn't open the browser.")
        if picked is not None:
            return picked.line              # what, and why, in the companion's words
        title = spoken_title(video.title)
        return f"Playing {title} on YouTube." if title else f"Playing {query} on YouTube."

    def _own_pick(self, query: str):
        """The companion's own song when the user left the choice to it, else None."""
        from .. import taste
        if not taste.wants_own_pick(query):
            return None
        try:
            return self._pick(query)
        except Exception:  # noqa: BLE001 - a mix of popular songs beats nothing
            log.exception("Couldn't pick a song of the companion's own")
            return None
