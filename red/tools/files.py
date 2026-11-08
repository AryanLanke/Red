"""Find files and folders by name, and open what was found.

`find_file` searches only Windows' standard folders (Desktop, Documents,
Downloads, Pictures, Music, Videos) and the folders in allowlist.toml, never
the whole disk. It only reads folder listings, stops after a time limit, and
keeps the best few matches. `open_found_file` opens one of those matches;
programs and scripts are never run, Red opens their folder instead.
"""

from __future__ import annotations

import difflib
import heapq
import os
import re
import threading
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .. import allowlist as _allowlist
from .. import known_folders as _known
from .base import Tool, ToolError

TIME_LIMIT_SECONDS = 4.0
MAX_ENTRIES = 300_000       # folder entries looked at, across all roots
MAX_RESULTS = 5

# Searched first, because that's where people keep things.
ROOT_ORDER = ("desktop", "documents", "downloads", "pictures", "videos", "music")

# Folders that are big and never what someone means by "my file".
SKIP_DIRS = frozenset({
    "node_modules", "__pycache__", "site-packages", ".git", ".venv", "venv", "appdata",
    "$recycle.bin", "system volume information", "windowsapps", "cache", "caches",
    "dist", "obj", ".next", "target",
})

# Opening these would run code, so Red opens the containing folder instead.
RUNNABLE = frozenset({
    ".exe", ".com", ".bat", ".cmd", ".ps1", ".psm1", ".vbs", ".vbe", ".js", ".jse",
    ".wsf", ".wsh", ".msi", ".msp", ".scr", ".pif", ".cpl", ".hta", ".jar", ".lnk",
    ".url", ".reg", ".inf", ".py", ".pyw", ".sh", ".application", ".appref-ms",
    ".settingcontent-ms", ".library-ms", ".msc", ".gadget", ".vb", ".ws",
})

_FILLER = frozenset({"my", "the", "a", "an", "file", "folder", "called", "named", "document",
                     "doc"})


def _words(text: str) -> list[str]:
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c)).lower().replace("'", "")
    # Split camelCase-free runs of letters and digits: "Resume_2024.pdf" -> resume 2024 pdf
    return [w for w in re.split(r"[^a-z0-9]+", text) if w]


def query_words(query: str) -> list[str]:
    return [w for w in _words(query) if w not in _FILLER]


def score(name: str, want: list[str]) -> int:
    """4 exact name, 3 every word, 2 every word inside the name, 1 close (misheard)."""
    have = _words(name)
    stem = _words(Path(name).stem) if "." in name else have
    if stem == want or have == want:
        return 4
    if all(w in have for w in want):
        return 3
    joined = "".join(have)
    if all(w in joined for w in want):
        return 2
    if all(difflib.get_close_matches(w, have, n=1, cutoff=0.8) for w in want):
        return 1
    return 0


@dataclass(frozen=True)
class Match:
    path: Path
    root_name: str      # "Documents"
    root: Path
    is_dir: bool
    score: int
    mtime: float

    @property
    def where(self) -> str:
        """'Documents\\Jobs' for the folder that holds the match."""
        try:
            rel = self.path.parent.relative_to(self.root)
        except ValueError:
            return str(self.path.parent)
        return self.root_name if str(rel) == "." else f"{self.root_name}\\{rel}"

    def detail(self, number: int) -> str:
        kind = "folder" if self.is_dir else "file"
        return f"{number}. {self.path.name} ({kind}) in {self.where}: {self.path}"


@dataclass
class SearchResult:
    query: str
    matches: list[Match]
    partial: bool        # stopped early because of the time or entry limit
    looked_at: int


def search(query: str, roots: list[tuple[str, Path]], kind: str = "any",
           time_limit: float = TIME_LIMIT_SECONDS, max_entries: int = MAX_ENTRIES,
           max_results: int = MAX_RESULTS, clock: Callable[[], float] = time.monotonic,
           scandir=os.scandir) -> SearchResult:
    """Walk the roots breadth-first and keep the best `max_results` matches."""
    want = query_words(query)
    if not want:
        return SearchResult(query, [], False, 0)
    deadline = clock() + time_limit
    # Min-heap on (score, is a file, mtime): on equal scores files beat folders,
    # because "find my resume" usually means a document, then newer beats older.
    best: list[tuple[int, bool, float, str, Match]] = []
    seen: set[str] = set()
    looked = 0
    partial = False

    queue: list[tuple[str, Path, Path]] = [(name, root, root) for name, root in roots]
    while queue:
        root_name, root, folder = queue.pop(0)
        key = os.path.normcase(str(folder))
        if key in seen:
            continue
        seen.add(key)
        try:
            entries = list(scandir(folder))
        except OSError:
            continue
        for entry in entries:
            looked += 1
            if looked > max_entries or clock() > deadline:
                partial = True
                queue = []
                break
            name = entry.name
            try:
                is_dir = entry.is_dir(follow_symlinks=False)
            except OSError:
                continue
            if is_dir and not (name.startswith(".") or name.lower() in SKIP_DIRS
                               or _is_hidden(entry)):
                queue.append((root_name, root, Path(entry.path)))
            if (kind == "file" and is_dir) or (kind == "folder" and not is_dir):
                continue
            s = score(name, want)
            if not s:
                continue
            try:
                mtime = entry.stat(follow_symlinks=False).st_mtime
            except OSError:
                mtime = 0.0
            m = Match(Path(entry.path), root_name, root, is_dir, s, mtime)
            item = (s, not is_dir, mtime, entry.path, m)
            if len(best) < max_results:
                heapq.heappush(best, item)
            elif item[:4] > best[0][:4]:
                heapq.heapreplace(best, item)
    matches = [item[-1] for item in sorted(best, key=lambda i: i[:4], reverse=True)]
    return SearchResult(query, matches, partial, looked)


def _is_hidden(entry) -> bool:
    try:
        attrs = entry.stat(follow_symlinks=False).st_file_attributes
    except (OSError, AttributeError):
        return False
    return bool(attrs & 0x6)        # FILE_ATTRIBUTE_HIDDEN | FILE_ATTRIBUTE_SYSTEM


def default_roots(allowlist=None, known=_known.all_known_folders) -> list[tuple[str, Path]]:
    """Known folders first (in ROOT_ORDER), then the allowlist's folders."""
    folders = known()
    roots = [(name.capitalize(), folders[name]) for name in ROOT_ORDER if name in folders]
    try:
        allow = allowlist() if callable(allowlist) else (allowlist or _allowlist.load_allowlist())
        roots += [(name, path) for name, path in allow.folders.items()]
    except ToolError:
        pass            # a broken allowlist.toml shouldn't stop a search of the known folders
    return [(n, p) for n, p in roots if p.is_dir()]


class FoundFiles:
    """The last search's matches, shared by find_file and open_found_file."""

    def __init__(self):
        self._lock = threading.Lock()
        self._matches: list[Match] = []

    def set(self, matches: list[Match]) -> None:
        with self._lock:
            self._matches = list(matches)

    def get(self) -> list[Match]:
        with self._lock:
            return list(self._matches)


_shared = FoundFiles()


def _default_startfile(path: str) -> None:
    os.startfile(path)  # type: ignore[attr-defined]  # Windows only


class FindFile(Tool):
    name = "find_file"
    description = ("Find a file or folder on this PC by its name, for example 'find my "
                   "resume' or 'where is the budget spreadsheet'. Searches the user's folders.")
    args_schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "minLength": 1, "maxLength": 200,
                     "description": "Words from the file or folder name."},
            "kind": {"type": "string", "enum": ["any", "file", "folder"]},
        },
        "required": ["name"],
        "additionalProperties": False,
    }

    def __init__(self, roots: Callable[[], list[tuple[str, Path]]] = default_roots,
                 found: FoundFiles | None = None, time_limit: float = TIME_LIMIT_SECONDS,
                 searcher=search):
        self._roots = roots
        self._found = found or _shared
        self._time_limit = time_limit
        self._search = searcher
        self.last_details = ""

    def run(self, name: str, kind: str = "any") -> str:
        self.last_details = ""
        if not query_words(name):
            raise ToolError("What's the file called?")
        roots = self._roots()
        if not roots:
            raise ToolError("I don't have any folders to search.")
        result = self._search(name, roots, kind if kind in ("file", "folder") else "any",
                              time_limit=self._time_limit)
        self._found.set(result.matches)
        self.last_details = "\n".join(m.detail(i) for i, m in enumerate(result.matches, 1))
        if not result.matches:
            more = " in the time I had" if result.partial else ""
            return f"I couldn't find anything called {name} in your folders{more}."
        best = result.matches[0]
        what = f"a folder called {best.path.name}" if best.is_dir else best.path.name
        reply = f"I found {what} in {best.where}"
        others = len(result.matches) - 1
        if others:
            reply += f", and {others} other match{'es' if others > 1 else ''}"
        return reply + ". Say open it to open it."


class OpenFoundFile(Tool):
    name = "open_found_file"
    description = ("Open a file or folder that find_file just found, for example 'open it' "
                   "or 'open the second one'.")
    args_schema = {
        "type": "object",
        "properties": {"number": {"type": "integer", "minimum": 1, "maximum": MAX_RESULTS,
                                  "description": "Which match; 1 is the best."}},
        "additionalProperties": False,
    }

    def __init__(self, found: FoundFiles | None = None,
                 startfile: Callable[[str], None] = _default_startfile):
        self._found = found or _shared
        self._startfile = startfile

    def run(self, number: int = 1) -> str:
        matches = self._found.get()
        if not matches:
            raise ToolError("Find a file first, for example say find my resume.")
        if not 1 <= number <= len(matches):
            raise ToolError(f"I only found {len(matches)} match"
                            f"{'es' if len(matches) != 1 else ''}.")
        m = matches[number - 1]
        if not m.path.exists():
            raise ToolError(f"{m.path.name} isn't there any more.")
        try:
            if m.is_dir or m.path.suffix.lower() not in RUNNABLE:
                self._startfile(str(m.path))
                return f"Opening {m.path.name}."
            # Never run a program or script; show where it is instead.
            self._startfile(str(m.path.parent))
        except OSError as e:
            raise ToolError(f"I couldn't open {m.path.name}: {e.strerror or e}") from e
        return f"{m.path.name} is a program or script, so I opened its folder instead."
