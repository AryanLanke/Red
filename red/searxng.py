"""Red's own SearXNG: installed by setup, started and stopped by Red.

look_up checks web pages through a SearXNG on this PC (red/tools/sources.py).
So that users install nothing themselves, `python -m red setup` puts one in
RED_HOME\\searxng, and Red starts it hidden while it runs:

- A pinned SearXNG commit, checked against its SHA-256 like every other download.
  Only what it needs to run is unpacked (the `searx` package and
  requirements.txt); the rest has file names Windows can't create.
- A small fix so it runs on Windows (`pwd` exists only on Linux and macOS).
- Its own venv, so its packages never mix with Red's.
- Settings that listen on 127.0.0.1 only, answer in JSON, and have a random
  secret made on this PC.
- Red starts it on a free port, as a ManagedServer: it dies with Red, even
  after a crash. It starts in the background so Red's start isn't slower.
  If it can't start, Red carries on with Wikipedia only and logs why.

RED_WEB_SEARCH=off turns it off. If RED_SEARCH_URL is set, that SearXNG is
used and Red starts none of its own.

SearXNG is AGPL-3.0 licensed (its LICENSE file is kept in the install folder);
Red talks to it only over HTTP.
"""

from __future__ import annotations

import logging
import os
import secrets
import shutil
import subprocess
import sys
import threading
import urllib.request
import zipfile
from pathlib import Path
from typing import Callable

from .config import Settings
from .downloads import DownloadError, download
from .process import ManagedServer, child_env, free_port

log = logging.getLogger(__name__)

COMMIT = "57ff753ad416b7bf27e59d72ae8c7cac93b56be4"          # 2026-11-09
ARCHIVE_URL = f"https://github.com/searxng/searxng/archive/{COMMIT}.zip"
ARCHIVE_SHA256 = "0b22645df495343e39f151b9e29439c6cfb51a11af32363c4cc5848366463e3e"
START_TIMEOUT = 90.0         # loading its engines takes a few seconds; a cold disk, more
WARM_TIMEOUT = 10.0
WANTED = ("searx/", "requirements.txt", "LICENSE")

# The Windows fix: `pwd` is only used for an error message about a cache server
# Red doesn't use.
_PWD_IMPORT = "import os\nimport pwd\nimport logging\n"
_PWD_IMPORT_FIXED = ("import os\nimport logging\n\ntry:\n    import pwd  # Linux and macOS only\n"
                     "except ImportError:  # Windows (patched by Red)\n    pwd = None\n")
_PWD_USE = ("        _pw = pwd.getpwuid(os.getuid())\n"
            "        logger.exception(\"[%s (%s)] can't connect valkey DB ...\", _pw.pw_name, _pw.pw_uid)\n")
_PWD_USE_FIXED = ("        if pwd is not None:\n"
                  "            _pw = pwd.getpwuid(os.getuid())\n"
                  "            logger.exception(\"[%s (%s)] can't connect valkey DB ...\", _pw.pw_name, _pw.pw_uid)\n"
                  "        else:\n"
                  "            logger.exception(\"can't connect valkey DB ...\")\n")

SETTINGS_YML = """# Red's SearXNG: listens on this PC only, answers look_up in JSON.
# Written by Red each time it starts SearXNG (red/searxng.py); edits are overwritten.
#
# Only Google and Brave: measured on 2026-11-09, together they answer in about
# 0.3-0.7 s, where all the default engines took 2 s (SearXNG waits for the
# slowest). DuckDuckGo asked for a CAPTCHA, Bing's results were off-topic, and
# the translation and currency engines aren't web search.
use_default_settings:
  engines:
    keep_only:
      - google cse
      - brave

outgoing:
  request_timeout: 2.0        # an engine slower than this is left out of the answer

general:
  instance_name: "Red search"

server:
  bind_address: "127.0.0.1"
  secret_key: "{secret}"
  limiter: false
  image_proxy: false

search:
  safe_search: 1
  formats:
    - html
    - json

valkey:
  url: false
"""


class SearxngError(RuntimeError):
    pass


def install_dir(settings: Settings) -> Path:
    """One folder per pinned version, so an update never mixes old and new files."""
    return settings.home / "searxng" / f"red-{COMMIT[:12]}"


def _src(settings: Settings) -> Path:
    return install_dir(settings) / "src"


def _venv_python(settings: Settings) -> Path:
    return install_dir(settings) / "venv" / "Scripts" / "python.exe"


def _settings_file(settings: Settings) -> Path:
    return install_dir(settings) / "settings.yml"


def _marker(settings: Settings) -> Path:
    return install_dir(settings) / ".installed"


def installed(settings: Settings) -> bool:
    marker = _marker(settings)
    return (marker.is_file() and marker.read_text(encoding="utf-8").strip() == COMMIT
            and _venv_python(settings).is_file())


def _wanted(inner: str) -> bool:
    """A path inside the archive's top folder that SearXNG needs to run."""
    return any(inner.startswith(w) if w.endswith("/") else inner == w for w in WANTED)


def extract_needed(zip_path: Path, target: Path) -> None:
    """Unpack only the `searx` package, requirements.txt and LICENSE, safely."""
    target.mkdir(parents=True, exist_ok=True)
    root = target.resolve()
    with zipfile.ZipFile(zip_path) as zf:
        for member in zf.infolist():
            # Archive paths start with "searxng-<commit>/".
            _, _, inner = member.filename.partition("/")
            if not _wanted(inner):
                continue
            out = (root / inner).resolve()
            if not out.is_relative_to(root):
                raise SearxngError(f"unsafe path in the SearXNG archive: {member.filename!r}")
            if member.is_dir():
                out.mkdir(parents=True, exist_ok=True)
                continue
            out.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(member) as src, out.open("wb") as dst:
                shutil.copyfileobj(src, dst)


def patch_for_windows(src: Path) -> None:
    """Make `import pwd` optional. Already patched is fine; unknown code is an error."""
    path = src / "searx" / "valkeydb.py"
    text = path.read_text(encoding="utf-8")
    if _PWD_IMPORT_FIXED in text and _PWD_USE_FIXED in text:
        return
    if _PWD_IMPORT not in text or _PWD_USE not in text:
        raise SearxngError("SearXNG's valkeydb.py changed; the Windows fix needs updating.")
    text = text.replace(_PWD_IMPORT, _PWD_IMPORT_FIXED).replace(_PWD_USE, _PWD_USE_FIXED)
    path.write_text(text, encoding="utf-8")


def write_settings(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(SETTINGS_YML.format(secret=secrets.token_hex(32)), encoding="utf-8")


def install(settings: Settings, *, fetch: Callable = download, run: Callable = subprocess.run,
            python: str = sys.executable, say: Callable[[str], None] = print) -> None:
    """Download, unpack, fix, and set up SearXNG in its own venv. Safe to run again."""
    if installed(settings):
        say("Web search (SearXNG) is already installed.")
        return
    folder = install_dir(settings)
    if folder.exists():
        shutil.rmtree(folder)            # a half-finished install: start clean
    archive = settings.cache_dir / "downloads" / f"searxng-{COMMIT[:12]}.zip"
    say("Downloading web search (SearXNG, about 7 MB)...")
    fetch(ARCHIVE_URL, archive, ARCHIVE_SHA256, "SearXNG")
    extract_needed(archive, _src(settings))
    patch_for_windows(_src(settings))
    say("Installing its packages (about 30 MB)...")
    run([python, "-m", "venv", str(folder / "venv")], check=True)
    run([str(_venv_python(settings)), "-m", "pip", "install", "--disable-pip-version-check",
         "--quiet", "-r", str(_src(settings) / "requirements.txt")], check=True,
        env=child_env(PIP_CACHE_DIR=str(settings.cache_dir / "pip")))
    write_settings(_settings_file(settings))
    _marker(settings).write_text(COMMIT, encoding="utf-8")
    say("Web search is installed. Red starts it when Red starts (RED_WEB_SEARCH=off turns it off).")


def start(settings: Settings, *, server_factory: Callable = ManagedServer,
          port: Callable[[], int] = free_port) -> tuple[str, ManagedServer]:
    """Start Red's SearXNG on a free port; return its address and the server."""
    write_settings(_settings_file(settings))     # always this version's engines and timeouts
    chosen = port()
    env = child_env(SEARXNG_SETTINGS_PATH=str(_settings_file(settings)),
                    SEARXNG_PORT=str(chosen), SEARXNG_BIND_ADDRESS="127.0.0.1",
                    PYTHONPATH=str(_src(settings)), PYTHONIOENCODING="utf-8")
    url = f"http://127.0.0.1:{chosen}"
    server = server_factory("searxng", [str(_venv_python(settings)), "-m", "searx.webapp"],
                            f"{url}/healthz", settings.logs_dir / "searxng.log", env)
    server.start(timeout=START_TIMEOUT)
    return url, server


class WebSearch:
    """Red's SearXNG for this run: started in the background, stopped with Red."""

    def __init__(self, settings: Settings, starter: Callable | None = None,
                 environ: dict | None = None, opener: Callable | None = None):
        self._settings = settings
        self._starter = starter
        self._opener = opener or urllib.request.urlopen
        self._environ = os.environ if environ is None else environ
        self._server = None
        self._stopped = False
        self._lock = threading.Lock()
        self.thread: threading.Thread | None = None
        self.status = "off"

    def begin(self) -> bool:
        """Start it in the background if it should run. True if a start began."""
        if not self._settings.web_search:
            self.status = "off (RED_WEB_SEARCH=off)"
            return False
        if self._environ.get("RED_SEARCH_URL", "").strip():
            self.status = "using RED_SEARCH_URL"
            return False
        if not installed(self._settings):
            self.status = "not installed (run python -m red setup)"
            log.info("Web search isn't installed; answers use Wikipedia only. Run python -m red setup.")
            return False
        self.status = "starting"
        self.thread = threading.Thread(target=self._run, name="searxng-start", daemon=True)
        self.thread.start()
        return True

    def _run(self) -> None:
        try:
            # Looked up now, not at import, so tests can replace it (tests/conftest.py).
            url, server = (self._starter or start)(self._settings)
        except Exception as e:  # noqa: BLE001 - Red must keep working without it
            self.status = f"failed: {e}"
            log.warning("Web search didn't start, so answers use Wikipedia only: %s", e)
            return
        with self._lock:
            if self._stopped:            # Red quit while it was starting
                server.stop()
                return
            self._server = server
            self._environ["RED_SEARCH_URL"] = url
            self.status = f"running at {url}"
        log.info("Web search (SearXNG) is running at %s", url)
        self._warm(url)

    def _warm(self, url: str) -> None:
        """One throwaway search, so the engines' connections are open before the
        user's first question (the first search took 1.9 s, later ones 0.65 s)."""
        try:
            with self._opener(f"{url}/search?q=hello&format=json", timeout=WARM_TIMEOUT) as r:
                r.read(1)
        except Exception as e:  # noqa: BLE001 - only a head start; nothing depends on it
            log.info("Web search warm-up didn't finish: %s", e)

    def stop(self) -> None:
        with self._lock:
            self._stopped = True
            server, self._server = self._server, None
        if server is not None:
            server.stop()
            self._environ.pop("RED_SEARCH_URL", None)


__all__ = ["COMMIT", "DownloadError", "SearxngError", "WebSearch", "install", "installed", "start"]
