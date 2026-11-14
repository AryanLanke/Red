"""play_local: music from the user's own Music folder, opened with the default player.

Rules (plan.md 0.1 item 4 and 0.3 lane 2 task 7):
- Only files under the Music folder (Windows' Known Folder, never a path the model wrote), with an
  audio extension, found by scanning that folder. The model's words are only a search key against the
  names of files and folders that were really found; a path in them is never opened.
- A symbolic link or junction that leads out of the folder is not followed.
- "Play" is `os.startfile` on the file: the default player, nothing else is started or run.
- The tool is not in the router's list (every tool costs prompt tokens, and "play X" belongs to
  play_online); it is the music idle action's local source (red/idle.py), and `default_registry` can
  add it with `local_music_tools()` when the user wants "play something from my music".
"""

from __future__ import annotations

import os
import random
import re
from pathlib import Path
from typing import Callable

from ..known_folders import known_folder
from .base import Tool, ToolError

AUDIO = {".mp3", ".flac", ".wav", ".m4a", ".ogg", ".opus", ".aac", ".wma"}
MAX_FILES = 5000
MAX_DEPTH = 6
MAX_QUERY = 80

Startfile = Callable[[str], None]


def music_folder() -> Path | None:
    return known_folder("music")


def _is_link(path: Path) -> bool:
    """A symlink or a Windows junction/reparse point: never followed out of the folder."""
    try:
        if path.is_symlink():
            return True
        return bool(getattr(path.lstat(), "st_file_attributes", 0) & 0x400)      # FILE_ATTRIBUTE_REPARSE_POINT
    except OSError:
        return True


def inside(root: Path, path: Path) -> bool:
    """True when `path` really is under `root` once links are resolved."""
    try:
        path.resolve(strict=True).relative_to(root.resolve(strict=True))
    except (OSError, ValueError):
        return False
    return True


def scan(root: Path | None, limit: int = MAX_FILES) -> list[Path]:
    """The audio files under `root` (up to `limit`, `MAX_DEPTH` folders deep), without hidden folders or links."""
    if root is None or not root.is_dir():
        return []
    found: list[Path] = []
    base = len(root.parts)
    for folder, dirs, files in os.walk(root):
        here = Path(folder)
        dirs[:] = sorted(d for d in dirs if not d.startswith((".", "$")) and not _is_link(here / d)
                         and len(here.parts) - base < MAX_DEPTH)
        for name in sorted(files):
            path = here / name
            if path.suffix.lower() in AUDIO and not name.startswith(".") and not _is_link(path):
                found.append(path)
                if len(found) >= limit:
                    return found
    return found


_NOISE = re.compile(r"^\W*\d{1,3}\W+")                  # "01 - ", "07. "


def title_of(path: Path) -> str:
    """'01 - Daft Punk - Get Lucky.mp3' -> 'Daft Punk - Get Lucky', fit to say aloud."""
    stem = _NOISE.sub("", path.stem).replace("_", " ")
    return " ".join(stem.split())[:80] or path.stem


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9']+", text.lower()) if len(w) > 1 or w.isdigit()}


def match(files: list[Path], root: Path, query: str) -> list[Path]:
    """Files whose name or folder names share the most words with `query` (all of them if it's empty)."""
    wanted = _words(query) - {"play", "some", "the", "my", "music", "song", "songs", "from", "by", "a", "of", "to"}
    if not wanted:
        return list(files)
    scored = []
    for f in files:
        try:
            names = " ".join([f.stem, *f.relative_to(root).parent.parts])
        except ValueError:
            continue
        hit = len(wanted & _words(names))
        if hit:
            scored.append((hit, f))
    if not scored:
        return []
    best = max(score for score, _ in scored)
    return [f for score, f in scored if score == best]


def _default_startfile(path: str) -> None:
    os.startfile(path)  # type: ignore[attr-defined]  # Windows only


class PlayLocal(Tool):
    name = "play_local"
    description = ("Play a song from the user's own Music folder with their default player: "
                   "'play something from my music', 'play my local music'. Only files in the Music folder.")
    args_schema = {"type": "object",
                   "properties": {"query": {"type": "string", "maxLength": MAX_QUERY,
                                            "description": "Words of a song, artist or folder name; empty for any."}},
                   "required": [], "additionalProperties": False}

    def __init__(self, root: Path | None = None, startfile: Startfile = _default_startfile,
                 rng: random.Random | None = None):
        self._root = root
        self._startfile = startfile
        self._rng = rng or random.Random()
        self.last_played: Path | None = None

    @property
    def root(self) -> Path | None:
        return self._root or music_folder()

    def pick(self, query: str = "", avoid: set[Path] | None = None) -> Path | None:
        """A song for `query` (random among the best matches), or None when the folder has none."""
        root = self.root
        files = match(scan(root), root, query) if root else []
        files = [f for f in files if inside(root, f)]
        fresh = [f for f in files if not avoid or f not in avoid]
        return self._rng.choice(fresh or files) if files else None

    def play(self, path: Path) -> str:
        """Open `path` in the default player, if (and only if) it is an audio file under the Music folder."""
        root = self.root
        if root is None or path.suffix.lower() not in AUDIO or not inside(root, path):
            raise ToolError("I only play music from your Music folder.")
        try:
            self._startfile(str(path.resolve(strict=True)))
        except OSError as e:
            raise ToolError("I couldn't start the player.") from e
        self.last_played = path
        return f"Playing {title_of(path)}."

    def run(self, query: str = "") -> str:
        if self.root is None or not self.root.is_dir():
            raise ToolError("I can't find your Music folder.")
        path = self.pick(" ".join(query.split())[:MAX_QUERY])
        if path is None:
            raise ToolError("I don't see that in your Music folder." if query.strip()
                            else "There's no music in your Music folder.")
        return self.play(path)


def local_music_tools() -> list[Tool]:
    return [PlayLocal()]
