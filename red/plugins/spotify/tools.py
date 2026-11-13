"""Spotify with no account (plan.md B3.2): search, and what's playing.

Play, pause, next and back are already the media keys. "Search Spotify for X"
opens a spotify:search: link (the query is URL-quoted, so it can't change the
link's shape). "What's playing?" reads the title of Spotify's window, which is
"Artist - Song" while it plays; no account, no network, no PowerShell.
"""

from __future__ import annotations

from urllib.parse import quote

from red.desk import Desk
from red.tools.base import Tool, ToolError

EXES = {"spotify.exe"}


class SpotifySearch(Tool):
    name = "spotify_search"
    description = "Search Spotify for a song, artist or playlist: 'search Spotify for Coldplay'."
    args_schema = {"type": "object",
                   "properties": {"query": {"type": "string", "minLength": 1, "maxLength": 100}},
                   "required": ["query"], "additionalProperties": False}

    def __init__(self, desk=None):
        self.desk = desk or Desk()

    def run(self, query: str) -> str:
        query = " ".join(query.split())
        if not query:
            raise ToolError("Search Spotify for what?")
        try:
            self.desk.open_uri(f"spotify:search:{quote(query, safe='')}")
        except OSError as e:
            raise ToolError("I couldn't open Spotify. Is it installed?") from e
        self.finish_later(lambda: self.desk.front_app(EXES))
        return f"Searching Spotify for {query}."


class WhatsPlaying(Tool):
    name = "whats_playing"
    description = "Say which song is playing in Spotify: 'what's playing?', 'what song is this?'."
    args_schema = {"type": "object", "properties": {}, "required": [], "additionalProperties": False}

    def __init__(self, windows=None):
        self._windows = windows

    def windows(self):
        if self._windows is not None:
            return self._windows()
        from red.windows import Win32Desktop
        return Win32Desktop().windows()

    def run(self) -> str:
        titles = [w.title for w in self.windows() if w.exe in EXES and w.title.strip()]
        if not titles:
            raise ToolError("Spotify isn't open, so nothing's playing there.")
        for title in titles:
            if " - " in title and not title.lower().startswith("spotify"):
                artist, song = title.split(" - ", 1)
                return f"{song.strip()} by {artist.strip()}."
        return "Spotify's open but nothing is playing."
