"""The companion menu's back end (red/actions.py): reminders, tasks, music and talk, around the real tools."""

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from red import actions, scheduler
from red.tools.base import ToolError

NOW = datetime(2026, 11, 13, 15, 0, 0)          # a Friday


@pytest.fixture(autouse=True)
def _fresh(monkeypatch, tmp_path):
    actions.bind(None)
    actions._own_registry.cache_clear()
    monkeypatch.setenv("RED_HOME", str(tmp_path))
    yield
    actions.bind(None)
    actions._own_registry.cache_clear()


@pytest.mark.parametrize("when, args", [
    ("in 20 minutes", {"in_minutes": 20}), ("in an hour", {"in_minutes": 60}), ("in half an hour", {"in_minutes": 30}),
    ("in 2 hours", {"in_minutes": 120}), ("in 90 seconds", {"in_minutes": 2}), ("in one day", {"in_minutes": 1440}),
    ("at 3 pm", {"time": "15:00"}), ("3pm", {"time": "15:00"}), ("at 9:30 am", {"time": "09:30"}),
    ("15:30", {"time": "15:30"}), ("tomorrow at 9 am", {"time": "09:00", "day": "tomorrow"}),
    ("tomorrow 9am", {"time": "09:00", "day": "tomorrow"}), ("friday 18:00", {"time": "18:00", "day": "friday"}),
    ("tonight at 8", {"time": "20:00", "day": "today"}), ("12 am", {"time": "00:00"}), ("12 pm", {"time": "12:00"}),
])
def test_when_from_words(when, args):
    assert actions.when_from(when, NOW) == args


def test_when_from_a_datetime():
    assert actions.when_from(NOW + timedelta(hours=2), NOW) == {"time": "17:00", "day": "today"}
    assert actions.when_from(NOW + timedelta(days=1), NOW) == {"time": "15:00", "day": "tomorrow"}
    assert actions.when_from(NOW + timedelta(days=3), NOW) == {"time": "15:00", "day": "monday"}


@pytest.mark.parametrize("bad", ["", "soon", "whenever", "at 25:99", "in 9999 days", "at"])
def test_when_from_refuses_what_it_cannot_read(bad):
    with pytest.raises(ToolError):
        actions.when_from(bad, NOW)


def test_when_from_refuses_the_past_and_too_far():
    with pytest.raises(ToolError, match="passed"):
        actions.when_from(NOW - timedelta(minutes=1), NOW)
    with pytest.raises(ToolError, match="7 days"):
        actions.when_from(NOW + timedelta(days=9), NOW)


class FakeReminder:
    name = "set_reminder"

    def __init__(self):
        self.calls = []

    def run(self, **kw):
        self.calls.append(kw)
        return "Okay, I'll remind you."


class FakeRegistry:
    def __init__(self, **tools):
        self.tools = tools

    def __contains__(self, name):
        return name in self.tools

    def get(self, name):
        return self.tools[name]


def bind_registry(**tools):
    actions.bind(SimpleNamespace(executor=SimpleNamespace(registry=FakeRegistry(**tools))))


def test_remind_runs_the_set_reminder_tool():
    tool = FakeReminder()
    bind_registry(set_reminder=tool)
    assert actions.remind("  call   mom ", "at 3 pm", now=NOW) == "Okay, I'll remind you."
    assert tool.calls == [{"text": "call mom", "time": "15:00"}]
    actions.remind("stretch", "in 20 minutes", now=NOW)
    assert tool.calls[-1] == {"text": "stretch", "in_minutes": 20}


def test_remind_with_the_real_tool_and_scheduler(tmp_path):
    sched = scheduler.Scheduler(tmp_path / "r.json", now=lambda: NOW, start=False)
    from red.tools.reminders import ListReminders, SetReminder
    bind_registry(set_reminder=SetReminder(scheduler=lambda: sched, now=lambda: NOW),
                  list_reminders=ListReminders(scheduler=lambda: sched, now=lambda: NOW))
    reply = actions.remind("call mom", "in 20 minutes", now=NOW)
    assert "3:20" in reply
    tool = actions._tools().get("list_reminders")
    tool.run()
    assert "call mom" in tool.last_details


def test_remind_needs_a_text_and_a_time():
    bind_registry(set_reminder=FakeReminder())
    with pytest.raises(ToolError, match="what"):
        actions.remind("  ", "in 5 minutes", now=NOW)
    with pytest.raises(ToolError, match="When"):
        actions.remind("x", "", now=NOW)


def test_a_missing_tool_is_a_polite_error():
    bind_registry()
    with pytest.raises(ToolError, match="isn't available"):
        actions.remind("x", "in 5 minutes", now=NOW)
    with pytest.raises(ToolError, match="isn't available"):
        actions.add_task("x")


def test_tasks_go_through_the_todo_plugin(tmp_path):
    actions._own_registry.cache_clear()
    assert actions.list_tasks() == []
    assert actions.add_task("  finish   the slides ") == "Added: finish the slides."
    actions.add_task("call the bank")
    assert actions.list_tasks() == ["finish the slides", "call the bank"]
    assert (tmp_path / "memory" / "todo.json").is_file(), "the same list a spoken 'add ...' uses"
    with pytest.raises(ToolError, match="what"):
        actions.add_task("   ")


def test_play_music_with_a_query_uses_play_online():
    calls = []

    class Online:
        name = "play_online"

        def run(self, query):
            calls.append(query)
            return "Playing Believer."

        def take_later(self):
            return None
    bind_registry(play_online=Online())
    assert actions.play_music("  Believer ") == "Playing Believer." and calls == ["Believer"]


def test_play_music_without_a_query_lets_red_pick(monkeypatch):
    played = []
    from red import idle
    monkeypatch.setattr(idle, "make_music", lambda registry: lambda c: idle.Song("Putting on X.", lambda: played.append(1)))
    bind_registry()
    assert actions.play_music() == "Putting on X." and played == [1]
    monkeypatch.setattr(idle, "make_music", lambda registry: lambda c: None)
    with pytest.raises(ToolError, match="anything"):
        actions.play_music("")


def test_talk_fires_the_listener_like_the_hotkey():
    fired = []
    actions.bind(SimpleNamespace(listener=SimpleNamespace(_fire=fired.append)))
    assert actions.talk() == "Listening." and fired == ["menu"]
    actions.bind(SimpleNamespace(listener=None))
    with pytest.raises(ToolError, match="listening"):
        actions.talk()
    actions.bind(None)
    with pytest.raises(ToolError):
        actions.talk()
