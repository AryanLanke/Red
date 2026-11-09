"""Reminders from red.scheduler (Track G) reach the voice and typed modes. Uses fakes only."""

import sys
import threading
import types

from red import __main__ as cli
from test_voice_app import FakeListener, make_app, world  # noqa: F401 (fixture)


class FakeScheduler:
    def __init__(self):
        self.on_due = None


def _fake_module(monkeypatch, factory):
    module = types.ModuleType("red.scheduler")
    module.default_scheduler = factory
    monkeypatch.setitem(sys.modules, "red.scheduler", module)


def test_without_scheduler_module_reminders_are_skipped(monkeypatch):
    monkeypatch.setitem(sys.modules, "red.scheduler", None)   # import raises ImportError
    assert cli.attach_reminders(print) is None


def test_attach_sets_on_due(monkeypatch):
    sched = FakeScheduler()
    _fake_module(monkeypatch, lambda: sched)
    assert cli.attach_reminders(print) is sched and sched.on_due is print


def test_broken_scheduler_does_not_stop_red(monkeypatch):
    def boom():
        raise RuntimeError("bad reminders file")
    _fake_module(monkeypatch, boom)
    assert cli.attach_reminders(print) is None


def test_voice_mode_attaches_and_detaches(world):
    sched = FakeScheduler()

    def attach(on_due):
        sched.on_due = on_due
        return sched
    app, *_ = make_app(world, attach=attach)
    stop = threading.Event()
    stop.set()
    app.run(stop)
    assert app.reminders is sched
    assert sched.on_due is None          # cleared on shutdown


def test_announce_speaks_with_wakeword_paused(world):
    app, speaker, overlay, _, out = make_app(world)
    app.start_listener()
    app.announce("Time to call mom.")
    assert speaker.said == ["Time to call mom."]
    assert app.listener.pauses == 1
    assert ("speaking", "Time to call mom.") in overlay.states
    assert overlay.states[-1] == ("idle", "Time to call mom.")
    assert "Red (reminder): Time to call mom." in out


def test_announce_waits_for_a_command_in_progress(world):
    app, speaker, *_ = make_app(world)
    app.start_listener()
    app._turn.acquire()                  # as if a command were being handled
    t = threading.Thread(target=app.announce, args=("Tea is ready.",))
    t.start()
    t.join(0.2)
    assert speaker.said == []            # still waiting
    app._turn.release()
    t.join(2)
    assert speaker.said == ["Tea is ready."]


def test_announce_survives_speaker_failure(world):
    app, speaker, overlay, *_ = make_app(world)

    def broken(text, block=True):
        raise OSError("no speakers")
    speaker.say = broken
    app.announce("Stand up.")            # no listener started: still works
    assert overlay.states[-1] == ("idle", "Stand up.")


def test_typed_mode_prints_reminders(monkeypatch, capsys):
    cli._print_reminder("Stretch.")
    assert "Red (reminder): Stretch." in capsys.readouterr().out
