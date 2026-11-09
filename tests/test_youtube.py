"""play_online: YouTube results parsing (from a saved page, never the live site) and the hand-over from play_music."""

import io
import socket
from pathlib import Path

import pytest

from red.tools import default_registry
from red.tools.base import ToolError
from red.tools.music import Library, PlayMusic
from red.tools.youtube import (BROWSER_AGENT, PlayOnline, Video, fetch_results, first_video,
                               search_url, spoken_title)

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


# --- play_music hands over --------------------------------------------------------

class Online:
    def __init__(self):
        self.queries = []

    def run(self, query):
        self.queries.append(query)
        return f"Playing {query} on YouTube."

    def take_later(self):
        return None


class NoPlayer:
    current, paused = None, False

    def play(self, tracks):
        from red.tools.music import PlayerError
        raise PlayerError("pygame-ce isn't installed")


def test_no_local_match_plays_online_instead(tmp_path):
    root = tmp_path / "Music"
    root.mkdir()
    (root / "Daft Punk - Get Lucky.mp3").write_bytes(b"")
    online = Online()
    reply = PlayMusic(NoPlayer(), Library(root), online=online).run(query="podcast about loneliness")
    assert online.queries == ["podcast about loneliness"]
    assert reply == "Playing podcast about loneliness on YouTube."


def test_podcasts_and_videos_never_play_a_local_song(tmp_path):
    root = tmp_path / "Music"
    root.mkdir()
    (root / "Loneliness.mp3").write_bytes(b"")       # would match "loneliness"
    online = Online()
    music = PlayMusic(NoPlayer(), Library(root), online=online)
    music.run(query="podcast about loneliness")
    music.run(query="Punisher trailer")
    assert online.queries == ["podcast about loneliness", "Punisher trailer"]


def test_an_empty_music_folder_plays_online(tmp_path):
    # 22:26 in the log: "There's no music I can play in C:\\Users\\aryan\\Music."
    online = Online()
    PlayMusic(NoPlayer(), folder=lambda: tmp_path, online=online).run(query="podcast")
    PlayMusic(NoPlayer(), folder=lambda: tmp_path / "missing", online=online).run()
    assert online.queries == ["podcast", "music"]


def test_a_player_that_cant_start_plays_online(tmp_path):
    root = tmp_path / "Music"
    root.mkdir()
    (root / "Get Lucky.mp3").write_bytes(b"")
    online = Online()
    PlayMusic(NoPlayer(), Library(root), online=online).run(query="get lucky")
    assert online.queries == ["get lucky"]


def test_the_default_registry_wires_play_music_to_play_online():
    registry = default_registry()
    assert registry.get("play_music")._online is registry.get("play_online")
    assert not registry.get("play_online").destructive
