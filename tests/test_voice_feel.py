"""Small talk, end-of-speech and overlay settings, the screen-edge glow, and keeping the model warm."""

import os
import threading
import time
from datetime import datetime

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from red import __main__ as cli  # noqa: E402
from red import overlay as ov  # noqa: E402
from red.config import (DEFAULT_END_SILENCE, DEFAULT_MAX_COMMAND, DEFAULT_OVERLAY,  # noqa: E402
                        load_settings)
from red.smalltalk import is_goodbye, normalize, quick_reply  # noqa: E402

MORNING = datetime(2026, 11, 9, 9, 0)
EVENING = datetime(2026, 11, 9, 20, 0)


# --- small talk ---------------------------------------------------------------

@pytest.mark.parametrize("said, expected", [
    ("What are you doing right now?", "Just here on your PC, listening for you. What do you need?"),
    ("what are you up to", "Just here on your PC, listening for you. What do you need?"),
    ("How are you?", "I'm doing great, thanks for asking. What can I do for you?"),
    ("Hello.", "Good morning! What can I do for you?"),
    ("Hey Red!", "Good morning! What can I do for you?"),
    ("Good evening", "Good morning! What can I do for you?"),   # greets by the clock
    ("Thanks, Red.", "You're welcome!"),
    ("What’s your name?", "I'm Red, your assistant on this PC."),
    ("Are you there?", "Yes, I'm here."),
    ("Good night", "Good night! Sleep well."),
])
def test_small_talk_gets_an_instant_reply(said, expected):
    assert quick_reply(said, MORNING) == expected


def test_greeting_follows_the_time_of_day():
    assert quick_reply("hi", EVENING) == "Good evening! What can I do for you?"


@pytest.mark.parametrize("said", [
    "Hey, open my downloads folder.",
    "What time is it?",
    "What are you doing tomorrow at 3 pm, remind me",
    "Shut down in 2 hours.",
    "Thanks, now open YouTube.",
    "",
    "...",
])
def test_commands_are_not_small_talk(said):
    assert quick_reply(said, MORNING) is None


def test_normalize():
    assert normalize("  What’s   UP, Red?! ") == "what's up red"
    assert normalize("How are you, please?") == "how are you"


def test_small_talk_never_claims_to_see_the_screen():
    reply = quick_reply("what are you doing right now", MORNING)
    assert "screen" not in reply.lower()


@pytest.mark.parametrize("said", ["No.", "Nope", "No, that's all.", "Nothing else, thanks.", "That's it", "I'm good",
                                  "No thank you!", "Never mind", "Goodbye, Red", "Stop"])
def test_goodbyes(said):
    assert is_goodbye(said)


@pytest.mark.parametrize("said", ["Open YouTube", "No, open Downloads", "Notepad", "Stop the music", "Cancel the shutdown",
                                  "", "What's the weather"])
def test_real_commands_are_not_goodbyes(said):
    assert not is_goodbye(said)


# --- settings -----------------------------------------------------------------

@pytest.fixture
def clean_env(monkeypatch):
    for name in ("RED_OVERLAY", "RED_END_SILENCE", "RED_MAX_COMMAND_SECONDS", "RED_FOLLOW_UP_SECONDS"):
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def test_new_settings_defaults(clean_env, tmp_path):
    s = load_settings(tmp_path)
    assert s.overlay == DEFAULT_OVERLAY == "glow"
    assert s.end_silence_seconds == DEFAULT_END_SILENCE == 1.5
    assert s.max_command_seconds == DEFAULT_MAX_COMMAND == 20.0
    assert s.follow_up_seconds == 7.0


def test_new_settings_from_env(clean_env, tmp_path):
    clean_env.setenv("RED_OVERLAY", "Card")
    clean_env.setenv("RED_END_SILENCE", "2.25")
    clean_env.setenv("RED_MAX_COMMAND_SECONDS", "30")
    s = load_settings(tmp_path)
    assert (s.overlay, s.end_silence_seconds, s.max_command_seconds) == ("card", 2.25, 30.0)


@pytest.mark.parametrize("name, value", [
    ("RED_OVERLAY", "sparkles"),
    ("RED_END_SILENCE", "0.1"),
    ("RED_END_SILENCE", "long"),
    ("RED_MAX_COMMAND_SECONDS", "999"),
])
def test_bad_settings_are_refused(clean_env, tmp_path, name, value):
    clean_env.setenv(name, value)
    with pytest.raises(ValueError, match=name):
        load_settings(tmp_path)


def test_load_voice_uses_the_end_silence_settings(clean_env, tmp_path):
    pytest.importorskip("faster_whisper")
    pytest.importorskip("piper")
    clean_env.setenv("RED_END_SILENCE", "2")
    clean_env.setenv("RED_MAX_COMMAND_SECONDS", "25")
    voice = cli.load_voice(load_settings(tmp_path))
    assert voice.record.keywords == {"max_seconds": 25.0, "silence_seconds": 2.0,
                                     "start_timeout": cli.START_TIMEOUT_SECONDS}


# --- keeping the model warm ---------------------------------------------------

class WarmLLM:
    def __init__(self, fail=False):
        self.calls = 0
        self.fail = fail
        self.called = threading.Event()

    def warm(self):
        self.calls += 1
        self.called.set()
        if self.fail:
            raise OSError("Ollama is busy")


def test_keep_model_warm_loads_now_and_stops():
    llm, stop = WarmLLM(), threading.Event()
    thread = cli.keep_model_warm(llm, stop, every=0.01)
    assert llm.called.wait(2)
    time.sleep(0.05)
    stop.set()
    thread.join(2)
    assert not thread.is_alive()
    assert llm.calls >= 2


def test_keep_model_warm_primes_once_after_loading():
    llm, stop, primed = WarmLLM(), threading.Event(), []
    thread = cli.keep_model_warm(llm, stop, every=0.01,
                                 prime=lambda: primed.append(llm.calls))
    assert llm.called.wait(2)
    time.sleep(0.08)
    stop.set()
    thread.join(2)
    assert primed == [1]          # once, right after the first load
    assert llm.calls >= 2


def test_keep_model_warm_survives_errors():
    llm, stop = WarmLLM(fail=True), threading.Event()
    thread = cli.keep_model_warm(llm, stop, every=0.01)
    assert llm.called.wait(2)
    time.sleep(0.05)
    stop.set()
    thread.join(2)
    assert llm.calls >= 2


def test_keep_model_warm_skips_clients_without_warm():
    assert cli.keep_model_warm(object(), threading.Event()) is None


@pytest.mark.parametrize("value, zero", [("0", True), ("0m", True), (" 0S ", True),
                                         ("5m", False), ("-1", False)])
def test_keep_alive_zero(value, zero):
    assert cli._keep_alive_is_zero(value) is zero


def test_ollama_warm_request(monkeypatch):
    from red import llm
    sent = []
    monkeypatch.setattr(llm, "_post_json", lambda url, body, **kw: sent.append((url, body)) or {})
    llm.OllamaClient("http://127.0.0.1:11434", "qwen2.5:7b", keep_alive="5m").warm()
    assert sent == [("http://127.0.0.1:11434/api/generate",
                     {"model": "qwen2.5:7b", "keep_alive": "5m"})]


# --- glow geometry and timing (no Qt) ----------------------------------------

def test_edge_strips_frame_the_screen_without_overlap():
    strips = ov.edge_strips(0, 0, 1920, 1080, 44)
    assert strips == {"top": (0, 0, 1920, 44), "bottom": (0, 1036, 1920, 44),
                      "left": (0, 44, 44, 992), "right": (1876, 44, 44, 992)}
    area = sum(w * h for _, _, w, h in strips.values())
    assert area == 1920 * 1080 - (1920 - 88) * (1080 - 88)   # exactly the frame


def test_edge_strips_on_a_second_monitor_and_tiny_screens():
    assert ov.edge_strips(1920, -200, 1280, 720, 40)["right"] == (3160, -160, 40, 640)
    tiny = ov.edge_strips(0, 0, 50, 30, 44)
    assert tiny["top"][3] == 15 and tiny["left"][3] == 0


def test_fades():
    assert ov.step_toward(0.0, 1.0, ov.GLOW_FADE_IN / 2) == pytest.approx(0.5)
    assert ov.step_toward(0.9, 1.0, 1.0) == 1.0
    assert ov.step_toward(1.0, 0.0, ov.GLOW_FADE_OUT / 2) == pytest.approx(0.5)
    assert ov.step_toward(0.1, 0.0, 1.0) == 0.0


def test_glow_alpha_breathes_within_bounds():
    values = [ov.glow_alpha(1.0, "listening", t / 50) for t in range(100)]
    assert 0.6 <= min(values) < max(values) <= 1.0
    assert ov.glow_alpha(0.0, "listening", 0.3) == 0.0


def test_glow_falloff_is_bright_at_the_edge_and_gone_at_depth():
    np = pytest.importorskip("numpy")
    values = ov.edge_falloff(np.array([0, 5, 15, 30, 56, 80]), 56)
    assert values[0] == pytest.approx(1.0)
    assert all(a > b for a, b in zip(values[:5], values[1:5]))   # always fading
    assert values[4] == 0.0 and values[5] == 0.0


def test_glow_mask_corners_blend():
    pytest.importorskip("numpy")
    top = ov.glow_mask(0, 0, 200, 40, 200, 100, 40)       # the top strip of a 200x100 screen
    assert top.shape == (40, 200)
    assert top[0, 100] == 255                              # the very edge
    assert top[39, 100] < 10                               # faded by the strip's inner side
    # Near the left end of the top strip, the left edge glows too.
    assert top[30, 0] == 255
    assert top[30, 0] > top[30, 100]


def test_every_active_state_has_a_glow():
    active = set(ov.STATES) - {"idle"}
    assert set(ov.GLOW_PALETTES) == set(ov.GLOW_SPEED) == set(ov.GLOW_PULSE) == active


# --- glow window (Qt offscreen) ---------------------------------------------

QtWidgets = pytest.importorskip("PySide6.QtWidgets")


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication(["test"])


def pump(app, seconds):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.005)


def test_glow_appears_on_listening_and_fades_out_on_idle(app):
    glow = ov.GlowOverlay()
    window = glow.window
    try:
        assert not window.isVisible()
        glow.set_state("listening", "")
        pump(app, 0.4)
        assert window.isVisible()
        assert window.level == pytest.approx(1.0)
        assert window.palette == ov.GLOW_PALETTES["listening"]
        glow.set_state("thinking", "open Downloads")
        pump(app, 0.1)
        assert window.palette == ov.GLOW_PALETTES["thinking"]
        # Strips sit on the screen edges and never in the middle.
        screen = app.primaryScreen().geometry()
        for strip in window.strips.values():
            g = strip.geometry()
            touches_edge = (g.left() == screen.left() or g.right() == screen.right()
                            or g.top() == screen.top() or g.bottom() == screen.bottom())
            assert touches_edge
            assert min(g.width(), g.height()) <= ov.GLOW_DEPTH
        glow.set_state("idle", "Opening Downloads.")
        pump(app, ov.GLOW_FADE_OUT + 0.4)
        assert not window.isVisible()
        assert not window.timer.isActive()   # no animation runs while idle
    finally:
        glow.close()
        pump(app, 0.05)


def test_glow_strips_ignore_the_mouse_and_focus(app):
    from PySide6.QtCore import Qt
    glow = ov.GlowOverlay()
    try:
        for strip in glow.window.strips.values():
            flags = strip.windowFlags()
            assert flags & Qt.WindowType.WindowTransparentForInput
            assert flags & Qt.WindowType.WindowDoesNotAcceptFocus
            assert flags & Qt.WindowType.WindowStaysOnTopHint
    finally:
        glow.close()


def test_run_with_overlay_glow_style(app):
    seen = []

    def worker(overlay):
        seen.append(type(overlay).__name__)
        overlay.set_state("listening")
        overlay.set_state("idle")

    assert ov.run_with_overlay(worker, style="glow") == 0
    assert seen == ["GlowOverlay"]


def test_run_with_overlay_off_and_notify_styles():
    seen = []
    assert ov.run_with_overlay(lambda o: seen.append(type(o).__name__), style="off") == 0

    class Fallback(ov.Overlay):
        def set_state(self, state, text=""):
            pass

    assert ov.run_with_overlay(lambda o: seen.append(type(o).__name__), style="notify",
                               fallback=Fallback) == 0
    assert seen == ["NullOverlay", "Fallback"]
