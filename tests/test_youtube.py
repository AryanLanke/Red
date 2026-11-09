"""play_online: YouTube results parsing (from a saved page, never the live site), and every "play ..." going online."""

import io
import socket
from pathlib import Path

import pytest

from red.tools import default_registry
from red.tools.base import ToolError
from fakes import FakePopen
from red import browser as b
from red.tools.youtube import (ANYTHING_QUERY, BROWSER_AGENT, PlayOnline, Video, fetch_results,
                               first_video, search_url, search_words, spoken_title)

FIXTURE = Path(__file__).parent / "fixtures" / "youtube_results.html"
PAGE = FIXTURE.read_text(encoding="utf-8")


def test_first_video_skips_shorts_and_reads_the_title():
    video = first_video(PAGE)
    assert video.id == "ypAHnzD04rg"                            # not the Short before it
    assert video.title.startswith("Practical Solutions to Deal with Loneliness - Biggest Problem & Scary")
    assert video.url == "https://www.youtube.com/watch?v=ypAHnzD04rg"


def test_a_page_with_no_videos():
    assert first_video("<html>Your search didn't match anything</html>") is None


def test_a_bare_video_id_still_works():
    assert first_video('{"videoId":"abcdefghijk"}') == Video("abcdefghijk")


def test_a_bad_id_never_becomes_a_url():
    with pytest.raises(ValueError):
        Video("x&list=1;rm").url


@pytest.mark.parametrize("title, said", [
    ("Practical Solutions to Deal with Loneliness | Dr. P Kohli | TRS", "Practical Solutions to Deal with Loneliness"),
    ("The Punisher | Official Trailer | Netflix", "The Punisher"),
    ("lofi hip hop radio - beats to relax/study to #lofi #chill", "lofi hip hop radio - beats to relax/study to"),
    ("A " + "very " * 30 + "long title", "A " + ("very " * 15).strip() + "..."),
    ("\U0001F4DA Lofi to study ☕️ | beats", "Lofi to study"),
])
def test_spoken_title(title, said):
    assert spoken_title(title) == said


def test_search_url_encodes_the_words():
    assert search_url("podcast about  loneliness & me") == \
        "https://www.youtube.com/results?search_query=podcast+about+loneliness+%26+me"


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def test_fetch_results_reads_until_the_first_video():
    seen = {}
    big = ("x" * 900_000 + PAGE + "y" * 900_000).encode()

    def opener(req, timeout):
        seen["url"], seen["agent"], seen["timeout"] = req.full_url, req.get_header("User-agent"), timeout
        seen["response"] = FakeResponse(big)
        return seen["response"]

    video = fetch_results("podcast about loneliness", opener=opener)
    assert video.id == "ypAHnzD04rg"
    assert seen["url"] == "https://www.youtube.com/results?search_query=podcast+about+loneliness"
    assert seen["agent"] == BROWSER_AGENT and seen["timeout"] == 6.0


class Browser:
    def __init__(self, ok=True):
        self.opened, self.ok = [], ok

    def __call__(self, url):
        self.opened.append(url)
        return self.ok


def test_play_online_starts_the_first_video():
    browser = Browser()
    tool = PlayOnline(open_browser=browser, find=lambda q: first_video(PAGE))
    reply = tool.run(query="podcast about loneliness")
    assert browser.opened == ["https://www.youtube.com/watch?v=ypAHnzD04rg"]
    assert reply == "Playing Practical Solutions to Deal with Loneliness - Biggest Problem & Scary Truth on YouTube."


@pytest.mark.parametrize("error", [OSError("offline"), socket.timeout("slow"), ValueError("odd page")])
def test_play_online_opens_the_search_when_youtube_cant_be_read(error):
    browser = Browser()

    def find(q):
        raise error
    reply = PlayOnline(open_browser=browser, find=find).run(query="Punisher trailer")
    assert browser.opened == ["https://www.youtube.com/results?search_query=Punisher+trailer"]
    assert "search for Punisher trailer" in reply


def test_play_online_with_no_result_opens_the_search():
    browser = Browser()
    reply = PlayOnline(open_browser=browser, find=lambda q: None).run(query="zzzz")
    assert browser.opened == [search_url("zzzz")] and "search" in reply


def test_play_online_says_when_the_browser_wont_open():
    with pytest.raises(ToolError):
        PlayOnline(open_browser=Browser(ok=False), find=lambda q: first_video(PAGE)).run(query="lofi")


def test_play_online_needs_words():
    with pytest.raises(ToolError):
        PlayOnline(open_browser=Browser(), find=lambda q: None).run(query="   ")


# --- every "play ..." goes online (plan.md task 3, second plan) -------------------------

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"


def test_a_song_plays_on_youtube_in_chrome():
    popen, found = FakePopen(), []
    browsers = b.Browsers(read={"chrome.exe": CHROME}.get, exists=lambda p: True, popen=popen,
                          setting=lambda: "chrome")

    def find(query):
        found.append(query)
        return Video("7wtfhZwyrcc", "Imagine Dragons - Believer (Official Music Video)")
    reply = PlayOnline(find=find, browsers=browsers).run(query="Believer")
    assert reply == "Playing Imagine Dragons - Believer (Official Music Video) on YouTube."
    assert found == ["Believer"]
    assert popen.calls[0][0] == [CHROME, "https://www.youtube.com/watch?v=7wtfhZwyrcc"]


def test_play_online_fronts_the_window_showing_youtube():
    targets = []

    def watch(target):
        targets.append(target)
        return lambda: True
    browsers = b.Browsers(default_open=lambda url: True, read={"chrome.exe": CHROME}.get,
                          exists=lambda p: True, popen=FakePopen(), setting=lambda: "chrome")
    PlayOnline(find=lambda q: Video("abcdefghijk", "x"), watch=watch, browsers=browsers).run(query="x")
    assert targets[0].exes == frozenset({"chrome.exe"}) and targets[0].titles == ("youtube",)


@pytest.mark.parametrize("said, query", [
    ("music", ANYTHING_QUERY), ("some music", ANYTHING_QUERY), ("anything", ANYTHING_QUERY),
    ("songs", ANYTHING_QUERY), ("all my songs", ANYTHING_QUERY),
    ("Arijit Singh songs", "Arijit Singh songs"), ("Believer", "Believer"),
    ("  lofi   music ", "lofi music"),
])
def test_play_anything_starts_a_mix(said, query):
    assert search_words(said) == query


def test_play_online_is_harmless():
    assert not default_registry().get("play_online").destructive
