"""notify_when_done: watching a window's text, finishing, timeout and cancellation.

No screen is read and no thread waits for real time: a fake reader returns
the window, and the clock is advanced by hand.
"""

import threading
from types import SimpleNamespace

import pytest

from red.router import RouteError, Router
from red.tools import default_registry
from red.tools.base import ToolError
from red.tools.watch import (MAX_SECONDS, CancelWatch, NotifyWhenDone, Watch, Watchers,
                             app_matches, default_reader, done_message)


class Clock:
    def __init__(self, now=1000.0):
        self.now = now

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def info(title="main.py - red - Visual Studio Code", app="Code", lines=(), ocr_ok=True):
    return SimpleNamespace(title=title, app=app, lines=list(lines), ocr_ok=ocr_ok)


class Reader:
    """Returns the given readings in order, then repeats the last one."""

    def __init__(self, *readings):
        self.readings = list(readings)

    def __call__(self):
        return self.readings.pop(0) if len(self.readings) > 1 else self.readings[0]


def watch(reader, clock=None, **kwargs):
    done = []
    w = Watch("VS Code", read=reader, on_done=lambda w, reason: done.append(reason),
              clock=clock or Clock(), **kwargs)
    return w, done


# --- when it's done ----------------------------------------------------------------

@pytest.mark.parametrize("line", ["Build finished successfully", "Done!", "Task completed",
                                  "exit code 0", "npm run build: process exited with 0"])
def test_a_completion_line_means_done(line):
    w, done = watch(Reader(info(lines=["compiling...", line])))
    assert w.tick() == "finished"
    assert done == ["finished"] and w.done


def test_the_users_target_text_means_done():
    done = []
    w = Watch("VS Code", "ready to deploy", read=Reader(info(lines=["Ready to deploy"])),
              on_done=lambda w, reason: done.append(reason))
    assert w.tick() == "target"
    assert done == ["target"]


def test_another_window_is_not_the_app():
    w, done = watch(Reader(info(title="A video - YouTube", app="chrome", lines=["finished"])))
    assert w.tick() is None
    assert done == []


def test_vs_code_matches_its_real_window_title():
    assert app_matches("VS Code", "main.py - red - Visual Studio Code", "Code")
    assert app_matches("vscode", "Visual Studio Code", "Code")
    assert app_matches("Chrome", "YouTube", "chrome.exe")
    assert not app_matches("VS Code", "A video - YouTube", "chrome")


def test_the_screen_stopping_for_two_minutes_means_done():
    clock = Clock()
    w, done = watch(Reader(info(lines=["step 1"])), clock)
    assert w.tick() is None                       # baseline
    clock.advance(60)
    assert w.tick() is None
    clock.advance(61)
    assert w.tick() == "still"
    assert done == ["still"]


def test_a_changing_screen_keeps_watching():
    clock = Clock()
    reader = Reader(info(lines=["step 1"]), info(lines=["step 2"]), info(lines=["step 2"]))
    w, done = watch(reader, clock)
    assert w.tick() is None
    clock.advance(61)
    assert w.tick() is None                       # changed: the clock restarts
    clock.advance(61)
    assert w.tick() is None                       # only 61 s since it changed
    clock.advance(60)
    assert w.tick() == "still"
    assert done == ["still"]


def test_empty_ocr_is_not_treated_as_still():
    clock = Clock()
    w, done = watch(Reader(info(lines=[], ocr_ok=False)), clock)
    w.tick()
    clock.advance(1000)
    assert w.tick() is None and done == []


def test_three_hours_is_the_limit():
    clock = Clock()
    w, done = watch(Reader(info(lines=["still going"])), clock)
    clock.advance(MAX_SECONDS + 1)
    assert w.tick() == "timeout"
    assert "three hours" in done_message("VS Code", "", "timeout")


def test_a_reader_that_fails_is_retried():
    calls = []

    def broken():
        calls.append(1)
        raise OSError("OCR unavailable")

    w, done = watch(broken)
    assert w.tick() is None and done == [] and len(calls) == 1


def test_it_announces_only_once():
    w, done = watch(Reader(info(lines=["done"])))
    assert w.tick() == "finished"
    assert w.tick() == "finished" and done == ["finished"]


# --- the tool and its watches ------------------------------------------------------

def watchers(*readings, clock=None, autostart=False):
    spoken, shown = [], []
    manager = Watchers(read=Reader(*readings), announce=spoken.append,
                       notify=lambda title, body: shown.append((title, body)),
                       clock=clock or Clock(), autostart=autostart)
    return manager, spoken, shown


def test_the_tool_starts_watching_and_says_what_it_waits_for():
    manager, _, _ = watchers(info(lines=["working"]))
    tool = NotifyWhenDone(manager)
    assert tool.run(app_name="VS Code") == "OK, I'll tell you when VS Code is done."
    assert tool.run(app_name="VS Code", target_text="Build succeeded") == (
        'OK, I\'ll tell you when VS Code shows "Build succeeded".')
    assert [w.target_text for w in manager.pending()] == ["Build succeeded"]


def test_the_tool_needs_an_app():
    with pytest.raises(ToolError):
        NotifyWhenDone(watchers(info())[0]).run(app_name="  ")


def test_the_finished_app_is_spoken_and_shown():
    clock = Clock()
    manager, spoken, shown = watchers(info(lines=["Build finished"]), clock=clock)
    toaster = NotifyWhenDone(manager)
    toaster.run(app_name="VS Code")
    pending, = manager.pending()
    assert pending.tick() == "finished"
    assert spoken == ["VS Code is done."]
    assert shown == [("Red", "VS Code is done.")]
    assert manager.pending() == []


def test_a_second_watch_replaces_the_first_for_the_same_app():
    manager, _, _ = watchers(info(lines=["working"]))
    tool = NotifyWhenDone(manager)
    tool.run(app_name="VS Code", target_text="one")
    tool.run(app_name="vs code", target_text="two")
    assert [w.target_text for w in manager.pending()] == ["two"]


def test_stop_watching_cancels_without_announcing():
    clock = Clock()
    manager, spoken, shown = watchers(info(lines=["Build finished"]), clock=clock)
    tool = NotifyWhenDone(manager)
    tool.run(app_name="VS Code")
    watched, = manager.pending()
    canceller = CancelWatch(manager)
    assert canceller.run(app_name="VS Code") == "Stopped watching VS Code."
    assert watched.tick() is None and spoken == [] and shown == []
    assert manager.pending() == []


def test_cancelling_something_that_isnt_watched():
    manager, _, _ = watchers(info())
    assert NotifyWhenDone(manager).cancel_watch("Chrome") == "I wasn't watching Chrome."
    assert CancelWatch(manager).run(app_name="Chrome") == "I wasn't watching Chrome."
    assert CancelWatch(manager).run() == "I wasn't watching anything."


def test_cancel_watch_with_no_app_stops_everything():
    manager, _, _ = watchers(info(lines=["working"]))
    tool = NotifyWhenDone(manager)
    tool.run(app_name="VS Code")
    tool.run(app_name="Chrome")
    assert CancelWatch(manager).run() == "Stopped watching."
    assert manager.pending() == []


def test_a_started_watch_runs_on_its_own_thread():
    finished = threading.Event()
    reader = Reader(info(lines=["Build completed"]))
    w = Watch("VS Code", read=reader, poll=0.01,
              on_done=lambda w, reason: finished.set())
    w.start()
    assert finished.wait(2.0)
    assert w.reason == "finished"


# --- routing -----------------------------------------------------------------------

@pytest.fixture
def router():
    return Router(default_registry(google=False))       # no LLM needed to parse


def test_router_accepts_the_new_tools(router):
    route = router.parse('{"tool": "notify_when_done", "args": {"app_name": "VS Code"}}')
    assert route.tool == "notify_when_done" and not route.destructive
    route = router.parse('{"tool": "cancel_watch", "args": {"app_name": "VS Code"}}')
    assert route.tool == "cancel_watch"


def test_router_rejects_bad_watch_arguments(router):
    for raw in ('{"tool": "notify_when_done", "args": {"app_name": ""}}',
                '{"tool": "notify_when_done", "args": {}}',
                '{"tool": "notify_when_done", "args": {"app_name": "' + "x" * 41 + '"}}'):
        with pytest.raises(RouteError):
            router.parse(raw)


def test_the_router_prompt_explains_watching(router):
    assert "notify_when_done" in router.system_prompt
    assert "tell me when the build is done" in router.system_prompt


def test_the_default_reader_needs_no_screen_yet():
    assert callable(default_reader())


def test_a_reminder_without_a_time_asks_instead_of_inventing_midnight():
    from red.tools.reminders import SetReminder

    class Sched:
        def add(self, *args):
            raise AssertionError("nothing should be scheduled")

    with pytest.raises(ToolError, match="When should I remind you"):
        SetReminder(lambda: Sched()).run(text="call mom")
