"""Other web sources for look_up, besides Wikipedia.

What was tried and left out, with reasons (checked live, 2026-11-09):
- DuckDuckGo instant answers: the abstract was Wikipedia's every time, so it
  adds no second source.
- arXiv: the abstracts were on unrelated topics ("Siri" gave an epidemic model,
  "Windows 11" a kernel-security paper). A small model would call that agreement.
- Wikidata: the top hit for "Siri" is a given name.

What is used: SearXNG, a free meta-search engine that runs on this PC. Red asks
it only when RED_SEARCH_URL is set to a loopback address (for example
http://127.0.0.1:8888) and its JSON output is switched on. It needs no account
and no key. SearXNG sends the search words to the engines it is set up with,
the same words that leave the PC today.

Each result is Evidence: a title, a short text, and the page's address. Gather
asks the sources at once, under a total time budget, and keeps what came back.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Callable
from urllib.parse import urlencode, urlsplit

from .base import ToolError
from .online import MAX_BYTES, TIMEOUT_SECONDS, USER_AGENT, Opener

log = logging.getLogger(__name__)

BUDGET_SECONDS = 4.0        # the most the look-up waits for the other sources in total
MAX_TEXT = 700              # characters per item, so the model's prompt stays small
MAX_RESULTS = 4             # web results used per look-up
LOOPBACK = {"127.0.0.1", "localhost"}

_STOP = {"the", "and", "for", "of", "what", "who", "is", "are", "how", "does", "tell", "me",
         "hey", "okay", "about", "a", "an", "in", "on", "to", "with", "look", "up", "search",
         "web", "you", "that", "this", "it", "its", "was", "were", "why", "when", "where", "which"}


@dataclass(frozen=True)
class Evidence:
    source: str        # the site the text came from, e.g. "britannica.com"
    title: str
    text: str
    url: str = ""


def topic_words(topic: str) -> list[str]:
    """The words that matter in a topic: letters and digits, no small or stop words."""
    words = re.findall(r"[a-z0-9]+", topic.lower())
    return list(dict.fromkeys(w for w in words if len(w) > 2 and w not in _STOP))


def _stem(word: str) -> str:
    """'assistants' and 'assistant' are the same word; 'bus' stays 'bus'."""
    return word[:-1] if len(word) > 3 and word.endswith("s") else word


def relevant(topic: str, *texts: str) -> bool:
    """Whole words of the topic appear in the texts: all of one or two words, half of more."""
    words = {_stem(w) for w in topic_words(topic)}
    if not words:
        return False
    seen = {_stem(w) for w in re.findall(r"[a-z0-9]+", " ".join(texts).lower())}
    needed = len(words) if len(words) <= 2 else (len(words) + 1) // 2
    return len(words & seen) >= needed


def _clip(text: str) -> str:
    text = " ".join(text.split())
    if len(text) <= MAX_TEXT:
        return text
    return text[:MAX_TEXT].rsplit(" ", 1)[0] + "…"


def search_url() -> str:
    """RED_SEARCH_URL, if it names a SearXNG on this PC; otherwise "" (no web search)."""
    value = os.environ.get("RED_SEARCH_URL", "").strip().rstrip("/")
    parts = urlsplit(value)
    if parts.scheme != "http" or parts.hostname not in LOOPBACK:
        return ""               # only this PC: no other server is ever asked
    return value


def searxng(topic: str, opener: Opener, base: str = "") -> list[Evidence]:
    """Web results for the topic from the local SearXNG, minus Wikipedia (already read)."""
    base = base or search_url()
    if not base:
        return []
    url = base + "/search?" + urlencode({"q": topic, "format": "json", "language": "en"})
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT,
                                               "Accept": "application/json"})
    with opener(req, timeout=TIMEOUT_SECONDS) as r:
        raw = r.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ToolError("The local search sent more than I can read.")
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise ToolError("The local search sent something I couldn't read.") from e
    found: list[Evidence] = []
    for result in (data.get("results") or []) if isinstance(data, dict) else []:
        if not isinstance(result, dict):
            continue
        link = str(result.get("url") or "")
        title = " ".join(str(result.get("title") or "").split())
        content = " ".join(str(result.get("content") or "").split())
        host = (urlsplit(link).hostname or "").removeprefix("www.")
        if not host or host.endswith("wikipedia.org") or not content:
            continue
        if not relevant(topic, title, content):
            continue
        found.append(Evidence(host, title or host, _clip(content), link))
        if len(found) >= MAX_RESULTS:
            break
    return found


# The sources a look-up asks, besides Wikipedia. Only the ones that are set up.
def default_sources() -> tuple[tuple[str, Callable[[str, Opener], list[Evidence]]], ...]:
    return (("the web", searxng),) if search_url() else ()


class Gather:
    """Asks every source at once. results() waits at most BUDGET_SECONDS in total."""

    def __init__(self, topic: str, opener: Opener, sources=None,
                 budget: float = BUDGET_SECONDS, clock: Callable[[], float] = time.monotonic):
        self._clock = clock
        self._deadline = clock() + budget
        sources = default_sources() if sources is None else sources
        self._pool = ThreadPoolExecutor(max_workers=max(1, len(sources)))
        self._futures = [(name, self._pool.submit(fn, topic, opener)) for name, fn in sources]

    def results(self) -> tuple[list[Evidence], list[str]]:
        """(the evidence, the names of the sources that gave some), in source order."""
        evidence: list[Evidence] = []
        used: list[str] = []
        for name, future in self._futures:
            try:
                items = future.result(timeout=max(0.0, self._deadline - self._clock()))
            except Exception as e:  # noqa: BLE001 - one source failing must not stop the others
                log.info("%s gave no evidence: %s", name, e)
                continue
            if items:
                evidence.extend(items)
                used.append(name)
        self._pool.shutdown(wait=False, cancel_futures=True)
        return evidence, used
