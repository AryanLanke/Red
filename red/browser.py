"""Which browser opens pages: RED_BROWSER, or the one the user names.

Windows' default browser isn't always the one you use (on the developer's
PC it's Edge, but Chrome is the one with YouTube open). So Red starts the
browser named by RED_BROWSER (chrome by default; edge, firefox, or default
for the Windows default), or the one asked for ("open YouTube from Chrome").

The browser's program is found through the registry's App Paths, like
open_app, never by guessing paths. It is started with the URL as its only
argument, a list and no shell. The URL must start with http:// or https://
and have no spaces, quotes or control characters, so it can't turn into a
command-line switch. If that browser isn't installed, the Windows default
opens the page instead.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

log = logging.getLogger(__name__)

CHOICES = ("chrome", "edge", "firefox", "default")
DEFAULT = "chrome"
# The browsers the user can name, their App Paths key, and how Red says them.
EXES = {"chrome": "chrome.exe", "edge": "msedge.exe", "firefox": "firefox.exe"}
NAMES = {"chrome": "Chrome", "edge": "Edge", "firefox": "Firefox"}


def find_exe(exe: str) -> str | None:
    """The browser's registered program (App Paths). Tests replace this."""
    from .tools.apps import read_app_path   # here: red.tools imports this module
    return read_app_path(exe)


def configured() -> str:
    """RED_BROWSER: chrome, edge, firefox or default. Unknown or unset means chrome."""
    name = os.environ.get("RED_BROWSER", "").strip().lower()
    return name if name in CHOICES else DEFAULT


# "in Edge", "from Google Chrome", "using Firefox". Chrome and Firefox are
# browsers wherever they're said; "edge" only after in/from/..., so "the edge
# of tomorrow" isn't a browser.
_NAMED = re.compile(r"\b(?:(?:in|from|on|using|with|via|through)\s+(?:the\s+)?"
                    r"(?:google\s+|microsoft\s+|mozilla\s+)?(chrome|edge|firefox)"
                    r"|(chrome|firefox))\b", re.IGNORECASE)


def named_in(words: str) -> set[str]:
    """The browsers the user's words name."""
    return {(a or b).lower() for a, b in _NAMED.findall(words)}


def from_words(said: str | None, asked: str | None) -> str | None:
    """The browser to use: the model's pick only if the user named it.

    said is the user's own words (None when unknown: then the model's pick
    stands). If they name one browser, that's the one, whatever the model
    filled in; if they name none, the setting decides.
    """
    if said is None:
        return asked if asked in EXES else None
    named = named_in(said)
    if asked in named:
        return asked
    return next(iter(named)) if len(named) == 1 else None


def safe_url(url: str) -> bool:
    """Only plain web addresses reach a browser's command line."""
    return (url.lower().startswith(("http://", "https://"))
            and not any(c.isspace() or ord(c) < 32 or c in '"<>' for c in url))


@dataclass(frozen=True)
class Choice:
    """The browser a page opens in. path None means the Windows default."""

    key: str | None = None      # "chrome"
    path: str | None = None     # "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe"

    @property
    def exe(self) -> str | None:
        """'chrome.exe', for finding its windows. None for the Windows default."""
        return EXES[self.key] if self.key and self.path else None

    @property
    def name(self) -> str:
        return NAMES.get(self.key or "", "your browser") if self.path else "your browser"


class Browsers:
    """Picks and starts a browser. Every side effect can be replaced in tests."""

    def __init__(self, default_open: Callable[[str], bool] | None = None,
                 read: Callable[[str], str | None] | None = None,
                 exists: Callable[[Path], bool] = Path.exists,
                 popen: Callable | None = None,
                 setting: Callable[[], str] = configured):
        # None: looked up when used, so tests can switch the real ones off in one place.
        self._default_open = default_open
        self._read = read
        self._exists = exists
        self._popen = popen
        self._setting = setting

    def pick(self, wanted: str | None = None) -> Choice:
        """The asked-for browser, else RED_BROWSER's, if it's installed; else the default."""
        key = wanted if wanted in EXES else self._setting()
        if key not in EXES:
            return Choice()
        path = (self._read or find_exe)(EXES[key])
        if not path:
            log.info("%s isn't installed; using the Windows default browser", NAMES[key])
            return Choice(key)
        found = Path(path)
        # Store-packaged builds can't be started by path; let Windows pick.
        if "windowsapps" in (p.lower() for p in found.parts) or not self._exists(found):
            return Choice(key)
        return Choice(key, str(found))

    def open(self, url: str, choice: Choice) -> bool:
        """Open url in the chosen browser. False if nothing could open it."""
        if not safe_url(url):
            raise ValueError(f"not a plain web address: {url[:80]!r}")
        if choice.path:
            try:
                # The URL is the one argument: a list and no shell.
                (self._popen or subprocess.Popen)(
                    [choice.path, url], shell=False, close_fds=True,
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return True
            except OSError:
                log.exception("Couldn't start %s; trying the Windows default", choice.path)
        return bool((self._default_open or webbrowser.open)(url))
