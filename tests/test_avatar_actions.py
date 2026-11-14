"""The companion menu's back end: times people type, reminders, the to-do list. No window, no clock."""

import json
from datetime import datetime, timedelta

import pytest

from red.avatar.actions import MenuActions, parse_when

NOW = datetime(2026, 11, 13, 22, 10, 0)


@pytest.mark.parametrize("text, expected", [
    ("in 20 minutes", NOW + timedelta(minutes=20)),
    ("45 min", NOW + timedelta(minutes=45)),
    ("2 hours", NOW + timedelta(hours=2)),
    ("an hour", NOW + timedelta(hours=1)),
    ("half an hour", NOW + timedelta(minutes=30)),
    ("1.5 hours", NOW + timedelta(minutes=90)),
    ("23:30", datetime(2026, 11, 13, 23, 30)),
    ("11:30pm", datetime(2026, 11, 13, 23, 30)),
    ("at 9:15 am", datetime(2026, 11, 14, 9, 15)),            # already past tonight: tomorrow
    ("9am", datetime(2026, 11, 14, 9, 0)),
    ("tomorrow 9am", datetime(2026, 11, 14, 9, 0)),
    ("tomorrow at 6:45 pm", datetime(2026, 11, 14, 18, 45)),
    ("Tomorrow", datetime(2026, 11, 14, 9, 0)),
    ("today 23:00", datetime(2026, 11, 13, 23, 0)),
    ("12am", datetime(2026, 11, 14, 0, 0)),
    ("12pm", datetime(2026, 11, 14, 12, 0)),
])
def test_parse_when(text, expected):
    assert parse_when(text, NOW) == expected


@pytest.mark.parametrize("text", ["", "soon", "5", "25:00", "13pm", "0 min", "in a while", "9:75", "at"])
def test_parse_when_refuses_what_it_cannot_read(text):
    assert parse_when(text, NOW) is None


class FakeScheduler:
    def __init__(self):
        self.added = []

    def add(self, when, text):
        if when <= NOW:
            raise ValueError("That time has already passed")
        self.added.append((when, text))
        return "id"


def actions(tmp_path, **kw):
    sched = FakeScheduler()
    return MenuActions(tmp_path, scheduler=lambda: sched, now=lambda: NOW, clock=lambda: 1000.0, **kw), sched


def test_a_reminder_goes_to_the_scheduler_like_the_tool_does(tmp_path):
    a, sched = actions(tmp_path)
    line = a.remind("  call   mom. ", "in 20 minutes")
    assert sched.added == [(NOW + timedelta(minutes=20), "Reminder: call mom.")]
    assert line == "Okay, I'll remind you at 10:30 PM."
    assert a.remind("water the plants", "tomorrow 9am") == "Okay, I'll remind you at 9:00 AM tomorrow."


def test_reminder_problems_are_messages_to_show(tmp_path):
    a, sched = actions(tmp_path)
    with pytest.raises(ValueError, match="remind you about"):
        a.remind("  ", "10 min")
    with pytest.raises(ValueError, match="couldn't read"):
        a.remind("x", "whenever")
    assert sched.added == []


def test_the_real_scheduler_limits_apply(tmp_path):
    from red import scheduler
    real = scheduler.Scheduler(tmp_path / "reminders.json", now=lambda: NOW, start=False)
    a = MenuActions(tmp_path, scheduler=lambda: real, now=lambda: NOW)
    a.remind("check the oven", "in 15 minutes")
    assert [(t, w) for _, t, w in real.pending()] == [(NOW + timedelta(minutes=15), "Reminder: check the oven.")]
    with pytest.raises(ValueError, match="7 days"):
        a.remind("far away", "in 200 hours")


def test_tasks_are_kept_in_memory_tasks_json(tmp_path):
    a, _ = actions(tmp_path)
    assert a.list_tasks() == []
    first = a.add_task("  buy   milk ")
    second = a.add_task("send the invoice")
    assert [t.text for t in a.list_tasks()] == ["buy milk", "send the invoice"]
    path = tmp_path / "memory" / "tasks.json"
    assert json.loads(path.read_text(encoding="utf-8"))[0]["text"] == "buy milk"
    assert a.set_done(first.id) and [t.text for t in a.list_tasks(include_done=False)] == ["send the invoice"]
    assert a.set_done(first.id, False) and len(a.list_tasks(include_done=False)) == 2
    assert not a.set_done("nope")
    assert a.set_done(second.id) and a.clear_done() == 1
    assert [t.text for t in a.list_tasks()] == ["buy milk"]
    assert a.remove_task(first.id) and not a.remove_task(first.id)
    assert not list(path.parent.glob("*.part"))               # written atomically


def test_task_text_is_checked(tmp_path):
    a, _ = actions(tmp_path)
    with pytest.raises(ValueError):
        a.add_task("   ")
    assert len(a.add_task("x" * 500).text) == 200


def test_a_broken_tasks_file_is_an_empty_list(tmp_path):
    path = tmp_path / "memory" / "tasks.json"
    path.parent.mkdir(parents=True)
    path.write_text("{not json", encoding="utf-8")
    a, _ = actions(tmp_path)
    assert a.list_tasks() == []
    a.add_task("fresh start")
    assert [t.text for t in a.list_tasks()] == ["fresh start"]


def test_talk_and_music_use_what_the_voice_loop_hands_in(tmp_path):
    calls = []
    a, _ = actions(tmp_path, talk=lambda: calls.append("talk"), music=lambda: "Putting on Back in Black.")
    assert a.talk() and calls == ["talk"]
    assert a.play_music() == "Putting on Back in Black."
    bare, _ = actions(tmp_path)
    assert not bare.talk() and bare.play_music() is None
