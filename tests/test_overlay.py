"""Overlay tests. Qt runs offscreen, so no window ever appears."""

import os
import threading
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from red import overlay as ov  # noqa: E402

QtWidgets = pytest.importorskip("PySide6.QtWidgets")
from PySide6.QtCore import Qt  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication(["test"])


def pump(app, seconds=0.05):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.005)


@pytest.fixture
def overlay(app):
    o = ov.QtOverlay(hide_after=0.1)
    yield o
    o.close()
    pump(app)


def test_states_match_contract():
    assert ov.STATES == ("idle", "listening", "thinking", "confirm", "speaking", "error")
    assert set(ov.LABELS) == set(ov.COLORS) == set(ov.STATES)


def test_window_never_takes_focus(overlay):
    w = overlay.window
    flags = w.windowFlags()
    for flag in (Qt.WindowType.FramelessWindowHint, Qt.WindowType.WindowStaysOnTopHint,
                 Qt.WindowType.WindowDoesNotAcceptFocus, Qt.WindowType.Tool,
                 Qt.WindowType.WindowTransparentForInput):
        assert flags & flag, flag
    assert w.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
    assert w.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)


def test_starts_hidden(overlay):
    assert not overlay.window.isVisible()


@pytest.mark.parametrize("state", [s for s in ov.STATES if s != "idle"])
def test_every_state_shows_text(app, overlay, state):
    overlay.set_state(state, f"text for {state}")
    pump(app)
    w = overlay.window
    assert w.isVisible()
    assert (w.state, w.text) == (state, f"text for {state}")
    assert w.title.text() == ov.LABELS[state]
    assert w.body.text() == f"text for {state}"


def test_set_state_from_another_thread(app, overlay):
    t = threading.Thread(target=overlay.set_state, args=("thinking", "from a thread"))
    t.start()
    t.join()
    pump(app)
    assert overlay.window.text == "from a thread"
    assert overlay.window.isVisible()


def test_idle_hides_after_a_delay(app, overlay):
    overlay.set_state("speaking", "Done.")
    pump(app)
    overlay.set_state("idle")
    pump(app, 0.02)
    assert overlay.window.isVisible()        # not yet
    pump(app, 0.3)
    assert not overlay.window.isVisible()


def test_new_state_cancels_hiding(app, overlay):
    overlay.set_state("speaking", "x")
    overlay.set_state("idle")
    pump(app, 0.02)
    overlay.set_state("listening")
    pump(app, 0.3)
    assert overlay.window.isVisible()


def test_idle_while_hidden_stays_hidden(app, overlay):
    overlay.set_state("idle")
    pump(app)
    assert not overlay.window.isVisible()


def test_sits_in_bottom_right_corner(app, overlay):
    overlay.set_state("speaking", "A reply that is long enough to wrap onto a second line "
                                  "so the height changes.")
    pump(app)
    area = app.primaryScreen().availableGeometry()
    g = overlay.window.frameGeometry()
    assert g.right() == area.right() - ov.MARGIN
    assert g.bottom() == area.bottom() - ov.MARGIN


def test_long_text_is_cut(app, overlay):
    overlay.set_state("speaking", "x" * 5000)
    pump(app)
    assert len(overlay.window.text) == ov.MAX_TEXT
    assert overlay.window.text.endswith("…")


def test_unknown_state_is_rejected(overlay):
    with pytest.raises(ValueError):
        overlay.set_state("dancing")


def test_set_state_after_close_is_ignored(app, overlay):
    overlay.close()
    overlay.set_state("speaking", "late")   # no error


def test_run_with_overlay_runs_worker_off_the_main_thread(app):
    seen = {}

    def worker(o):
        seen["thread"] = threading.current_thread()
        seen["type"] = type(o)
        o.set_state("speaking", "hello")
        o.set_state("idle")

    assert ov.run_with_overlay(worker, hide_after=0.01) == 0
    assert seen["thread"] is not threading.main_thread()
    assert seen["type"] is ov.QtOverlay


def test_run_with_overlay_reports_worker_errors(app):
    def worker(o):
        raise RuntimeError("boom")

    assert ov.run_with_overlay(worker, hide_after=0.01) == 1


def test_falls_back_to_notifications_without_qt(monkeypatch):
    def no_qt(hide_after):
        raise ImportError("No module named 'PySide6'")

    monkeypatch.setattr(ov, "_start_qt", no_qt)
    calls = []
    fallback = ov.NotificationOverlay(runner=lambda cmd, **kw: calls.append((cmd, kw)))
    seen = {}

    def worker(o):
        seen["overlay"] = o
        o.set_state("speaking", "Opening Downloads.")

    assert ov.run_with_overlay(worker, fallback=lambda: fallback) == 0
    assert seen["overlay"] is fallback
    assert len(calls) == 1


class TestNotificationOverlay:
    def make(self):
        calls = []
        return ov.NotificationOverlay(runner=lambda cmd, **kw: calls.append((cmd, kw))), calls

    def test_only_important_states_notify(self):
        o, calls = self.make()
        for state in ("idle", "listening", "thinking"):
            o.set_state(state, "something")
        assert calls == []
        for state in ("confirm", "speaking", "error"):
            o.set_state(state, "something")
        assert len(calls) == 3

    def test_empty_text_skips_except_errors(self):
        o, calls = self.make()
        o.set_state("speaking", "")
        assert calls == []
        o.set_state("error", "")
        assert calls[0][1]["env"]["RED_TOAST_BODY"] == "Something went wrong."

    def test_text_goes_through_env_not_the_command_line(self):
        o, calls = self.make()
        nasty = "'; Remove-Item C:\\ -Recurse; <b>&amp;"
        o.set_state("speaking", nasty)
        cmd, kw = calls[0]
        assert cmd == ov.toast_command()
        assert all(nasty not in part for part in cmd)
        assert kw["env"]["RED_TOAST_BODY"] == nasty
        assert kw["stdin"] is ov.subprocess.DEVNULL

    def test_runner_failure_is_not_fatal(self):
        def broken(cmd, **kw):
            raise FileNotFoundError("powershell.exe")

        ov.NotificationOverlay(runner=broken).set_state("error", "x")

    def test_unknown_state_is_rejected(self):
        o, _ = self.make()
        with pytest.raises(ValueError):
            o.set_state("nope")


def test_console_overlay():
    lines = []
    ov.ConsoleOverlay(write=lines.append).set_state("thinking", "open Downloads")
    assert lines == ["[thinking] open Downloads"]


def test_demo_runs_offscreen(monkeypatch, app):
    monkeypatch.setattr(ov, "HIDE_AFTER_IDLE_SECONDS", 0.01)
    assert ov.main(["--seconds", "0"]) == 0
