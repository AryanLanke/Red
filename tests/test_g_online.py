"""Online answers with a fake opener: no network. RED_ONLINE=1 runs one live check."""

import io
import re
import json
import os
import socket
import urllib.error
from urllib.parse import parse_qs, urlsplit

import pytest

from red.tools import default_registry
from red.tools.base import ToolError
from red.tools.online import (MAX_BYTES, LookUp, News, Offline, Weather, fetch, news_edition)


class FakeOpener:
    """Maps a URL prefix to a response body (bytes, str, dict) or an exception."""

    def __init__(self, routes):
        self.routes, self.requests = routes, []

    def __call__(self, req, timeout):
        url = req.full_url
        self.requests.append((url, timeout, dict(req.header_items())))
        for prefix, body in self.routes.items():
            if url.startswith(prefix):
                if isinstance(body, Exception):
                    raise body
                if isinstance(body, (dict, list)):
                    body = json.dumps(body)
                if isinstance(body, str):
                    body = body.encode()
                return io.BytesIO(body)
        raise AssertionError(f"unexpected URL {url}")

    def query(self, i):
        return {k: v[0] for k, v in parse_qs(urlsplit(self.requests[i][0]).query).items()}


GEO = {"results": [{"name": "Pune", "latitude": 18.52, "longitude": 73.86, "country": "India"}]}
FORECAST = {
    "current": {"temperature_2m": 27.4, "apparent_temperature": 29.1, "weather_code": 2,
                "wind_speed_10m": 8},
    "daily": {"weather_code": [2, 61], "temperature_2m_max": [31.2, 29.6],
              "temperature_2m_min": [18.7, 19.4], "precipitation_probability_max": [10, 70]},
}


def weather_opener(geo=GEO, forecast=FORECAST):
    return FakeOpener({"https://geocoding-api.open-meteo.com/": geo,
                       "https://api.open-meteo.com/": forecast})


def test_weather_now():
    opener = weather_opener()
    reply = Weather(opener, home=lambda: "").run(place="Pune")
    assert reply == ("In Pune it's 27 degrees and partly cloudy, feeling like 29. Today's high "
                     "is 31 and the low is 19, with a 10 percent chance of rain.")
    assert opener.query(0)["name"] == "Pune"
    assert opener.query(1)["latitude"] == "18.52"


def test_weather_tomorrow():
    reply = Weather(weather_opener(), home=lambda: "").run(place="Pune", day="tomorrow")
    assert reply == ("Tomorrow in Pune: light rain, a high of 30 and a low of 19 degrees, "
                     "with a 70 percent chance of rain.")


def test_weather_home_city_and_missing_city():
    opener = weather_opener()
    Weather(opener, home=lambda: "Mumbai").run(place="here")
    assert opener.query(0)["name"] == "Mumbai"
    with pytest.raises(ToolError, match="Which city"):
        Weather(weather_opener(), home=lambda: "").run()


def test_weather_unknown_place():
    with pytest.raises(ToolError, match="couldn't find a place called Atlantis"):
        Weather(weather_opener(geo={}), home=lambda: "").run(place="Atlantis")


def test_weather_bad_data():
    with pytest.raises(ToolError, match="couldn't read"):
        Weather(weather_opener(forecast={"current": {}}), home=lambda: "").run(place="Pune")


@pytest.mark.parametrize("place", ["Pune&latitude=0", "x/../../etc", "a#b", "São Paulo"])
def test_weather_place_is_only_a_query_value(place):
    opener = weather_opener()
    Weather(opener, home=lambda: "").run(place=place)
    url = urlsplit(opener.requests[0][0])
    assert (url.scheme, url.netloc, url.path) == ("https", "geocoding-api.open-meteo.com",
                                                  "/v1/search")
    assert opener.query(0)["name"] == place and url.fragment == ""


# --- errors shared by every online tool --------------------------------------------

@pytest.mark.parametrize("error, message, offline", [
    (urllib.error.URLError(socket.gaierror(11001, "getaddrinfo failed")), "I'm offline", True),
    (urllib.error.URLError(ConnectionRefusedError()), "I'm offline", True),
    (urllib.error.URLError(socket.timeout("timed out")), "didn't answer in time", False),
    (TimeoutError(), "didn't answer in time", False),
    (urllib.error.HTTPError("https://x", 503, "busy", {}, None), "returned an error (503)", False),
])
def test_network_errors_become_spoken_replies(error, message, offline):
    opener = FakeOpener({"https://": error})
    with pytest.raises(ToolError, match=re.escape(message)) as info:
        Weather(opener, home=lambda: "").run(place="Pune")
    assert isinstance(info.value, Offline) == offline


def test_fetch_uses_a_time_limit_and_user_agent():
    opener = FakeOpener({"https://": b"{}"})
    fetch("https://example.org/x", "test", opener)
    _, timeout, headers = opener.requests[0]
    assert 0 < timeout <= 10
    assert headers["User-agent"].startswith("Red/")


def test_fetch_refuses_plain_http_and_huge_replies():
    with pytest.raises(ValueError):
        fetch("http://example.org", "test", FakeOpener({}))
    with pytest.raises(ToolError, match="more than I can read"):
        fetch("https://example.org", "test", FakeOpener({"https://": b"x" * (MAX_BYTES + 1)}))


# --- Wikipedia ----------------------------------------------------------------------

SEARCH = ["hugging face", ["Hugging Face"], [""], ["https://en.wikipedia.org/wiki/Hugging_Face"]]
SUMMARY = {"type": "standard", "title": "Hugging Face",
           "extract": "Hugging Face, Inc. is an American company that develops tools for "
                      "building applications using machine learning. It is known for its "
                      "transformers library. It also runs a platform for sharing models.",
           "content_urls": {"desktop": {"page": "https://en.wikipedia.org/wiki/Hugging_Face"}}}


def wiki_opener(search=SEARCH, summary=SUMMARY):
    return FakeOpener({"https://en.wikipedia.org/w/api.php": search,
                       "https://en.wikipedia.org/api/rest_v1/page/summary/": summary})


class FakeLLM:
    def __init__(self, answer):
        self.answer, self.calls = answer, []

    def complete_json(self, system, user, schema):
        self.calls.append((system, user))
        return json.dumps({"answer": self.answer})


def test_look_up_summarises_with_the_local_model():
    llm = FakeLLM("Hugging Face is an American AI company. It makes the transformers library.")
    opener = wiki_opener()
    tool = LookUp(llm, opener)
    reply = tool.run(topic="hugging face", question="what does hugging face do")
    assert reply == ("From Wikipedia: Hugging Face is an American AI company. It makes the "
                     "transformers library.")
    system, user = llm.calls[0]
    assert "Using only the Wikipedia text" in system
    assert "what does hugging face do" in user and "transformers library" in user
    assert opener.requests[1][0].endswith("/page/summary/Hugging_Face")
    assert tool.last_details.splitlines() == ["Wikipedia: Hugging Face",
                                              "https://en.wikipedia.org/wiki/Hugging_Face"]


def test_look_up_without_a_model_reads_the_first_sentences():
    reply = LookUp(None, wiki_opener()).run(topic="hugging face")
    assert reply.startswith("From Wikipedia: Hugging Face, Inc. is an American company")


def test_look_up_bound_through_the_router():
    from red.router import Router
    from red.tools import ToolRegistry
    tool = LookUp(opener=wiki_opener())
    Router(ToolRegistry([tool]), FakeLLM("Bound."))
    assert tool.run(topic="x") == "From Wikipedia: Bound."


def test_look_up_nothing_found_and_disambiguation():
    with pytest.raises(ToolError, match="Wikipedia has nothing on zzqx"):
        LookUp(None, wiki_opener(search=["zzqx", [], [], []])).run(topic="zzqx")
    reply = LookUp(None, wiki_opener(summary={"type": "disambiguation", "title": "Mercury",
                                              "extract": "Mercury may refer to:"})).run(
        topic="mercury")
    assert reply == "Hugging Face can mean several things. Try saying which one you mean."


def test_look_up_title_is_encoded_in_the_path():
    opener = wiki_opener(search=["x", ["AC/DC?#"], [], []])
    LookUp(None, opener).run(topic="acdc")
    assert opener.requests[1][0].endswith("/page/summary/AC%2FDC%3F%23")


def test_look_up_offline():
    opener = FakeOpener({"https://": urllib.error.URLError(socket.gaierror())})
    with pytest.raises(Offline, match="can't reach Wikipedia"):
        LookUp(None, opener).run(topic="x")


# --- News ---------------------------------------------------------------------------

RSS = """<?xml version="1.0"?><rss><channel>
<item><title>Rain lashes Pune - Times of India</title><source>Times of India</source>
<link>https://news.example/1</link></item>
<item><title>Markets close higher - Mint</title><source>Mint</source><link>https://n/2</link></item>
<item><title>New metro line opens</title><link>https://n/3</link></item>
<item><title>Fourth story - BBC</title><source>BBC</source></item>
</channel></rss>"""


def test_news_reads_three_headlines():
    opener = FakeOpener({"https://news.google.com/rss": RSS})
    tool = News(opener, edition=lambda: ("IN", "en"))
    reply = tool.run(topic="Pune")
    assert reply == ("Here are the latest headlines about Pune: Rain lashes Pune, from Times "
                     "of India; Markets close higher, from Mint; New metro line opens.")
    assert opener.query(0) == {"q": "Pune", "hl": "en-IN", "gl": "IN", "ceid": "IN:en"}
    assert len(tool.last_details.splitlines()) == 4


def test_top_news_without_a_topic():
    opener = FakeOpener({"https://news.google.com/rss": RSS})
    assert News(opener).run(topic="latest").startswith("Here are the latest headlines: ")
    assert urlsplit(opener.requests[0][0]).path == "/rss"


def test_news_empty_and_broken_feeds():
    empty = FakeOpener({"https://news.google.com/rss": "<rss><channel/></rss>"})
    assert News(empty).run(topic="x") == "I didn't find any news about x."
    broken = FakeOpener({"https://news.google.com/rss": "<rss"})
    with pytest.raises(ToolError, match="couldn't read"):
        News(broken).run()


def test_news_edition(monkeypatch):
    monkeypatch.setenv("RED_NEWS_EDITION", "in:EN")
    assert news_edition() == ("IN", "en")
    monkeypatch.setenv("RED_NEWS_EDITION", "evil&x=1")
    assert news_edition() == ("US", "en")


def test_online_tools_are_registered_and_read_only():
    reg = default_registry()
    for name in ("weather", "look_up", "news"):
        assert name in reg and reg.get(name).destructive is False


@pytest.mark.skipif(os.environ.get("RED_ONLINE") != "1", reason="set RED_ONLINE=1 to use the network")
def test_live_sources():
    assert "Pune" in Weather(home=lambda: "").run(place="Pune")
    assert LookUp(None).run(topic="Alan Turing").startswith("From Wikipedia:")
    assert News().run(topic="technology").startswith("Here are the latest headlines")
