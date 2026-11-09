"""Mail and calendar commands through the real local model, with the Google tools registered.

Nothing is sent to Google: these only check the tool call. RED_INTEGRATION=1 to run.
"""

import os

import pytest

from red.config import load_settings
from red.llm import connect
from red.router import Router
from red.tools import default_registry
from red.tools.calendar import spoken_times

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(os.environ.get("RED_INTEGRATION") != "1", reason="set RED_INTEGRATION=1 to run"),
]

AFTER_READING = ("User: read my mail from Rahul\n"
                 "Red: Rahul asks if you can come to dinner on Friday.")


@pytest.fixture(scope="module")
def router():
    llm, server = connect(load_settings())
    yield Router(default_registry(google=True), llm)
    if server:
        server.stop()


def has(**want):
    def check(args):
        return all(str(args.get(k, "")).lower() == str(v).lower() for k, v in want.items())
    check.__name__ = f"has({want})"
    return check


def mentions(key, *words):
    def check(args):
        return all(w in str(args.get(key, "")).lower() for w in words)
    check.__name__ = f"mentions({key}, {words})"
    return check


CASES = [
    ("any new mail?", "check_mail", None, ""),
    ("do I have any emails", "check_mail", None, ""),
    ("read my mail from Rahul", "read_mail", mentions("sender", "rahul"), ""),
    ("reply saying I'll come tomorrow", "reply_mail", mentions("body", "come", "tomorrow"), AFTER_READING),
    ("mail Mom that I'll be late", "send_mail", lambda a: "mom" in a["to"].lower() and "late" in a["body"].lower(), ""),
    ("what's on my calendar tomorrow?", "calendar_events", has(day="tomorrow"), ""),
    ("add a meeting Friday at 3", "calendar_add", has(day="friday", time="15:00"), ""),
    # The tool takes the event's time from your words when the model leaves it out.
    ("move my 5 pm to 6", "calendar_move",
     lambda a: a.get("new_time") == "18:00" and (a.get("time") or spoken_times("move my 5 pm to 6")[0]) == "17:00",
     ""),
    ("cancel my 4 pm", "calendar_cancel", has(time="16:00"), ""),
    ("draft an email to my boss about taking friday off", "compose_mail", None, ""),
]


@pytest.mark.parametrize("command, tool, check, context", CASES)
def test_routes(router, command, tool, check, context):
    route = router.route(command, context=context) if context else router.route(command)
    assert route.tool == tool, route
    if check is not None:
        assert check(route.args), (getattr(check, "__name__", "check"), route)
