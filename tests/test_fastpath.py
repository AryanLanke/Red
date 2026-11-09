"""red.fastpath: clear, common commands skip the model; anything unclear still goes to it."""

import json
import time

import pytest

from red import fastpath as fp
from red.router import Router
from red.tools import default_registry

APPS = {"edge", "chrome", "notepad", "calculator", "vs code", "spotify", "word"}
FOLDERS = {"downloads", "documents", "desktop", "pictures", "music", "videos", "projects"}


def match(text):
    return fp.match(text, apps=lambda n: n in APPS, folders=lambda n: n in FOLDERS)


def call(tool, **args):
    return {"tool": tool, "args": args}


@pytest.mark.parametrize("said, expected", [
    # open ... (the 23:37 test, and its "from Chrome")
    ("Open YouTube.", call("open_url", url="https://www.youtube.com")),
    ("Can you open YouTube for me from Chrome?", call("open_url", url="https://www.youtube.com", browser="chrome")),
    ("open youtube in microsoft edge", call("open_url", url="https://www.youtube.com", browser="edge")),
    ("Hey Red, open GitHub please", call("open_url", url="https://github.com")),
    ("go to github.com", call("open_url", url="https://github.com")),
    ("open Edge", call("open_app", app="Edge")),
    ("Open Chrome.", call("open_app", app="Chrome")),
    ("launch the notepad app", call("open_app", app="notepad")),
    ("open my downloads folder", call("open_folder", folder="Downloads")),
    ("open documents", call("open_folder", folder="Documents")),
    ("open my projects folder", call("open_folder", folder="projects")),
    # volume
    ("volume up", call("volume", action="up")),
    ("Turn the volume down.", call("volume", action="down")),
    ("mute", call("volume", action="mute")),
    ("unmute the sound", call("volume", action="unmute")),
    ("set the volume to 30 percent", call("volume", action="set", percent=30)),
    # media keys
    ("Pause.", call("pause_music")),
    ("pause the video", call("pause_music")),
    ("resume", call("resume_music")),
    ("play", call("resume_music")),
    ("play it", call("resume_music")),
    ("next song", call("next_song")),
    ("skip this song", call("next_song")),
    ("previous track", call("previous_track")),
    ("stop the music", call("stop_music")),
    # lock, time, screenshot
    ("lock my PC", call("lock_pc")),
    ("Lock.", call("lock_pc")),
    ("What time is it?", call("tell_status", what="time")),
    ("what's the date today", call("tell_status", what="date")),
    ("how much battery do I have", call("tell_status", what="battery")),
    ("take a screenshot", call("take_screenshot")),
    # play and search
    ("play Believer", call("play_online", query="Believer")),
    ("Play some Arijit Singh.", call("play_online", query="some Arijit Singh")),
    ("play a podcast about loneliness", call("play_online", query="a podcast about loneliness")),
    ("play lofi on YouTube", call("play_online", query="lofi")),
    ("put on some jazz", call("play_online", query="some jazz")),
    ("search youtube for lofi music", call("web_search", query="lofi music", site="youtube")),
    ("search lofi on YouTube", call("web_search", query="lofi", site="youtube")),
    ("search lofi in Edge", call("web_search", query="lofi", browser="edge")),
    ("google cheap flights to Goa", call("web_search", query="cheap flights to Goa")),
    ("search the web for cheap flights to Goa", call("web_search", query="cheap flights to Goa")),
])
def test_clear_commands_skip_the_model(said, expected):
    assert match(said) == expected


@pytest.mark.parametrize("said", [
    "open it", "open the second one",                       # need find_file's results
    "open my resume", "open bluetooth settings",            # not a known app, folder or site
    "open YouTube in Edge and search lofi",                 # two things (task 9)
    "Red you just open chrome. I told you to open YouTube",
    "search online for the mars rover and tell me about it",   # look_up
    "search for my resume file", "search for what is hugging face",
    "play the next one please and then pause",
    "don't open youtube", "shut down in 2 hours", "restart", "sleep",   # destructive: always the model
    "empty the recycle bin", "what's on my screen", "how tall is mount everest",
    "I'm feeling lonely.", "banana", "", "   ",
    "open " + "x" * 90,
    "play Believer in Chrome",                              # play_online has no browser yet
])
def test_anything_unclear_goes_to_the_model(said):
    assert match(said) is None


@pytest.mark.parametrize("said, topic", [
    ("who made Siri", "Siri"),
    ("Who is the CEO of Microsoft?", "CEO of Microsoft"),
    ("what is Hugging Face", "Hugging Face"),
    ("What's the latest iPhone?", "latest iPhone"),
    ("What's Punisher about?", "Punisher"),                  # from the 2026-11-09 log
    ("Hey Red, tell me about the James Webb telescope", "James Webb telescope"),
    ("who invented the telephone", "telephone"),
    ("what are black holes", "black holes"),
])
def test_plain_fact_questions_go_straight_to_look_up(said, topic):
    assert match(said) == call("look_up", topic=topic)


@pytest.mark.parametrize("said", [
    "who are you", "what is your name", "who made you", "what are you doing right now?",
    "what's going on in your mind right now", "what's up", "What's up Cop?",
    "what's on my screen right now", "what is my battery", "what is the weather in Pune",
    "what's the news today", "what is in my calendar", "what is 5 + 5", "what is 12 times 7",
    "who made it", "what is that", "who is she", "what was the song", "what time is it now",
    "what's happening", "what is wrong with this",
])
def test_personal_or_follow_up_questions_still_go_to_the_model(said):
    result = match(said)
    assert result is None or result["tool"] != "look_up"


def test_mid_conversation_a_fact_question_goes_to_the_model():
    model = Model()
    router = Router(default_registry(), model,
                    fast=lambda c: fp.match(c, apps=lambda n: False, folders=lambda n: False))
    router.route("who is the lead actor")
    assert model.calls == 0                                          # no conversation: fast
    router.route("who is the lead actor", context="User: tell me about Punisher\nRed: ...")
    assert model.calls == 1                                          # "the" one just named


def test_it_is_far_under_a_millisecond_a_command():
    sentences = ["Open YouTube.", "volume up", "play Believer", "I'm feeling lonely.",
                 "search online for the mars rover and tell me about it"] * 200
    start = time.perf_counter()
    for s in sentences:
        match(s)
    assert (time.perf_counter() - start) / len(sentences) < 0.001


class NoModel:
    def complete_json(self, *a, **k):
        raise AssertionError("the model must not be asked")


class Model:
    def __init__(self):
        self.calls = 0

    def complete_json(self, system, user, schema, **k):
        self.calls += 1
        return json.dumps({"tool": "none", "args": {"reply": "Hm?"}})


def test_the_router_uses_it_first_and_checks_it_the_same_way():
    router = Router(default_registry(), NoModel(),
                    fast=lambda c: fp.match(c, apps=lambda n: False, folders=lambda n: False))
    route = router.route("Open YouTube.")
    assert (route.tool, route.args, route.destructive) == (
        "open_url", {"url": "https://www.youtube.com"}, False)


def test_a_bad_fast_call_is_refused_like_a_bad_model_call():
    from red.router import RouteError
    router = Router(default_registry(), NoModel(),
                    fast=lambda c: {"tool": "volume", "args": {"action": "set", "percent": 500}})
    with pytest.raises(RouteError):
        router.route("volume 500")


def test_unclear_commands_still_reach_the_model():
    model = Model()
    router = Router(default_registry(), model)
    assert router.route("I'm feeling lonely.").is_none and model.calls == 1


def test_a_tool_the_registry_lacks_goes_to_the_model():
    from red.tools.base import ToolRegistry
    from red.tools.web import OpenUrl
    model = Model()
    router = Router(ToolRegistry([OpenUrl(open_browser=lambda u: True)]), model)
    router.route("volume up")                   # no volume tool here
    assert model.calls == 1


def test_known_apps_and_folders_by_default():
    # The built-in lists, not the fakes: Edge is a known app, Downloads a Windows folder.
    assert fp.match("open edge")["tool"] == "open_app"
    assert fp.match("open downloads")["tool"] == "open_folder"
    assert fp.match("open youtube")["tool"] == "open_url"
