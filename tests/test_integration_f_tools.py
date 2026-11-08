"""Routes real typed commands for the Track F tools through the local model,
with every tool registered. Nothing is executed: only the chosen call is checked.

Slow and needs the model, so it only runs with RED_INTEGRATION=1.
"""

import os

import pytest

from red.config import load_settings
from red.llm import connect
from red.router import Router
from red.tools import default_registry

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(os.environ.get("RED_INTEGRATION") != "1",
                       reason="set RED_INTEGRATION=1 to run"),
]


@pytest.fixture(scope="module")
def router():
    llm, server = connect(load_settings())
    yield Router(default_registry(), llm)
    if server:
        server.stop()


def norm(value):
    return " ".join(str(value).lower().replace("-", " ").split()) if isinstance(value, str) \
        else value


def has(**expected):
    """Check only the named args, ignoring case and spacing."""
    def check(args):
        return all(norm(args.get(k)) == norm(v) for k, v in expected.items())
    check.__name__ = f"has({expected})"
    return check


def contains(key, *words):
    def check(args):
        return all(w in norm(args.get(key, "")) for w in words)
    check.__name__ = f"contains({key}, {words})"
    return check


ANY = None

CASES = [
    # Office apps (open_app with App Paths)
    ("open powerpoint", "open_app", has(app="powerpoint")),
    ("open ppt", "open_app", ANY),
    ("open word", "open_app", has(app="word")),
    ("launch excel", "open_app", has(app="excel")),
    ("open outlook", "open_app", has(app="outlook")),
    # web_search
    ("search the web for best laptops 2026", "web_search", contains("query", "best laptops")),
    ("google how to boil an egg", "web_search", contains("query", "boil", "egg")),
    ("search youtube for lofi music", "web_search", has(site="youtube")),
    ("look up the weather in Pune", "web_search", contains("query", "weather", "pune")),
    ("show me pictures of cats", "web_search", has(site="images")),
    ("open youtube", "open_url", ANY),
    # find_file and open_found_file
    ("find my resume", "find_file", contains("name", "resume")),
    ("where is my budget spreadsheet", "find_file", contains("name", "budget")),
    ("where did I save the tax return pdf", "find_file", contains("name", "tax")),
    ("find the folder called holiday photos", "find_file", contains("name", "holiday")),
    ("open it", "open_found_file", ANY),
    ("open the second one", "open_found_file", has(number=2)),
    ("open my downloads folder", "open_folder", ANY),
    # compose_mail
    ("compose a mail to bob@example.com about the project deadline", "compose_mail",
     lambda a: a.get("to") == "bob@example.com" and "deadline" in norm(a.get("subject", ""))),
    ("write an email to mom saying I will be late", "compose_mail", contains("to", "mom")),
    ("draft an email to my boss about taking friday off", "compose_mail",
     contains("subject", "friday")),
    ("send a mail to priya about lunch", "compose_mail", contains("to", "priya")),
    # quick system actions
    ("lock my pc", "lock_pc", ANY),
    ("lock the computer", "lock_pc", ANY),
    ("put the computer to sleep", "sleep_pc", ANY),
    ("turn the volume up", "volume", has(action="up")),
    ("volume down a bit", "volume", has(action="down")),
    ("mute the sound", "volume", has(action="mute")),
    ("unmute", "volume", has(action="unmute")),
    ("set the volume to 40 percent", "volume", has(action="set", percent=40)),
    ("pause", "pause_music", ANY),
    ("pause the video", "pause_music", ANY),
    ("play the next track", "next_song", ANY),
    ("go back to the previous song", "previous_track", ANY),
    ("open bluetooth settings", "open_settings", has(page="bluetooth")),
    ("open display settings", "open_settings", has(page="display")),
    ("open wifi settings", "open_settings", has(page="wifi")),
    ("check for windows updates", "open_settings", has(page="windows_update")),
    ("what time is it", "tell_status", has(what="time")),
    ("what's the date today", "tell_status", has(what="date")),
    ("how much battery do I have", "tell_status", has(what="battery")),
    ("take a screenshot", "take_screenshot", ANY),
    ("empty the recycle bin", "empty_recycle_bin", ANY),
]


@pytest.mark.parametrize("command, tool, check", CASES)
def test_routes(router, command, tool, check):
    route = router.route(command)
    assert route.tool == tool, route
    if check is not None:
        assert check(route.args), (check.__name__, route)
