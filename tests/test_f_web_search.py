"""web_search builds a fixed URL with the query encoded. No browser opens."""

from urllib.parse import parse_qs, urlsplit

import pytest

from red.router import Router, RouteError
from red.tools import ToolRegistry
from red.tools.base import ToolError
from red.tools.web import WebSearch, search_url, web_engine


class FakeBrowser:
    def __init__(self, ok=True):
        self.ok, self.urls = ok, []

    def __call__(self, url):
        self.urls.append(url)
        return self.ok


def test_web_search_opens_an_encoded_google_url():
    browser = FakeBrowser()
    reply = WebSearch(browser, engine=lambda: "google").run(query="weather in  Pune")
    assert reply == "Searching the web for weather in Pune."
    assert browser.urls == ["https://www.google.com/search?q=weather+in+Pune"]


@pytest.mark.parametrize("query", [
    "c++ & rust?", "a=b&c=d#frag", "100% sure", "naïve café", "x\" onmouseover=\"y",
    "../../etc/passwd", "javascript:alert(1)",
])
def test_query_cannot_change_the_url(query):
    browser = FakeBrowser()
    WebSearch(browser, engine=lambda: "google").run(query=query)
    url = urlsplit(browser.urls[0])
    assert (url.scheme, url.netloc, url.path) == ("https", "www.google.com", "/search")
    assert parse_qs(url.query) == {"q": [" ".join(query.split())]}
    assert url.fragment == ""


@pytest.mark.parametrize("site, host, word", [
    ("youtube", "www.youtube.com", "YouTube"),
    ("images", "www.google.com", "images"),
    ("maps", "www.google.com", "maps"),
    ("news", "news.google.com", "the news"),
    ("wikipedia", "en.wikipedia.org", "Wikipedia"),
])
def test_sites(site, host, word):
    browser = FakeBrowser()
    reply = WebSearch(browser).run(query="lofi beats", site=site)
    assert urlsplit(browser.urls[0]).netloc == host
    assert "lofi+beats" in browser.urls[0]
    assert reply == f"Searching {word} for lofi beats."


@pytest.mark.parametrize("engine, host", [("bing", "www.bing.com"),
                                          ("duckduckgo", "duckduckgo.com")])
def test_engine_setting(monkeypatch, engine, host):
    monkeypatch.setenv("RED_SEARCH_ENGINE", engine.upper())
    assert web_engine() == engine
    assert urlsplit(search_url("x", engine=web_engine())).netloc == host


def test_unknown_engine_falls_back_to_google(monkeypatch):
    monkeypatch.setenv("RED_SEARCH_ENGINE", "evil.example")
    assert web_engine() == "google"


def test_browser_failure():
    with pytest.raises(ToolError, match="couldn't open the browser"):
        WebSearch(FakeBrowser(ok=False)).run(query="x")


def test_schema_limits():
    router = Router(ToolRegistry([WebSearch(FakeBrowser())]))
    router.parse('{"tool": "web_search", "args": {"query": "x", "site": "youtube"}}')
    for bad in ('{"tool": "web_search", "args": {"query": ""}}',
                '{"tool": "web_search", "args": {"query": "x", "site": "evil"}}',
                '{"tool": "web_search", "args": {"query": "x", "url": "https://e.vil"}}',
                '{"tool": "web_search", "args": {"query": "%s"}}' % ("x" * 301)):
        with pytest.raises(RouteError):
            router.parse(bad)
