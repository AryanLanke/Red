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
NIGHT = datetime(2026, 11, 9, 22, 37)


# --- small talk ---------------------------------------------------------------

@pytest.mark.parametrize("said, expected", [
    ("Hello.", "Morning! What's up?"),
    ("Hey Red!", "Morning! What's up?"),
    ("Good evening", "Good evening! What's up?"),   # mirrors your word
    ("Thanks, Red.", "Anytime!"),
    ("What’s your name?", "I'm Red. I live on your PC: part friend, part helper."),
    ("Are you there?", "Yep, right here."),
    ("Good night", "Night! Sleep well."),
])
def test_small_talk_gets_an_instant_reply(said, expected):
    assert quick_reply(said, MORNING) == expected


def test_greeting_follows_the_time_of_day():
    assert quick_reply("hi", EVENING) == "Evening! What's up?"
    assert quick_reply("hi", NIGHT) == "Hey, still up? What's going on?"
    assert quick_reply("good evening", NIGHT) == "Good evening! What's up?"


def test_small_talk_never_sounds_like_a_help_desk():
    from red.smalltalk import _RULES
    for _, reply in _RULES:
        for when in (MORNING, EVENING, NIGHT):
            line = reply(when)
            assert "assist" not in line.lower() and "What can I do for you" not in line


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


def test_how_are_you_goes_to_the_conversation_not_a_canned_line():
    # The friend persona (red.chat) answers these, so they're not quick replies any more.
    for said in ("How are you?", "What are you doing right now?", "What's going on in your mind?"):
        assert quick_reply(said, MORNING) is None


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
    assert s.overlay == DEFAULT_OVERLAY == "companion"
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
                                     "quick_silence": 0.8,
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


def test_keep_model_warm_reloads_soon_after_the_laptop_wakes(monkeypatch):
    """A sleep makes the wall clock jump: the next warm comes within one short check, not `every`."""
    llm, stop = WarmLLM(), threading.Event()
    clock = [1000.0]
    monkeypatch.setattr(cli.time, "time", lambda: clock[0])
    monkeypatch.setattr(cli, "RESUME_CHECK_SECONDS", 0.01)
    thread = cli.keep_model_warm(llm, stop, every=3600)
    assert llm.called.wait(2)
    first = llm.calls
    clock[0] += 4 * 3600                                  # the laptop slept 4 hours
    deadline = time.monotonic() + 2
    while llm.calls == first and time.monotonic() < deadline:
        time.sleep(0.01)
    stop.set()
    thread.join(2)
    assert llm.calls > first


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
                     {"model": "qwen2.5:7b", "keep_alive": "5m", "options": {"num_ctx": 4096}})]


def test_ollama_warm_keeps_the_routers_context(monkeypatch):
    """The keep-warm ping must load the model at the size real calls use, or the next one reloads it."""
    from red import llm
    sent = []
    monkeypatch.setattr(llm, "_post_json", lambda url, body, **kw: sent.append((url, body)) or {})
    client = llm.OllamaClient("http://127.0.0.1:11434", "qwen3.5:4b", keep_alive="5m")
    client.options["num_ctx"] = 8192                  # what Router's fit_context sets
    client.warm()
    chat = client._body("s", "u", {}, 0.0, None, None, stream=False)
    assert sent[0][1]["options"]["num_ctx"] == chat["options"]["num_ctx"] == 8192


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


def test_edge_falloff_is_bright_at_the_edge_and_ends_at_depth():
    np = pytest.importorskip("numpy")
    assert ov.edge_falloff(0.0, 56) == pytest.approx(1.0)
    assert ov.edge_falloff(56, 56) == 0.0
    d = np.array([0.0, 10.0, 20.0, 40.0, 56.0], dtype=np.float32)
    s = ov.edge_falloff(d, 56)
    assert s[0] > s[1] > s[2] > s[3] > s[4]              # fades smoothly
    assert s[4] == 0.0                                   # and ends exactly at the depth


def test_glow_mask_fades_from_each_edge():
    pytest.importorskip("numpy")
    mask = ov.glow_mask(0, 0, 400, 56, 400, 300, 56)
    assert mask.shape == (56, 400)
    assert mask[0, 200] == 255                           # brightest right at the edge
    assert mask[55, 200] == 0                            # nothing at the depth
    assert 0 < mask[28, 200] < 255                       # a soft middle


def test_glow_mask_corners_blend_where_strips_meet():
    pytest.importorskip("numpy")
    top = ov.glow_mask(0, 0, 400, 56, 400, 300, 56)
    left = ov.glow_mask(0, 56, 56, 188, 400, 300, 56)
    assert left[0, 0] == top[0, 0] == 255                # the seam is seamless


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
        pump(app, ov.GLOW_FADE_IN + 0.3)
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
