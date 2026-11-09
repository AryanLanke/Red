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


def test_rounded_corners_have_no_seam():
    np = pytest.importorskip("numpy")
    ys, xs = np.mgrid[0:100, 0:200].astype(np.float32)
    d = ov.rounded_edge_distance(xs, ys, 200, 100, 20)
    assert d[50, 0] == 0 and d[0, 100] == 0 and d[50, 7] == 7        # straight edges
    assert d[0, 0] < 0                                                # the square corner is outside the arc
    # Moving along the arc keeps the same distance: no diagonal crease.
    assert d[20 - 14, 20 - 14] == pytest.approx(20 - np.hypot(14, 14), abs=1e-4)
    # The field is continuous where a corner meets a straight edge.
    assert abs(float(d[5, 20]) - float(d[5, 21])) < 1e-4


def test_glass_layers():
    np = pytest.importorskip("numpy")
    d = np.array([0.0, 2.0, 6.0, 20.0, 50.0, 90.0])
    layers = ov.glass_profile(d, 84)
    assert set(layers) == set(ov.LAYERS)
    line, haze, shadow = layers["line"], layers["haze"], layers["shadow"]
    assert line[0] == pytest.approx(1.0) and line[2] < 0.01         # a fine highlight
    assert shadow[2] == pytest.approx(0.30) and shadow[0] < 0.05     # the grey edge sits just inside it
    assert haze[0] > haze[3] > haze[4] > 0 and haze[5] == 0          # milky, fading, gone by the depth
    assert haze.max() < 0.5                                          # translucent, never solid


def test_soft_distance_rounds_the_corners():
    np = pytest.importorskip("numpy")
    ys, xs = np.mgrid[0:300, 0:400].astype(np.float32)
    soft = ov.soft_edge_distance(xs, ys, 400, 300)
    assert abs(float(soft[150, 10]) - 10) < 0.5                      # about the plain distance mid-edge
    # Near a corner it is lower than the plain minimum, which curves the haze.
    assert float(soft[40, 40]) < 40 - 10
    # And it changes smoothly across the diagonal: no crease.
    row = soft[60, 40:81]
    steps = np.diff(row)
    assert np.all(np.abs(np.diff(steps)) < 0.2)


def test_glass_masks_shapes_and_inset():
    pytest.importorskip("numpy")
    masks = ov.glass_masks(0, 0, 400, 84, 400, 300)
    assert all(m.shape == (84, 400) for m in masks.values())
    assert masks["line"][int(round(ov.GLOW_INSET)), 200] >= 200      # the highlight just inside the edge
    assert masks["line"][40, 200] == 0 and masks["haze"][40, 200] > 0


def test_the_gleam_travels():
    a = ov.shine([0.12, 0.5], 0.0)
    assert a[0] == pytest.approx(1.0) and a[1] < 0.4                 # bright where the gleam is
    later = ov.shine([0.12], 3.0)[0]
    assert later < a[0]                                              # it has moved on
    assert all(0.3 <= v <= 1.0 for v in ov.shine([i / 50 for i in range(50)], 7.0))


def test_colours_flow_smoothly_and_wrap_round():
    pal = ov.GLOW_PALETTES["listening"]
    many = ov.flow_colours([0.0, 0.25, 0.999], 3.0, pal, 0.05)
    assert many[0] == ov.flow_colour(0.0, 3.0, pal, 0.05)
    assert many[1] == ov.flow_colour(0.25, 3.0, pal, 0.05)
    # 0.999 and 0.0 are neighbours round the screen's edge.
    assert max(abs(a - b) for a, b in zip(many[0], many[2])) <= 3
    # Over time the colour at one spot changes, but gently.
    a, b = ov.flow_colour(0.4, 0.0, pal, 0.05), ov.flow_colour(0.4, 0.1, pal, 0.05)
    assert a != ov.flow_colour(0.4, 5.0, pal, 0.05)
    assert max(abs(x - y) for x, y in zip(a, b)) <= 8


def test_strip_spans_join_up_round_the_edge():
    W, H, d = 1920, 1080, 48
    strips = ov.edge_strips(0, 0, W, H, d)
    spans = {side: ov.perimeter_span(side, *strips[side], W, H) for side in strips}
    P = 2 * (W + H)
    assert spans["top"] == (0.0, W / P)
    assert spans["right"][0] == pytest.approx((W + d) / P)
    assert spans["bottom"][0] == pytest.approx((2 * W + H) / P)       # its left end
    # Each span starts at the strip's own top (or left) end, where its gradient starts.
    assert spans["left"][0] == pytest.approx((2 * W + 2 * H - d) / P)  # top end, next to the top strip
    assert spans["left"][1] == pytest.approx((2 * W + H + d) / P)      # bottom end, next to the bottom strip


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
