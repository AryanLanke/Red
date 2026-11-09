"""Online answers from public, keyless HTTPS sources.

- weather: Open-Meteo (geocoding, then the forecast). The reply is built from
  the numbers directly, so the model can't change them.
- look_up: Wikipedia (search, then the page summary), summarised by the local
  model in 2 or 3 sentences, and credited to Wikipedia.
- news: Google News RSS headlines, read as written.

Every request goes to a fixed https:// URL with the user's words encoded as one
query parameter, with a time limit and a size cap. With no network Red says it's
offline. Only the search words leave the PC; nothing else is sent.
"""

from __future__ import annotations

import json
import os
import socket
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from typing import Callable
from urllib.parse import quote, urlencode

from .assistant import _UsesLLM, ask_model, spoken
from .base import Tool, ToolError

TIMEOUT_SECONDS = 6.0
MAX_BYTES = 1_000_000
USER_AGENT = "Red/0.1 (local voice assistant; https://github.com/AryanLanke/Red)"

Opener = Callable[..., object]


class Offline(ToolError):
    pass


def fetch(url: str, source: str, opener: Opener = urllib.request.urlopen,
          timeout: float = TIMEOUT_SECONDS) -> bytes:
    """GET an https URL. Raises a ToolError fit to say aloud."""
    if not url.startswith("https://"):
        raise ValueError("only https URLs")
    name = source[:1].upper() + source[1:]
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT,
                                               "Accept": "application/json, application/xml"})
    try:
        with opener(req, timeout=timeout) as r:
            data = r.read(MAX_BYTES + 1)
    except urllib.error.HTTPError as e:
        raise ToolError(f"{name} returned an error ({e.code}).") from e
    except urllib.error.URLError as e:
        reason = e.reason
        if isinstance(reason, (TimeoutError, socket.timeout)):
            raise ToolError(f"{name} didn't answer in time.") from e
        raise Offline(f"I'm offline, so I can't reach {source} right now.") from e
    except (TimeoutError, socket.timeout) as e:
        raise ToolError(f"{name} didn't answer in time.") from e
    except OSError as e:
        raise Offline(f"I'm offline, so I can't reach {source} right now.") from e
    if len(data) > MAX_BYTES:
        raise ToolError(f"{name} sent more than I can read.")
    return data


def fetch_json(url: str, source: str, opener: Opener = urllib.request.urlopen) -> dict:
    try:
        return json.loads(fetch(url, source, opener).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise ToolError(f"{source[:1].upper() + source[1:]} sent something I couldn't read.") from e


# --------------------------------------------------------------------------
# Weather (Open-Meteo)
# --------------------------------------------------------------------------

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search?"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast?"

# WMO weather interpretation codes, as Open-Meteo documents them.
WEATHER_CODES = {
    0: "clear", 1: "mostly clear", 2: "partly cloudy", 3: "overcast",
    45: "foggy", 48: "foggy with frost",
    51: "light drizzle", 53: "drizzle", 55: "heavy drizzle",
    56: "freezing drizzle", 57: "heavy freezing drizzle",
    61: "light rain", 63: "rain", 65: "heavy rain", 66: "freezing rain", 67: "heavy freezing rain",
    71: "light snow", 73: "snow", 75: "heavy snow", 77: "snow grains",
    80: "light showers", 81: "showers", 82: "violent showers",
    85: "snow showers", 86: "heavy snow showers",
    95: "thunderstorms", 96: "thunderstorms with hail", 99: "thunderstorms with heavy hail",
}


def default_place() -> str:
    return os.environ.get("RED_WEATHER_PLACE", "").strip()


def _num(x) -> int:
    return int(round(float(x)))


class Weather(Tool):
    name = "weather"
    description = ("Get the live weather or forecast for a city from the internet, for "
                   "example 'what's the weather in Pune' or 'will it rain tomorrow'.")
    args_schema = {
        "type": "object",
        "properties": {
            "place": {"type": "string", "minLength": 1, "maxLength": 100,
                      "description": "City name, only if the user said one."},
            "day": {"type": "string", "enum": ["now", "today", "tomorrow"]},
        },
        "additionalProperties": False,
    }

    def __init__(self, opener: Opener = urllib.request.urlopen,
                 home: Callable[[], str] = default_place):
        self._open = opener
        self._home = home

    def run(self, place: str = "", day: str = "now") -> str:
        place = " ".join(place.split()) or self._home()
        if not place or place.lower() in {"here", "my city", "my location", "outside"}:
            place = self._home()
        if not place:
            raise ToolError("Which city? You can also set RED_WEATHER_PLACE to your city.")
        geo = fetch_json(GEOCODE_URL + urlencode({"name": place, "count": 1, "language": "en",
                                                  "format": "json"}), "the weather service",
                         self._open)
        results = geo.get("results") or []
        if not results:
            raise ToolError(f"I couldn't find a place called {place}.")
        loc = results[0]
        name = loc.get("name", place)
        query = urlencode({
            "latitude": loc["latitude"], "longitude": loc["longitude"], "timezone": "auto",
            "forecast_days": 2,
            "current": "temperature_2m,apparent_temperature,weather_code,wind_speed_10m",
            "daily": "weather_code,temperature_2m_max,temperature_2m_min,"
                     "precipitation_probability_max",
        })
        data = fetch_json(FORECAST_URL + query, "the weather service", self._open)
        try:
            if day == "now":
                cur = data["current"]
                sky = WEATHER_CODES.get(int(cur["weather_code"]), "")
                text = f"In {name} it's {_num(cur['temperature_2m'])} degrees"
                text += f" and {sky}" if sky else ""
                feels = _num(cur["apparent_temperature"])
                if feels != _num(cur["temperature_2m"]):
                    text += f", feeling like {feels}"
                daily, i = data["daily"], 0
                text += (f". Today's high is {_num(daily['temperature_2m_max'][i])} and the low "
                         f"is {_num(daily['temperature_2m_min'][i])}")
            else:
                daily, i = data["daily"], (0 if day == "today" else 1)
                sky = WEATHER_CODES.get(int(daily["weather_code"][i]), "")
                when = "Today" if i == 0 else "Tomorrow"
                text = (f"{when} in {name}: {sky + ', ' if sky else ''}a high of "
                        f"{_num(daily['temperature_2m_max'][i])} and a low of "
                        f"{_num(daily['temperature_2m_min'][i])} degrees")
            rain = daily.get("precipitation_probability_max", [None, None])[i]
            if rain is not None:
                text += f", with a {_num(rain)} percent chance of rain"
        except (KeyError, IndexError, TypeError, ValueError) as e:
            raise ToolError("The weather service sent something I couldn't read.") from e
        return text + "."


# --------------------------------------------------------------------------
# Wikipedia
# --------------------------------------------------------------------------

WIKI_SEARCH_URL = "https://en.wikipedia.org/w/api.php?"
WIKI_SUMMARY_URL = "https://en.wikipedia.org/api/rest_v1/page/summary/"
MAX_EXTRACT = 3000

SUMMARY_SYSTEM = """You are Red, a voice assistant. Using only the Wikipedia text below, answer the user's question in 2 or 3 short sentences of plain spoken English. No lists, markdown or links. If the text doesn't answer it, say what the article is about instead.
Reply with JSON only: {"answer": "<your answer>"}"""


class LookUp(_UsesLLM):
    name = "look_up"
    description = ("Look something up online on Wikipedia and say a short summary aloud, "
                   "for example 'look up the James Webb telescope' or 'search the web for X "
                   "and tell me what it is'.")
    args_schema = {
        "type": "object",
        "properties": {
            "topic": {"type": "string", "minLength": 1, "maxLength": 200,
                      "description": "The thing to look up, as a short name."},
            "question": {"type": "string", "maxLength": 300,
                         "description": "The user's question, if they asked one."},
        },
        "required": ["topic"],
        "additionalProperties": False,
    }

    def __init__(self, llm=None, opener: Opener = urllib.request.urlopen):
        super().__init__(llm)
        self._open = opener
        self.last_details = ""

    def run(self, topic: str, question: str = "") -> str:
        self.last_details = ""
        topic = " ".join(topic.split())
        if not topic:
            raise ToolError("What should I look up?")
        found = fetch_json(WIKI_SEARCH_URL + urlencode({
            "action": "opensearch", "search": topic, "limit": 1, "namespace": 0,
            "format": "json"}), "Wikipedia", self._open)
        titles = found[1] if isinstance(found, list) and len(found) > 1 else []
        if not titles:
            raise ToolError(f"Wikipedia has nothing on {topic}.")
        title = titles[0]
        page = fetch_json(WIKI_SUMMARY_URL + quote(title.replace(" ", "_"), safe=""),
                          "Wikipedia", self._open)
        extract = " ".join(str(page.get("extract", "")).split())[:MAX_EXTRACT]
        if not extract:
            raise ToolError(f"Wikipedia has nothing on {topic}.")
        url = (page.get("content_urls", {}).get("desktop", {}).get("page")
               or f"https://en.wikipedia.org/wiki/{quote(title.replace(' ', '_'))}")
        self.last_details = f"Wikipedia: {page.get('title', title)}\n{url}"
        if page.get("type") == "disambiguation":
            return f"{title} can mean several things. Try saying which one you mean."
        if self._llm is None:
            return "From Wikipedia: " + spoken(extract, 3)
        ask = question.strip() or f"What is {topic}?"
        answer = ask_model(self._llm, SUMMARY_SYSTEM,
                           f"Question: {ask}\n\nWikipedia article '{title}':\n{extract}")
        return f"From Wikipedia: {answer}"


# --------------------------------------------------------------------------
# News (Google News RSS)
# --------------------------------------------------------------------------

NEWS_SEARCH_URL = "https://news.google.com/rss/search?"
NEWS_TOP_URL = "https://news.google.com/rss?"
MAX_HEADLINES = 3


def news_edition() -> tuple[str, str]:
    """RED_NEWS_EDITION like 'IN:en' or 'GB:en' (country:language), default US:en."""
    value = os.environ.get("RED_NEWS_EDITION", "").strip()
    country, _, lang = value.partition(":")
    if len(country) == 2 and country.isalpha() and lang.isalpha() and 2 <= len(lang) <= 3:
        return country.upper(), lang.lower()
    return "US", "en"


class News(Tool):
    name = "news"
    description = ("Read the latest news headlines from the internet, optionally about a "
                   "topic, for example 'latest news about India' or 'what's in the news'.")
    args_schema = {
        "type": "object",
        "properties": {"topic": {"type": "string", "maxLength": 100,
                                 "description": "Only if the user named a topic."}},
        "additionalProperties": False,
    }

    def __init__(self, opener: Opener = urllib.request.urlopen,
                 edition: Callable[[], tuple[str, str]] = news_edition):
        self._open = opener
        self._edition = edition
        self.last_details = ""

    def run(self, topic: str = "") -> str:
        self.last_details = ""
        topic = " ".join(topic.split())
        if topic.lower() in {"all", "everything", "today", "latest", "news", "none", "null"}:
            topic = ""
        country, lang = self._edition()
        params = {"hl": f"{lang}-{country}", "gl": country, "ceid": f"{country}:{lang}"}
        url = (NEWS_SEARCH_URL + urlencode({"q": topic, **params}) if topic
               else NEWS_TOP_URL + urlencode(params))
        raw = fetch(url, "the news service", self._open)
        try:
            root = ET.fromstring(raw)
        except ET.ParseError as e:
            raise ToolError("The news service sent something I couldn't read.") from e
        items = []
        for item in root.iter("item"):
            title = " ".join((item.findtext("title") or "").split())
            source = " ".join((item.findtext("source") or "").split())
            if source and title.endswith(f" - {source}"):
                title = title[: -len(source) - 3]
            if title:
                items.append((title, source, item.findtext("link") or ""))
            if len(items) >= 5:
                break
        if not items:
            return f"I didn't find any news about {topic}." if topic else "I didn't find any news."
        self.last_details = "\n".join(f"{t} ({s}) {link}" for t, s, link in items)
        spoken_items = "; ".join(f"{t}{f', from {s}' if s else ''}"
                                 for t, s, _ in items[:MAX_HEADLINES])
        about = f" about {topic}" if topic else ""
        return f"Here are the latest headlines{about}: {spoken_items}."
