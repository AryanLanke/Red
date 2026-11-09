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
from concurrent.futures import TimeoutError as FuturesTimeout
from concurrent.futures import as_completed
from dataclasses import dataclass, replace
from functools import partial
from html.parser import HTMLParser
from typing import Callable
from urllib.parse import unquote, urlencode, urlsplit

from .base import ToolError
from .online import MAX_BYTES, TIMEOUT_SECONDS, USER_AGENT, Opener, fetch_json

log = logging.getLogger(__name__)

BUDGET_SECONDS = 6.0        # the most the look-up waits for the other sources in total
MAX_TEXT = 700              # characters per snippet, so the model's prompt stays small
MAX_RESULTS = 4             # web results used per look-up
READ_PAGES = 3              # the top results whose pages are read, not just their snippets
READ_ENOUGH = 2             # stop waiting once this many pages gave good text
PAGE_SECONDS = 1.5          # the most the page reading waits, all pages together (most took 0.2-0.6 s)
MAX_PASSAGES = 1100         # characters kept from each page: the paragraphs that fit the question
MAX_PAGE_BYTES = 1_500_000
MIN_CONTENT = 40            # a snippet shorter than this says nothing ("Sign in")
LOOPBACK = {"127.0.0.1", "localhost"}
# Videos, photos and social posts: their snippets are titles and chatter, not facts.
SKIP_SITES = {"youtube.com", "youtu.be", "flickr.com", "x.com", "twitter.com", "facebook.com",
              "instagram.com", "tiktok.com", "pinterest.com", "reddit.com"}

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


def site_of(host: str) -> str:
    """The website a host belongs to: 'support.microsoft.com' -> 'microsoft.com'."""
    parts = host.lower().removeprefix("www.").split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else host.lower()


def search_url() -> str:
    """RED_SEARCH_URL, if it names a SearXNG on this PC; otherwise "" (no web search)."""
    value = os.environ.get("RED_SEARCH_URL", "").strip().rstrip("/")
    parts = urlsplit(value)
    if parts.scheme != "http" or parts.hostname not in LOOPBACK:
        return ""               # only this PC: no other server is ever asked
    return value


def searxng(topic: str, opener: Opener, base: str = "", query: str = "",
            read_pages: bool = True) -> list[Evidence]:
    """Web results from the local SearXNG, in the search engines' ranking order.

    `query` is what is searched: the user's own question ("who made Siri") finds
    better pages than the bare topic ("Siri"). `topic` decides which results are
    relevant. Wikipedia keeps its place in the ranking like any other site. The
    top pages are then read, so the model sees the paragraphs that answer the
    question, not just the two-line snippet.
    """
    base = base or search_url()
    if not base:
        return []
    query = " ".join((query or topic).split())[:300]
    url = base + "/search?" + urlencode({"q": query, "format": "json", "language": "en"})
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
    sites: set[str] = set()                  # one page per website: four microsoft.com pages are one source
    for result in (data.get("results") or []) if isinstance(data, dict) else []:
        if not isinstance(result, dict):
            continue
        link = str(result.get("url") or "")
        title = " ".join(str(result.get("title") or "").split())
        content = " ".join(str(result.get("content") or "").split())
        host = (urlsplit(link).hostname or "").removeprefix("www.")
        site = site_of(host) if host else ""
        if not host or site in SKIP_SITES or site in sites:
            continue
        if len(content) < MIN_CONTENT or not relevant(topic, title, content):
            continue
        sites.add(site)
        name = "Wikipedia" if site == "wikipedia.org" else host
        found.append(Evidence(name, title or host, _clip(content), link))
        if len(found) >= MAX_RESULTS:
            break
    if read_pages and found:
        found = read_top_pages(found, query, opener)
    return found


# --- reading the pages themselves ---------------------------------------------------

class _PageText(HTMLParser):
    """The readable paragraphs of a page: no scripts, menus, headers or footers."""

    SKIP = {"script", "style", "noscript", "nav", "header", "footer", "aside", "form",
            "svg", "button", "select", "template", "iframe"}
    KEEP = {"p", "li", "h1", "h2", "h3", "td", "blockquote", "dd"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.skip = 0
        self.inside = 0
        self.buffer: list[str] = []
        self.paragraphs: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip += 1
        elif tag in self.KEEP:
            self._flush()
            self.inside += 1

    def handle_endtag(self, tag):
        if tag in self.SKIP:
            self.skip = max(0, self.skip - 1)
        elif tag in self.KEEP:
            self._flush()
            self.inside = max(0, self.inside - 1)

    def handle_data(self, data):
        if not self.skip and self.inside:
            self.buffer.append(data)

    def _flush(self):
        text = " ".join("".join(self.buffer).split())
        self.buffer = []
        if len(text) >= 40:
            self.paragraphs.append(text)

    def close(self):
        super().close()
        self._flush()


def page_paragraphs(html: str) -> list[str]:
    parser = _PageText()
    try:
        parser.feed(html)
        parser.close()
    except Exception:  # noqa: BLE001 - a broken page gives what was read so far
        pass
    return list(dict.fromkeys(parser.paragraphs))       # menus repeat; keep each once


def best_passages(paragraphs: list[str], query: str, limit: int = MAX_PASSAGES) -> str:
    """The paragraphs that share the most words with the question, in page order."""
    words = {_stem(w) for w in topic_words(query)}
    if not words or not paragraphs:
        return ""
    scored = []
    for i, text in enumerate(paragraphs):
        seen = {_stem(w) for w in re.findall(r"[a-z0-9]+", text.lower())}
        score = len(words & seen)
        if score:
            scored.append((-score, i, text))
    chosen, size = [], 0
    for _, i, text in sorted(scored):
        if size + len(text) > limit:
            if not chosen:          # one long paragraph: keep its start
                chosen.append((i, _cut(text, limit)))
            break
        chosen.append((i, text))
        size += len(text) + 1
    return " ".join(text for _, text in sorted(chosen))


def _cut(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0] + "…"


def fetch_page(url: str, opener: Opener) -> str:
    """A web page's HTML, or "" when it isn't an https HTML page that loads in time."""
    if not url.startswith("https://"):
        return ""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT,
                                               "Accept": "text/html,application/xhtml+xml"})
    with opener(req, timeout=PAGE_SECONDS) as r:
        headers = getattr(r, "headers", None)
        kind = headers.get("Content-Type", "") if headers is not None else "text/html"
        if "html" not in kind.lower():
            return ""
        raw = r.read(MAX_PAGE_BYTES)
        charset = headers.get_content_charset() if hasattr(headers, "get_content_charset") else None
    return raw.decode(charset or "utf-8", errors="replace")


WIKI_TEXT_URL = "https://en.wikipedia.org/w/api.php?"


def wikipedia_paragraphs(url: str, opener: Opener) -> list[str]:
    """A Wikipedia article as plain-text paragraphs, from its API.

    Its web page is often over 1 MB of HTML and took 1.1-2.7 s to load
    (2026-11-09); the same text from the API is a fraction of that.
    """
    path = urlsplit(url).path
    if not path.startswith("/wiki/"):
        return []
    title = unquote(path[len("/wiki/"):]).replace("_", " ")
    data = fetch_json(WIKI_TEXT_URL + urlencode({
        "action": "query", "prop": "extracts", "explaintext": 1, "redirects": 1,
        "titles": title, "format": "json", "formatversion": 2}), "Wikipedia", opener)
    pages = data.get("query", {}).get("pages", []) if isinstance(data, dict) else []
    text = str(pages[0].get("extract", "")) if pages else ""
    return [p for p in (" ".join(line.split()) for line in text.splitlines())
            if len(p) >= 40 and not p.startswith("==")]


def read_paragraphs(item: Evidence, opener: Opener) -> list[str]:
    """The readable paragraphs behind one search result."""
    if item.source == "Wikipedia" and urlsplit(item.url).hostname == "en.wikipedia.org":
        return wikipedia_paragraphs(item.url, opener)
    return page_paragraphs(fetch_page(item.url, opener))


def read_top_pages(found: list[Evidence], query: str, opener: Opener,
                   budget: float = PAGE_SECONDS) -> list[Evidence]:
    """The same evidence, with the top pages' best paragraphs in place of their snippets.

    Pages are read side by side. Once the best-ranked page is in and READ_ENOUGH
    of them gave good text, the rest aren't waited for: one slow lower site no
    longer holds up the answer.
    A page that is slow, blocked or not HTML keeps its snippet, so this can only
    add to what the model sees.
    """
    top = found[:READ_PAGES]
    pool = ThreadPoolExecutor(max_workers=len(top))
    futures = {pool.submit(read_paragraphs, item, opener): i for i, item in enumerate(top)}
    texts: dict[int, str] = {}
    done: set[int] = set()
    try:
        for future in as_completed(futures, timeout=budget):
            i = futures[future]
            done.add(i)
            if future.exception() is None:
                text = best_passages(future.result(), query)
                if len(text) >= 100:
                    texts[i] = text
            # The best-ranked page is always waited for (within the budget): two
            # fast lower pages must not answer without it.
            if 0 in done and len(texts) >= READ_ENOUGH:
                break
    except FuturesTimeout:
        pass                          # the budget is spent: keep what came back
    pool.shutdown(wait=False, cancel_futures=True)
    better = [replace(item, text=texts[i]) if i in texts else item for i, item in enumerate(top)]
    return better + found[READ_PAGES:]


# The sources a look-up asks, besides Wikipedia. Only the ones that are set up.
def default_sources(query: str = "") -> tuple[tuple[str, Callable[[str, Opener], list[Evidence]]], ...]:
    if not search_url():
        return ()
    return (("the web", partial(searxng, query=query)),)


class Gather:
    """Asks every source at once. results() waits at most BUDGET_SECONDS in total."""

    def __init__(self, topic: str, opener: Opener, sources=None,
                 budget: float = BUDGET_SECONDS, clock: Callable[[], float] = time.monotonic):
        self._clock = clock
        self._deadline = clock() + budget
        sources = default_sources() if sources is None else sources
        self._pool = ThreadPoolExecutor(max_workers=max(1, len(sources)))
        self._futures = [(name, self._pool.submit(fn, topic, opener)) for name, fn in sources]

    @property
    def asking(self) -> bool:
        """True when at least one source was asked (the web search is set up)."""
        return bool(self._futures)

    def cancel(self) -> None:
        """Stop waiting: the look-up failed before the answers were needed."""
        self._pool.shutdown(wait=False, cancel_futures=True)

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
