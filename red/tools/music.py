"""Music tools: play songs from a local folder, and stop, pause, resume or skip.

The music folder is RED_MUSIC_DIR, or the user's Music folder by default.
The model's text is only a search term matched against file and folder
names in that folder; it is never used as a path.

Playback uses pygame-ce (SDL_mixer), which plays mp3, ogg, opus, flac and wav
without installing VLC. It runs inside Red's process on a background thread,
so music keeps playing after `run()` returns and stops when Red exits.
"""

from __future__ import annotations

import difflib
import logging
import os
import random
import re
import threading
import time
import unicodedata
from pathlib import Path
from typing import Callable, Protocol, Sequence

from .base import Tool

log = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = frozenset({".mp3", ".ogg", ".opus", ".flac", ".wav"})
MAX_FILES = 20_000          # stop scanning after this many songs
FUZZY_RATIO = 0.8           # how close a misheard word must be to count

# Words that say "music" without naming anything. Removed from both the
# query and the file names, so "songs by the beatles" matches "The Beatles".
_FILLER = frozenset({
    "a", "an", "the", "some", "any", "my", "me", "by", "from", "of", "please",
    "song", "songs", "music", "track", "tracks", "tune", "tunes", "album", "playlist",
})

# Whole queries that mean "no particular song". The model tends to fill the
# optional query with one of these instead of leaving it out.
_EVERYTHING = frozenset({
    "all", "any", "anything", "everything", "none", "null", "nil", "undefined", "n a",
    "random", "shuffle", "shuffled", "something", "whatever", "my", "all of it",
})


def wants_everything(query: str | None) -> bool:
    """True when `query` names nothing, so Red should shuffle the whole library."""
    if not query:
        return True
    words = re.sub(r"[^a-z0-9]+", " ", query.lower()).strip()
    return words in _EVERYTHING or not _tokens(query)


def music_dir() -> Path:
    """RED_MUSIC_DIR, otherwise the user's Music folder."""
    explicit = os.environ.get("RED_MUSIC_DIR", "").strip()
    if explicit:
        return Path(explicit).expanduser()
    # Integration: replace with red.known_folders.known_folder("music"), which
    # also finds a Music folder that was moved to OneDrive.
    return Path.home() / "Music"


def _tokens(text: str) -> list[str]:
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c)).lower()
    text = text.replace("'", "")       # "don't" -> "dont"
    return [t for t in re.split(r"[^a-z0-9]+", text) if t and t not in _FILLER]


def song_title(path: Path) -> str:
    """'03 - Get Lucky.mp3' -> 'Get Lucky'."""
    # "08 - x", "3. x", "01 x" are track numbers; "7 Rings" and "1999" are titles.
    title = re.sub(r"^(?:\d{1,3}\s*[-._)]\s*|\d{2,3}\s+)", "", path.stem).strip()
    return title or path.stem


class Library:
    """The songs under one folder."""

    def __init__(self, root: Path, max_files: int = MAX_FILES):
        self.root = Path(root)
        self.max_files = max_files

    def scan(self) -> list[Path]:
        tracks: list[Path] = []
        for folder, dirs, files in os.walk(self.root):
            dirs[:] = sorted(d for d in dirs if not d.startswith("."))
            for name in sorted(files):
                if Path(name).suffix.lower() in SUPPORTED_EXTENSIONS:
                    tracks.append(Path(folder) / name)
                    if len(tracks) >= self.max_files:
                        return tracks
        return tracks

    def find(self, query: str, tracks: Sequence[Path] | None = None) -> list[Path]:
        """Songs whose name or folders match `query`, best matches only.

        Ranking: a song or folder named exactly the query, then songs whose path
        contains every word of the query, then close (misheard) matches.
        """
        want = _tokens(query)
        if not want:
            return []
        tracks = self.scan() if tracks is None else tracks
        want_text = " ".join(want)
        best: list[Path] = []
        best_score = 0
        for track in tracks:
            score = self._score(track, want, want_text)
            if score > best_score:
                best, best_score = [track], score
            elif score and score == best_score:
                best.append(track)
        return best

    def _score(self, track: Path, want: list[str], want_text: str) -> int:
        try:
            parts = track.relative_to(self.root).parts
        except ValueError:
            parts = (track.name,)
        folders = [_tokens(p) for p in parts[:-1]]
        title = _tokens(song_title(track))
        if title == want or any(f == want for f in folders):
            return 3
        have = set(title).union(*folders)
        if all(w in have for w in want):
            return 2
        if all(difflib.get_close_matches(w, have, n=1, cutoff=FUZZY_RATIO) for w in want):
            return 1
        if difflib.SequenceMatcher(None, want_text, " ".join(title)).ratio() >= FUZZY_RATIO:
            return 1
        return 0


# --------------------------------------------------------------------------
# Players
# --------------------------------------------------------------------------

class PlayerError(RuntimeError):
    """Playback couldn't start (no audio device, missing library, ...)."""


class Player(Protocol):
    @property
    def current(self) -> Path | None: ...
    @property
    def paused(self) -> bool: ...
    def play(self, tracks: Sequence[Path]) -> Path | None: ...   # first song that played
    def stop(self) -> bool: ...                                  # False if nothing was playing
    def pause(self) -> bool: ...
    def resume(self) -> bool: ...
    def next(self) -> Path | None: ...                           # None at the end of the list


class PygamePlayer:
    """Plays a list of files one after another with pygame-ce's mixer.

    The mixer opens the audio device on the first `play()`, not on import.
    A daemon thread starts the next song when one ends.
    """

    def __init__(self, poll_seconds: float = 0.25):
        self._poll = poll_seconds
        self._lock = threading.RLock()
        self._queue: list[Path] = []
        self._index = -1
        self._paused = False
        self._music = None
        self._error: type[Exception] = Exception
        self._watcher: threading.Thread | None = None

    @property
    def current(self) -> Path | None:
        with self._lock:
            return self._queue[self._index] if 0 <= self._index < len(self._queue) else None

    @property
    def paused(self) -> bool:
        return self._paused

    def _mixer(self):
        if self._music is None:
            os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
            try:
                import pygame
            except ImportError as e:
                raise PlayerError("pygame-ce isn't installed") from e
            try:
                pygame.mixer.init()
            except pygame.error as e:
                raise PlayerError(f"no audio output ({e})") from e
            self._music, self._error = pygame.mixer.music, pygame.error
        return self._music

    def play(self, tracks: Sequence[Path]) -> Path | None:
        with self._lock:
            self._mixer()
            self._queue, self._index, self._paused = list(tracks), -1, False
            first = self._advance()
            if self._watcher is None:
                self._watcher = threading.Thread(target=self._watch, name="red-music",
                                                 daemon=True)
                self._watcher.start()
            return first

    def _advance(self) -> Path | None:
        """Start the next playable song. Call with the lock held."""
        music = self._music
        while self._index + 1 < len(self._queue):
            self._index += 1
            track = self._queue[self._index]
            try:
                music.load(str(track))
                music.play()
                self._paused = False
                return track
            except self._error as e:
                log.warning("Skipping %s: %s", track, e)
        self._clear()
        return None

    def _clear(self) -> None:
        if self._music is not None:
            self._music.stop()
            self._music.unload()
        self._queue, self._index, self._paused = [], -1, False

    def stop(self) -> bool:
        with self._lock:
            was_playing = bool(self._queue)
            self._clear()
            return was_playing

    def pause(self) -> bool:
        with self._lock:
            if not self._queue or self._paused:
                return False
            self._music.pause()
            self._paused = True
            return True

    def resume(self) -> bool:
        with self._lock:
            if not self._queue or not self._paused:
                return False
            self._music.unpause()
            self._paused = False
            return True

    def next(self) -> Path | None:
        with self._lock:
            if not self._queue:
                return None
            return self._advance()

    def _watch(self) -> None:
        while True:   # daemon thread: ends with Red
            time.sleep(self._poll)
            with self._lock:
                if self._queue and not self._paused and not self._music.get_busy():
                    self._advance()


_shared_player: Player | None = None
_shared_lock = threading.Lock()


def default_player() -> Player:
    """One player shared by all the music tools, created on first use."""
    global _shared_player
    with _shared_lock:
        if _shared_player is None:
            _shared_player = PygamePlayer()
        return _shared_player


# --------------------------------------------------------------------------
# Tools
# --------------------------------------------------------------------------

_NO_ARGS = {"type": "object", "properties": {}, "additionalProperties": False}


class _MusicTool(Tool):
    def __init__(self, player: Player | None = None):
        self._player = player

    @property
    def player(self) -> Player:
        return self._player or default_player()


class PlayMusic(_MusicTool):
    name = "play_music"
    description = ("Play music from the user's music folder: a named song, artist, album "
                   "or genre, or shuffle all songs.")
    args_schema = {
        "type": "object",
        "properties": {"query": {
            "type": "string", "minLength": 1, "maxLength": 100,
            "description": "The song, artist, album or folder name the user said, "
                           "or \"all\" to shuffle all songs."}},
        "additionalProperties": False,
    }

    def __init__(self, player: Player | None = None, library: Library | None = None,
                 folder: Callable[[], Path] = music_dir,
                 shuffle: Callable[[list], None] = random.shuffle):
        super().__init__(player)
        self._library = library
        self._folder = folder
        self._shuffle = shuffle

    def run(self, query: str | None = None) -> str:
        library = self._library or Library(self._folder())
        if not library.root.is_dir():
            return f"I can't find your music folder at {library.root}."
        tracks = library.scan()
        if not tracks:
            return f"There's no music I can play in {library.root}."

        if not wants_everything(query):
            tracks = library.find(query, tracks)
            if not tracks:
                return f"I couldn't find any music matching {query}."
        else:
            query = None

        tracks = list(tracks)
        if len(tracks) > 1:
            self._shuffle(tracks)
        try:
            first = self.player.play(tracks)
        except PlayerError as e:
            return f"I couldn't play music: {e}."
        if first is None:
            return "I couldn't play any of those files."
        if len(tracks) == 1:
            return f"Playing {song_title(first)}."
        if query:
            return f"Shuffling {len(tracks)} songs matching {query}, starting with {song_title(first)}."
        return f"Shuffling all {len(tracks)} songs, starting with {song_title(first)}."


class StopMusic(_MusicTool):
    name = "stop_music"
    description = "Stop the music that is playing."
    args_schema = _NO_ARGS

    def run(self) -> str:
        return "Music stopped." if self.player.stop() else "No music is playing."


class PauseMusic(_MusicTool):
    name = "pause_music"
    description = "Pause the music that is playing, so it can be resumed later."
    args_schema = _NO_ARGS

    def run(self) -> str:
        if self.player.pause():
            return "Paused."
        return "The music is already paused." if self.player.paused else "No music is playing."


class ResumeMusic(_MusicTool):
    name = "resume_music"
    description = "Resume (unpause) music that was paused."
    args_schema = _NO_ARGS

    def run(self) -> str:
        if self.player.resume():
            current = self.player.current
            return f"Resuming {song_title(current)}." if current else "Resuming."
        return "The music isn't paused." if self.player.current else "No music is playing."


class NextSong(_MusicTool):
    name = "next_song"
    description = "Skip to the next song in the music that is playing."
    args_schema = _NO_ARGS

    def run(self) -> str:
        if self.player.current is None:
            return "No music is playing."
        track = self.player.next()
        return f"Playing {song_title(track)}." if track else "That was the last song."
