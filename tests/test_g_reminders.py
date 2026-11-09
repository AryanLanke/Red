"""Scheduler and timer/reminder tools with a fake clock. No thread waits for real time."""

import json
import threading
import time
from datetime import datetime, timedelta

import pytest

from red import scheduler as sched_mod
from red.scheduler import Scheduler
from red.tools.base import ToolError
from red.tools.reminders import (CancelReminder, ListReminders, SetReminder, SetTimer,
                                 describe_item)

NOW = datetime(2026, 11, 8, 14, 0, 0)   # a Sunday, 2:00 PM


class Clock:
    def __init__(self, t=NOW):
        self.t = t

    def __call__(self):
        return self.t

    def advance(self, **kw):
        self.t += timedelta(**kw)


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def sched(tmp_path, clock):
    return Scheduler(tmp_path / "reminders.json", now=clock, start=False)


def tools(sched, clock):
    src = lambda: sched  # noqa: E731
    return (SetTimer(src, clock), SetReminder(src, clock), ListReminders(src, clock),
            CancelReminder(src, clock))


# --- Scheduler ------------------------------------------------------------------

def test_add_pending_cancel(sched, clock):
    a = sched.add(NOW + timedelta(hours=2), "b later")
    b = sched.add(NOW + timedelta(hours=1), "a sooner")
    assert [t for _, _, t in sched.pending()] == ["a sooner", "b later"]
    assert sched.cancel(a) is True
    assert sched.cancel("SOONER") is True           # by text, ignoring case
    assert sched.cancel("nothing") is False
    assert sched.pending() == []
    assert isinstance(b, str)


def test_rejects_past_and_far_future(sched):
    with pytest.raises(ValueError, match="already passed"):
        sched.add(NOW - timedelta(minutes=1), "x")
    with pytest.raises(ValueError, match="7 days"):
        sched.add(NOW + timedelta(days=7, minutes=1), "x")
    with pytest.raises(ValueError):
        sched.add(NOW + timedelta(minutes=1), "   ")


def test_due_items_are_delivered_once(sched, clock):
    said = []
    sched.on_due = said.append
    sched.add(NOW + timedelta(minutes=5), "tea")
    assert sched.tick() == []
    clock.advance(minutes=5)
    assert sched.tick() == ["tea"]
    assert sched.tick() == []
    assert said == ["tea"] and sched.pending() == []


def test_due_items_wait_for_a_handler(sched, clock):
    sched.add(NOW + timedelta(minutes=1), "tea")
    clock.advance(minutes=1)
    assert sched.tick() == []                 # no on_due yet: kept
    sched.on_due = lambda text: None
    assert sched.tick() == ["tea"]


def test_broken_handler_does_not_lose_others(sched, clock):
    said = []

    def handler(text):
        said.append(text)
        if text == "a":
            raise RuntimeError("speaker broke")

    sched.on_due = handler
    sched.add(NOW + timedelta(minutes=1), "a")
    sched.add(NOW + timedelta(minutes=2), "b")
    clock.advance(minutes=3)
    sched.tick()
    assert said == ["a", "b"]


def test_survives_a_restart(tmp_path, clock):
    path = tmp_path / "data" / "reminders.json"
    first = Scheduler(path, now=clock, start=False)
    first.add(NOW + timedelta(hours=1), "call mom")
    assert json.loads(path.read_text())["reminders"][0]["text"] == "call mom"
    second = Scheduler(path, now=clock, start=False)
    assert [t for _, _, t in second.pending()] == ["call mom"]


def test_missed_while_closed(tmp_path, clock):
    path = tmp_path / "reminders.json"
    Scheduler(path, now=clock, start=False).add(NOW + timedelta(minutes=10), "call mom")
    Scheduler(path, now=clock, start=False).add(NOW + timedelta(minutes=20), "stale")
    clock.advance(hours=3)
    later = Scheduler(path, now=clock, start=False)
    later.on_due = lambda t: None
    assert later.tick()[0] == "You missed a reminder at 2:10 PM: call mom"


def test_very_old_missed_reminders_are_dropped(tmp_path, clock):
    path = tmp_path / "reminders.json"
    Scheduler(path, now=clock, start=False).add(NOW + timedelta(minutes=10), "old")
    clock.advance(days=2)
    assert Scheduler(path, now=clock, start=False).pending() == []


def test_unreadable_file_is_ignored(tmp_path, clock):
    path = tmp_path / "reminders.json"
    path.write_text("{not json")
    assert Scheduler(path, now=clock, start=False).pending() == []


def test_background_thread_delivers(tmp_path, monkeypatch):
    monkeypatch.setattr(sched_mod, "POLL_SECONDS", 0.02)
    s = Scheduler(tmp_path / "r.json")
    got = threading.Event()
    s.on_due = lambda text: got.set()
    s.add(datetime.now() + timedelta(seconds=1), "soon")
    assert got.wait(5)


def test_default_scheduler_is_one_per_process(monkeypatch, tmp_path):
    monkeypatch.setenv("RED_HOME", str(tmp_path))
    monkeypatch.setattr(sched_mod, "_default", None)
    a = sched_mod.default_scheduler()
    assert a is sched_mod.default_scheduler()
    assert sched_mod.reminders_file() == tmp_path / "data" / "reminders.json"
    monkeypatch.setattr(sched_mod, "_default", None)


# --- tools -----------------------------------------------------------------------

def test_timer(sched, clock):
    timer, _, _, _ = tools(sched, clock)
    assert timer.run(minutes=10) == "Timer set for 10 minutes. It ends at 2:10 PM."
    assert timer.run(seconds=90) == "Timer set for 1 minute and 30 seconds. It ends at 2:01 PM."
    assert timer.run(minutes=90, label="Pasta") == \
        "Timer set for 1 hour and 30 minutes. It ends at 3:30 PM."
    texts = [t for _, _, t in sched.pending()]
    assert texts == ["Your 1 minute and 30 second timer is done.",
                     "Your 10 minute timer is done.", "Your pasta timer is done."]


def test_timer_limits(sched, clock):
    timer, _, _, _ = tools(sched, clock)
    with pytest.raises(ToolError, match="How long"):
        timer.run()
    with pytest.raises(ToolError, match="7 days"):
        timer.run(minutes=7 * 24 * 60, seconds=60)


@pytest.mark.parametrize("args, when, reply", [
    ({"time": "15:00"}, NOW.replace(hour=15), "OK, I'll remind you at 3:00 PM to call mom."),
    ({"time": "09:30"}, NOW.replace(hour=9, minute=30) + timedelta(days=1),
     "OK, I'll remind you at 9:30 AM tomorrow to call mom."),
    ({"time": "09:30", "day": "tomorrow"}, NOW.replace(hour=9, minute=30) + timedelta(days=1),
     None),
    ({"time": "08:00", "day": "tuesday"}, NOW.replace(hour=8) + timedelta(days=2),
     "OK, I'll remind you at 8:00 AM on Tuesday to call mom."),
    ({"time": "15:00", "day": "sunday"}, NOW.replace(hour=15), None),     # later today
    ({"time": "13:00", "day": "sunday"}, NOW.replace(hour=13) + timedelta(days=7), None),
    ({"in_minutes": 20}, NOW + timedelta(minutes=20), "OK, I'll remind you at 2:20 PM to call mom."),
])
def test_reminder_times(sched, clock, args, when, reply):
    _, remind, _, _ = tools(sched, clock)
    got = remind.run(text="to call mom", **args)
    assert sched.pending()[0][1] == when
    assert sched.pending()[0][2] == "Reminder: call mom."
    if reply:
        assert got == reply


def test_reminder_rejects_past_today_and_missing_time(sched, clock):
    _, remind, _, _ = tools(sched, clock)
    with pytest.raises(ToolError, match="already passed today"):
        remind.run(text="x", time="09:00", day="today")
    with pytest.raises(ToolError, match="When should I remind you"):
        remind.run(text="x")
    with pytest.raises(ToolError, match="7 days"):
        remind.run(text="x", in_minutes=7 * 24 * 60 + 1)


def test_list(sched, clock):
    timer, remind, listing, _ = tools(sched, clock)
    assert listing.run() == "You don't have any timers or reminders."
    timer.run(minutes=10)
    remind.run(text="call mom", time="15:00")
    assert listing.run() == ("You have 2: the 10 minute timer at 2:10 PM; "
                             "call mom at 3:00 PM.")
    assert listing.last_details.splitlines() == ["2:10 PM: the 10 minute timer",
                                                 "3:00 PM: call mom"]


def test_cancel(sched, clock):
    timer, remind, _, cancel = tools(sched, clock)
    assert cancel.run(which="timer") == "You don't have any timers or reminders."
    timer.run(minutes=10)
    remind.run(text="call mom", time="15:00")
    remind.run(text="water the plants", time="16:00")
    assert cancel.run(which="the timer") == "Cancelled the 10 minute timer."
    assert cancel.run(which="call mom reminder") == "Cancelled call mom."
    with pytest.raises(ToolError, match="couldn't find"):
        cancel.run(which="dentist")
    assert cancel.run() == "Cancelled water the plants."     # only one left
    timer.run(minutes=1)
    timer.run(minutes=2)
    with pytest.raises(ToolError, match="Which one"):
        cancel.run()
    assert cancel.run(which="all") == "Cancelled all 2."
    assert sched.pending() == []


def test_describe_item():
    assert describe_item("Your pasta timer is done.") == "the pasta timer"
    assert describe_item("Reminder: call mom.") == "call mom"


def test_registry_build_starts_no_scheduler(monkeypatch):
    from red.tools import default_registry
    monkeypatch.setattr(sched_mod, "_default", None)
    default_registry()
    assert sched_mod._default is None


def test_cancel_falls_back_to_your_words(sched, clock):
    # The model said only "reminder" for "cancel my reminder to call mom".
    _, remind, _, cancel = tools(sched, clock)
    remind.run(text="call mom", time="15:00")
    remind.run(text="water the plants", time="16:00")
    cancel.set_command("cancel my reminder to call mom")
    assert cancel.run(which="reminder") == "Cancelled call mom."
    remind.run(text="call dad", time="15:30")
    cancel.set_command("cancel my reminder to call dad")
    assert cancel.run(which="all") == "Cancelled call dad."   # the model's "all" isn't yours
    cancel.set_command("cancel it")                         # names nothing: ask, as before
    remind.run(text="feed the cat", time="17:00")
    with pytest.raises(ToolError, match="Which one"):
        cancel.run(which="reminder")
