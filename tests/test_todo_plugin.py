"""The todo plugin (plan.md B4). The list and logs live in tmp folders, never the user's."""

import json
import sys
from datetime import datetime

import pytest

from red import plugins as pl
from red.tools.base import ToolError


@pytest.fixture(scope="module")
def mod():
    loaded = {p.name: p for p in pl.load(None, builtin_dir=pl.BUILTIN_DIR)}
    assert not loaded["todo"].error, loaded["todo"].error
    return sys.modules["red_plugin_todo"]


@pytest.fixture
def todo(mod, tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "red_home", lambda: tmp_path)
    return mod.Todo()


def test_add_list_done_clear(todo, tmp_path):
    assert todo.run(action="list") == "Nothing left on your list."
    todo.run(action="add", text="finish the slides")
    assert todo.run(action="add", text="call the dentist") == "Added: call the dentist."
    assert todo.run(action="list") == "2 left: finish the slides; call the dentist."
    assert todo.run(action="done", text="the slides") == "Ticked off: finish the slides. 1 left."
    assert todo.run(action="done", text="dentist") == "Ticked off: call the dentist. That's everything."
    assert todo.run(action="clear") == "Cleared 2 done."
    assert todo.run(action="clear") == "Nothing done to clear."
    assert (tmp_path / "memory" / "todo.json").is_file()


def test_done_falls_back_to_the_users_words(todo):
    todo.run(action="add", text="finish the slides")
    todo.set_command("mark the slides done")
    assert todo.run(action="done") == "Ticked off: finish the slides. That's everything."


def test_errors(todo):
    with pytest.raises(ToolError, match="Add what"):
        todo.run(action="add")
    with pytest.raises(ToolError, match="don't see"):
        todo.run(action="done", text="rocket")


def test_recap(mod, todo, tmp_path, monkeypatch):
    day = "2026-11-13"
    (tmp_path / "logs").mkdir()
    lines = [{"time": f"{day}T09:00:00+05:30", "tool": "open_app", "status": "ok"},
             {"time": f"{day}T09:05:00+05:30", "tool": "open_app", "status": "ok"},
             {"time": f"{day}T09:10:00+05:30", "tool": "weather", "status": "ok"},
             {"time": f"{day}T09:11:00+05:30", "tool": "none", "status": "none"},
             {"time": "2026-11-12T09:00:00+05:30", "tool": "volume", "status": "ok"}]
    (tmp_path / "logs" / "commands.jsonl").write_text("\n".join(map(json.dumps, lines)), encoding="utf-8")
    todo.run(action="add", text="ship it")
    items = json.loads((tmp_path / "memory" / "todo.json").read_text())
    todo.run(action="done", text="ship it")
    items = json.loads((tmp_path / "memory" / "todo.json").read_text())
    items[0]["finished"] = f"{day}T10:00:00"
    (tmp_path / "memory" / "todo.json").write_text(json.dumps(items))
    recap = mod.DayRecap(today=lambda: datetime(2026, 11, 13, 20, 0))
    monkeypatch.setattr(recap, "commits", lambda d: {"red": ["add the recap", "fix it"]})
    assert recap.run() == ('Today: 2 commits in red, latest "add the recap"; finished 1 to-do: ship it; '
                           '3 things done with me, mostly open app x2, weather x1.')
    quiet = mod.DayRecap(today=lambda: datetime(2026, 1, 1))
    monkeypatch.setattr(quiet, "commits", lambda d: {})
    assert "don't have much" in quiet.run()
