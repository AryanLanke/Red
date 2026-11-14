"""The companion: frame choice, the mouth meter, pickup clips and the window. Qt runs offscreen."""

import json
import os
import re
import wave

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from red import avatar  # noqa: E402
from red.avatar import (BLINK_EVERY, BLINK_LENGTH, Look, MouthMeter, MouthPlayer,  # noqa: E402
                        blinking, clip_paths, emotion_from_text, load_sprites, make_clips, mark_for,
                        meter_speaker, pick_frame)
from red.config import load_settings  # noqa: E402

PEEK = ["peek_idle", "peek_idle_blink", "peek_talk_1", "peek_talk_2", "peek_talk_3", "peek_notice",
        "peek_listen", "peek_listen_blink", "peek_think", "peek_think_blink", "peek_happy",
        "peek_happy_talk_1", "peek_happy_talk_2", "peek_laugh", "peek_laugh_2", "peek_sad", "peek_sad_talk",
        "peek_angry", "peek_angry_talk", "peek_surprised", "peek_shy", "peek_wave_1", "peek_wave_2",
        "peek_wave_3", "peek_sleep"]
BODY = ["body_drag_1", "body_drag_2", "body_drag_3", "body_drag_fun", "body_drop"]
CORNERS = [n.replace("peek_", "cornerR_") for n in PEEK] + [n.replace("peek_", "cornerL_") for n in PEEK]
TOP = [n.replace("peek_", "top_") for n in PEEK]
TOP_CORNERS = [n.replace("peek_", "topL_") for n in PEEK] + [n.replace("peek_", "topR_") for n in PEEK]


def make_sprites(folder, names=None):
    """A tiny sprite folder like finish.py writes: solid pictures, marks, frames.json."""
    from PIL import Image
    folder.mkdir(parents=True, exist_ok=True)
    names = names or PEEK + BODY + CORNERS + TOP + TOP_CORNERS
    sets = {}
    for set_name, size, head in (("peek", (100, 80), [50, 30]), ("cornerR", (70, 90), [30, 30]),
                                 ("cornerL", (70, 90), [40, 30]), ("top", (100, 80), [50, 50]),
                                 ("topL", (70, 90), [40, 60]), ("topR", (70, 90), [30, 60]),
                                 ("body", (80, 200), [40, 50])):
        frames = []
        for name in names:
            if not name.startswith(set_name + "_"):
                continue
            Image.new("RGBA", size, (200, 80, 80, 255)).save(folder / f"{name}.png")
            frames.append({"name": name, "state": None, "emotion": None, "marks": {"head": head}})
        sets[set_name] = {"size": list(size), "frames": frames}
    (folder / "frames.json").write_text(json.dumps({"model": "test", "pxPerMetre": 300, "sets": sets}))
    return folder


# --- frames on disk -------------------------------------------------------------------------------

def test_load_sprites(tmp_path):
    sprites = load_sprites(make_sprites(tmp_path / "red"))
    assert sprites.px_per_metre == 300
    assert sprites.sizes == {"peek": (100, 80), "cornerR": (70, 90), "cornerL": (70, 90), "top": (100, 80),
                             "topL": (70, 90), "topR": (70, 90), "body": (80, 200)}
    assert (sprites.name, sprites.voice) == ("Red", None)       # Red speaks with RED_VOICE
    assert sprites.frames["body_drop"].set == "body"
    assert sprites.frames["peek_idle"].marks["head"] == [50, 30]


def test_any_installed_model_is_a_companion(tmp_path):
    models = tmp_path / "models"
    make_sprites(models / "companion" / "red")
    bruno = make_sprites(models / "companion" / "bruno")
    meta = json.loads((bruno / "frames.json").read_text())
    meta.update(name="Bruno", voice="am_fenrir")
    (bruno / "frames.json").write_text(json.dumps(meta))
    (models / "companion" / "empty").mkdir()
    assert avatar.available_companions(models) == {"bruno": "Bruno", "red": "Red"}
    assert load_sprites(bruno).voice == "am_fenrir"
    assert avatar.available_companions(tmp_path / "nothing") == {}


def test_corners():
    have = {"peek_idle", "cornerR_idle", "cornerL_idle", "peek_talk_1"}.__contains__
    assert avatar.frame_for_side("peek_idle", "right", have) == "cornerR_idle"
    assert avatar.frame_for_side("peek_idle", "left", have) == "cornerL_idle"
    assert avatar.frame_for_side("peek_idle", "edge", have) == "peek_idle"
    assert avatar.frame_for_side("peek_talk_1", "right", have) == "peek_talk_1"   # no corner frame: the edge one
    assert avatar.frame_for_side("body_drag_1", "right", have) == "body_drag_1"
    assert avatar.side_for(1900, 0, 1919, 180) == "right"
    assert avatar.side_for(100, 0, 1919, 180) == "left"
    assert avatar.side_for(900, 0, 1919, 180) == "edge"
    assert avatar.side_for(900, 0, 1919, 180, y=60, top=0) == "top"
    assert avatar.side_for(1900, 0, 1919, 180, y=60, top=0) == "top-right"   # near the top and a side
    assert avatar.side_for(100, 0, 1919, 180, y=60, top=0) == "top-left"
    assert avatar.side_for(1900, 0, 1919, 180, y=600, top=0) == "right"      # near a side, lower down
    assert avatar.side_for(900, 0, 1919, 180, y=600, top=0) == "edge"
    assert avatar.frame_for_side("peek_sad", "top-left") == "topL_sad"
    assert avatar.frame_for_side("peek_sad", "top-right") == "topR_sad"
    assert avatar.frame_for_side("peek_sad", "top") == "top_sad"


def test_load_sprites_needs_peek_idle(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_sprites(tmp_path / "missing")
    with pytest.raises(FileNotFoundError):
        load_sprites(make_sprites(tmp_path / "x", names=["peek_talk_1"]))


# --- which frame ---------------------------------------------------------------------------------

AWAKE = 0.5    # a moment that isn't a blink (checked below)


def test_blinks_are_short_and_regular():
    assert not blinking(AWAKE)
    steps = np.arange(0, 120, 0.01)
    share = sum(blinking(t) for t in steps) / len(steps)
    assert share == pytest.approx(BLINK_LENGTH / BLINK_EVERY, rel=0.25)


def test_idle_and_blink():
    blink_at = next(t for t in np.arange(0, 10, 0.01) if blinking(t))
    assert pick_frame(Look(), AWAKE) == "peek_idle"
    assert pick_frame(Look(), blink_at) == "peek_idle_blink"
    assert pick_frame(Look(state="listening"), blink_at) == "peek_listen_blink"
    assert pick_frame(Look(state="thinking"), AWAKE) == "peek_think"
    assert pick_frame(Look(state="confirm"), AWAKE) == "peek_think"


@pytest.mark.parametrize("emotion, closed, half, open_", [
    (None, "peek_idle", "peek_talk_1", "peek_talk_2"),
    ("happy", "peek_happy", "peek_happy_talk_1", "peek_happy_talk_2"),
    ("sad", "peek_sad", "peek_sad_talk", "peek_sad_talk"),
    ("angry", "peek_angry", "peek_angry_talk", "peek_angry_talk"),
])
def test_mouth_follows_the_voice(emotion, closed, half, open_):
    def at(mouth, now=0.3):         # 0.3 s: not one of the moments an "oh" replaces the "ah"
        return pick_frame(Look(state="speaking", emotion=emotion, mouth=mouth), now)
    assert at(0.0) == closed
    assert at(0.3) == half
    assert at(0.9) == open_
    if emotion is None:
        assert at(0.9, now=0.0) == "peek_talk_3"


def test_emotions_when_quiet():
    for emotion, frame in (("happy", "peek_happy"), ("sad", "peek_sad"), ("angry", "peek_angry"),
                           ("surprised", "peek_surprised"), ("shy", "peek_shy")):
        assert pick_frame(Look(emotion=emotion), AWAKE) == frame


def test_sleep_greeting_and_error():
    assert pick_frame(Look(state="sleeping"), 0.0) == "peek_sleep"
    assert pick_frame(Look(state="error"), 0.0) == "peek_shy"
    waves = {pick_frame(Look(state="greeting", since=0.0), t) for t in np.arange(0, 1, 0.05)}
    assert waves == {"peek_wave_1", "peek_wave_2", "peek_wave_3"}


def test_carried_and_dropped():
    frames = {pick_frame(Look(dragging=True), t) for t in np.arange(0, 1, 0.05)}
    assert frames == {"body_drag_1", "body_drag_2", "body_drag_3"}
    assert pick_frame(Look(dragging=True, emotion="happy"), 0.0) == "body_drag_fun"
    assert pick_frame(Look(falling=True), 0.0) == "body_drop"


def test_missing_frames_fall_back():
    have = {"peek_idle", "peek_listen"}
    assert pick_frame(Look(state="speaking", mouth=1.0), 0.0, have.__contains__) == "peek_idle"
    blink_at = next(t for t in np.arange(0, 10, 0.01) if blinking(t))
    assert pick_frame(Look(state="listening"), blink_at, have.__contains__) == "peek_listen"


def test_marks_over_the_head():
    assert mark_for(Look(state="sleeping")) == "zzz"
    assert mark_for(Look(state="thinking")) == "dots"
    assert mark_for(Look(emotion="sad")) == "tear"
    assert mark_for(Look(emotion="angry")) == "anger"
    assert mark_for(Look()) is None
    assert mark_for(Look(dragging=True, emotion="sad")) is None


@pytest.mark.parametrize("text, feeling", [
    ("Hey! Good to see you.", "greeting"),
    ("Good morning. Coffee first?", "greeting"),
    ("Haha, fair enough.", "laugh"),
    ("Sorry, I couldn't find that folder.", "sad"),
    ("Whoa, that's a big file.", "surprised"),
    ("Oops, my bad.", "shy"),
    ("Done. The build is green.", "happy"),
    ("Opening Downloads.", None),
    ("", None),
])
def test_emotion_from_text(text, feeling):
    assert emotion_from_text(text) == feeling


# --- the mouth meter -------------------------------------------------------------------------------

class Clock:
    def __init__(self, t=100.0):
        self.t = t

    def __call__(self):
        return self.t


def test_mouth_meter_follows_loudness():
    clock = Clock()
    meter = MouthMeter(clock)
    rate = 24_000
    loud = 0.5 * np.sin(np.arange(rate) * 2 * np.pi * 220 / rate)
    audio = np.concatenate([loud, np.zeros(rate)]).astype(np.float32)
    meter.start(audio, rate)
    clock.t += 0.5
    assert meter.level() > 0.8
    clock.t += 1.0
    assert meter.level() == 0.0           # the silent second
    clock.t += 5.0
    assert meter.level() == 0.0           # finished
    meter.start(audio, rate)
    meter.stop()
    assert meter.level() == 0.0


class FakePlayer:
    def __init__(self):
        self.calls = []

    def play(self, audio, rate):
        self.calls.append(("play", len(audio), rate))

    def wait(self):
        self.calls.append(("wait",))

    def stop(self):
        self.calls.append(("stop",))


class FakeSpeaker:
    def __init__(self):
        self.player = FakePlayer()
        self.fallback = type("Fallback", (), {})()
        self.fallback.player = self.player


def test_meter_wraps_the_speakers_player_once():
    speaker = FakeSpeaker()
    inner = speaker.player
    meter = MouthMeter(Clock())
    meter_speaker(speaker, meter)
    assert isinstance(speaker.player, MouthPlayer)
    assert speaker.fallback.player is speaker.player
    meter_speaker(speaker, meter)
    assert speaker.player.inner is inner          # not wrapped twice
    speaker.player.play(np.ones(2400, np.float32) * 0.3, 24_000)
    speaker.player.wait()
    speaker.player.stop()
    assert [c[0] for c in inner.calls] == ["play", "wait", "stop"]


# --- pickup clips ----------------------------------------------------------------------------------

def test_make_clips_once(tmp_path):
    said = []

    def synthesize(text, voice):
        said.append((text, voice))
        return np.full(2400, 0.2, np.float32), 24_000

    made = make_clips(tmp_path, "af_bella", synthesize)
    assert made == len(avatar.PICKUP_LINES) + len(avatar.DROP_LINES)
    assert {v for _, v in said} == {"af_bella"}
    path = clip_paths(tmp_path, "af_bella", "pickup")[0]
    with wave.open(str(path)) as w:
        assert (w.getframerate(), w.getnchannels(), w.getnframes()) == (24_000, 1, 2400)
    assert make_clips(tmp_path, "af_bella", synthesize) == 0     # already there


# --- settings --------------------------------------------------------------------------------------

def test_companion_settings(monkeypatch, tmp_path):
    for name in ("RED_OVERLAY", "RED_COMPANION", "RED_COMPANION_SIZE"):
        monkeypatch.delenv(name, raising=False)
    s = load_settings(tmp_path)
    assert (s.overlay, s.companion, s.companion_size) == ("companion", None, "medium")
    monkeypatch.setenv("RED_COMPANION", "Remy")
    monkeypatch.setenv("RED_COMPANION_SIZE", "large")
    s = load_settings(tmp_path)
    assert (s.companion, s.companion_size) == ("remy", "large")
    monkeypatch.setenv("RED_COMPANION", "bruno")              # any installed model
    assert load_settings(tmp_path).companion == "bruno"
    monkeypatch.setenv("RED_COMPANION", "not a name!")
    with pytest.raises(ValueError):
        load_settings(tmp_path)


# --- the window ------------------------------------------------------------------------------------

def as_peek(name):
    """A frame name with the corner taken out: cornerR_happy -> peek_happy."""
    return re.sub(r"^corner[LR]_", "peek_", name)


@pytest.fixture
def app():
    from PySide6 import QtWidgets
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication(["test"])


@pytest.fixture
def window(app, tmp_path, monkeypatch):
    from red.avatar import window as win
    played = []
    monkeypatch.setattr(win, "play_clip", played.append)
    clock = Clock()
    sprites = load_sprites(make_sprites(tmp_path / "models" / "companion" / "red"))
    overlay = win.CompanionOverlay(sprites, models_dir=tmp_path / "models", state_file=tmp_path / "spot.json",
                                   voice="af_heart", clock=clock, check_fullscreen=lambda: False)
    for path in overlay.window.pickup_clips + overlay.window.drop_clips:
        avatar.write_wav(path, np.zeros(10, np.float32), 24_000)
    overlay.played, overlay.clock = played, clock
    yield overlay
    overlay.close()


def test_window_never_takes_focus(window):
    from PySide6.QtCore import Qt
    w = window.window
    assert w.windowFlags() & Qt.WindowType.WindowDoesNotAcceptFocus
    assert w.windowFlags() & Qt.WindowType.Tool                      # no taskbar button
    assert w.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
    assert w.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)


def test_starts_in_the_bottom_right_corner(window):
    from PySide6.QtGui import QGuiApplication
    w = window.window
    area = QGuiApplication.primaryScreen().availableGeometry()
    assert w.side == "right"
    assert w.geometry().bottom() == area.bottom()
    assert w.geometry().right() == area.right()            # flush with the side of the screen
    w.tick()
    assert w.frame_name.startswith("cornerR_")


def test_corners_and_the_edge(window, tmp_path):
    from PySide6.QtGui import QGuiApplication
    w = window.window
    area = QGuiApplication.primaryScreen().availableGeometry()
    w.place("left")
    assert w.geometry().left() == area.left() and w.geometry().bottom() == area.bottom()
    w.tick()
    assert w.frame_name.startswith("cornerL_")
    w.place("edge")
    w.tick()
    assert w.frame_name.startswith("peek_")
    assert area.left() <= w.x_center <= area.right()
    assert json.loads((tmp_path / "spot.json").read_text())["side"] == "edge"


def test_top_corners_hang_upside_down(window, tmp_path):
    from PySide6.QtGui import QGuiApplication
    w = window.window
    area = QGuiApplication.primaryScreen().availableGeometry()
    w.place("top-left")
    assert w.hanging and w.geometry().top() == area.top() and w.geometry().left() == area.left()
    w.tick()
    assert w.frame_name.startswith("topL_")
    assert w.sprite_left(70) == 0.0
    w.place("top-right")
    assert w.hanging and w.geometry().top() == area.top() and w.geometry().right() == area.right()
    w.tick()
    assert w.frame_name.startswith("topR_")
    assert w.sprite_left(70) == w.width() - 70
    w._on_heard("hello")
    w._on_said("Hi there.")
    window.clock.t += 2
    w.muted = True
    w.tick()
    assert not w.grab().isNull()                          # bubbles below the head, badge at the bottom
    assert json.loads((tmp_path / "spot.json").read_text())["side"] == "top-right"
    menu = w.build_menu()
    labels = [action.text() for action in menu.actions()]
    assert "Hang from the top-left corner" in labels and "Hang from the top-right corner" not in labels


def test_a_drop_near_a_top_corner_snaps_there(window):
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QGuiApplication
    w = window.window
    area = QGuiApplication.primaryScreen().availableGeometry()
    start = QPointF(area.center().x(), area.bottom() - 20)
    w.press(start)
    spot = QPointF(area.right() - 40, area.top() + 30)
    w.move(spot)
    w.release(spot)
    assert w.side == "top-right" and not w.look.falling
    assert w.geometry().top() == area.top() and w.geometry().right() == area.right()


def test_a_model_without_top_corner_frames_hangs_from_the_top_edge(app, tmp_path, monkeypatch):
    from red.avatar import window as win
    monkeypatch.setattr(win, "play_clip", lambda p: None)
    names = [n for n in PEEK + BODY + CORNERS + TOP]
    sprites = load_sprites(make_sprites(tmp_path / "models" / "companion" / "red", names))
    overlay = win.CompanionOverlay(sprites, models_dir=tmp_path / "models", clock=Clock(),
                                   check_fullscreen=lambda: False)
    try:
        from PySide6.QtGui import QGuiApplication
        area = QGuiApplication.primaryScreen().availableGeometry()
        w = overlay.window
        w.place("top-left")
        w.tick()
        assert w.hanging and w.frame_name.startswith("top_")       # the top edge's frames, in the corner
        assert w.x_center == pytest.approx(area.left() + w.perch_size[0] / 2)
    finally:
        overlay.close()


def test_the_reply_waits_for_the_voice(app, window):
    """The "speaking" state comes before the audio: no text yet. A `said` shows its piece."""
    w = window.window
    w._apply("speaking", "Done. The build is green.\nred: main, 2 to push")
    assert w.bubble_text == "" and w.turn_emotion == "happy"       # the emotion is guessed, the text waits
    window.clock.t += 5
    w.tick()
    assert w.bubble_text == ""                                     # still no audio: still nothing shown
    w._on_said("Done.")
    assert w.bubble_text == "Done."
    window.clock.t += 0.2
    w.tick()
    w._on_said("The build is green.")                              # the next piece, when it starts
    assert w.bubble_text == "Done. The build is green."
    assert w._typed(window.clock.t) == len("Done. ")               # the old piece stays, the new types in
    assert w._typing(window.clock.t)
    window.clock.t += 3
    w.tick()
    assert not w._typing(window.clock.t)
    assert not w.grab().isNull()


def test_a_reply_without_said_events_shows_once_the_voice_sounds(window):
    from red.avatar import MouthMeter
    w = window.window
    w.meter = MouthMeter(clock=window.clock)
    w._apply("speaking", "Opened Downloads.")
    w.tick()
    assert w.bubble_text == ""                                     # nothing sounds yet
    w.meter.start(np.ones(24_000, np.float32), 24_000)              # one second of audio starts
    window.clock.t += 0.1
    w.tick()
    assert w.bubble_text == "Opened Downloads."
    w._on_said("Opened Downloads.")                                 # a late `said` replaces it, no doubling
    assert w.bubble_text == "Opened Downloads."


def test_what_the_user_said_shows_grey_and_stays_while_red_thinks(window):
    w = window.window
    w._apply("speaking", "Earlier reply.")
    w._on_said("Earlier reply.")
    w._apply("thinking", "")
    assert w.bubble_until <= window.clock.t                        # Red's old words are gone
    w._on_heard("what's   up with you")
    assert w.heard_text == "what's up with you"
    assert w.bubble_text == "" and w.heard_until == float("inf")
    window.clock.t += 2
    w.tick()
    assert not w.grab().isNull()                                   # painted: "you: ..." above the bubble
    w._on_said("Not much. You?")
    assert w.bubble_text == "Not much. You?"
    assert w.heard_until == float("inf")                           # the user's line stays with the reply
    w._apply("idle", "")
    assert w.heard_until == window.clock.t + avatar_window().BUBBLE_HOLD
    w._apply("listening", "")                                      # the user talks again: both go
    assert w.heard_until <= window.clock.t and w.bubble_until <= window.clock.t


def avatar_window():
    from red.avatar import window as win
    return win


def test_a_long_reply_keeps_the_latest_pieces(window):
    w = window.window
    for i in range(30):
        window.clock.t += 0.5
        w._on_said(f"This is sentence number {i} of a long reply.")
    assert len(w.bubble_text) <= avatar_window().BUBBLE_TEXT
    assert w.bubble_text.endswith("number 29 of a long reply.")


def test_the_next_reply_starts_fresh(window):
    w = window.window
    w._on_said("First reply.")
    window.clock.t += 0.5
    w._on_said("Still the first.")
    assert w.bubble_text == "First reply. Still the first."
    w._apply("thinking", "")
    w._on_said("A new reply.")
    assert w.bubble_text == "A new reply."


def test_events_reach_the_window_through_queued_signals(app, window):
    """red.events handlers run on Red's voice thread: the bubble gets them on the Qt thread."""
    import threading
    from red import events
    seen = []
    w = window.window
    original = w._on_said
    w._on_said = lambda text: (seen.append(threading.current_thread()), original(text))
    w.said_signal.disconnect()
    w.said_signal.connect(w._on_said, __import__("PySide6.QtCore", fromlist=["Qt"]).Qt.ConnectionType.QueuedConnection)
    t = threading.Thread(target=lambda: (events.emit("heard", text="hello there"),
                                         events.emit("said", text="Hey."),
                                         events.emit("mic", muted=True)))
    t.start()
    t.join()
    assert w.heard_text == "" and not seen                         # nothing ran on the other thread
    app.processEvents()
    assert w.heard_text == "hello there" and w.bubble_text == "Hey." and w.muted
    assert seen == [threading.main_thread()] or seen[0] is not t
    window.close()
    events.emit("heard", text="after close")                       # unsubscribed: no error, no change
    app.processEvents()
    assert w.heard_text == "hello there"


def test_microphone_off_from_the_menu(window):
    w = window.window
    calls = []
    window.on_mic = calls.append
    w.toggle_mic()
    assert calls == [True] and w.muted
    w.tick()
    assert not w.grab().isNull()                                   # the crossed-out mic is drawn
    w.toggle_mic()
    assert calls == [True, False] and not w.muted


def test_microphone_stays_as_it_was_if_the_listener_cant_mute(window):
    w = window.window

    def fail(muted):
        raise RuntimeError("no listener")
    window.on_mic = fail
    w.toggle_mic()
    assert not w.muted
    window.on_mic = None
    w.toggle_mic()
    assert not w.muted


def test_mic_control_uses_mute_or_pauses_the_wake_word():
    from red import events
    from red.avatar import mic_control

    class WithMute:
        def __init__(self):
            self.calls = []

        def mute(self, on):
            self.calls.append(on)

    class OldListener:
        def __init__(self):
            self.calls = []

        def pause(self):
            self.calls.append("pause")

        def resume(self):
            self.calls.append("resume")

    got = []
    off = events.on("mic", lambda muted: got.append(muted))
    try:
        new = WithMute()
        mic_control(lambda: new)(True)
        assert new.calls == [True] and got == []                   # Listener.mute announces itself
        old = OldListener()
        control = mic_control(lambda: old)
        control(True)
        control(True)                                              # never paused twice
        control(False)
        control(False)
        assert old.calls == ["pause", "resume"] and got == [True, True, False, False]
        with pytest.raises(RuntimeError):
            mic_control(lambda: None)(True)
    finally:
        off()


def test_greeting_waves(window):
    w = window.window
    w._apply("speaking", "Hey! Good to see you.")
    frames = set()
    for _ in range(12):
        window.clock.t += 0.1
        w.tick()
        frames.add(as_peek(w.frame_name))
    assert {"peek_wave_1", "peek_wave_2", "peek_wave_3"} <= frames


def test_set_state_from_another_thread(app, window):
    import threading
    t = threading.Thread(target=window.set_state, args=("listening", ""))
    t.start()
    t.join()
    app.processEvents()
    assert window.window.look.state == "listening"
    with pytest.raises(ValueError):
        window.set_state("dancing")


def test_falls_asleep_and_wakes(window):
    w = window.window
    window.clock.t += avatar.SLEEP_AFTER_SECONDS + 1
    w.tick()
    assert as_peek(w.frame_name) == "peek_sleep"
    w._apply("listening", "")
    assert as_peek(w.frame_name) == "peek_notice"


def test_hover_cheers_up(window):
    w = window.window
    w.enterEvent(None)
    assert as_peek(w.frame_name) == "peek_happy"


def test_click_opens_chat(window):
    from PySide6.QtCore import QPointF
    clicked = []
    window.on_click = lambda: clicked.append(True)
    w = window.window
    w.press(QPointF(10, 10))
    w.move(QPointF(12, 11))                   # a wobble, not a pickup
    w.release(QPointF(12, 11))
    assert clicked == [True]
    assert not w.look.dragging


def test_pick_up_carry_and_drop(window, tmp_path):
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QGuiApplication
    w = window.window
    area = QGuiApplication.primaryScreen().availableGeometry()
    start = QPointF(area.center().x(), area.bottom() - 20)
    w.press(start)
    w.move(start + QPointF(40, -200))
    assert w.look.dragging
    assert w.frame_name.startswith("body_") or (w.tick() or w.frame_name.startswith("body_"))
    assert len(window.played) == 1 and "pickup" in window.played[0].name
    w.move(start + QPointF(-160, -300))
    assert not w.grab().isNull()
    w.release(start + QPointF(-160, -300))
    assert w.look.falling and "drop" in window.played[-1].name
    for _ in range(200):
        window.clock.t += 1 / 30
        w.tick()
        if not w.look.falling:
            break
    assert not w.look.falling
    assert w.side == "edge"                                # let go mid-screen: the bottom edge
    assert w.x_center == pytest.approx(start.x() - 160, abs=2)
    assert w.geometry().bottom() == area.bottom()
    assert json.loads((tmp_path / "spot.json").read_text())["x"] == pytest.approx(w.x_center)


def test_hangs_upside_down_from_the_top(window):
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QGuiApplication
    w = window.window
    area = QGuiApplication.primaryScreen().availableGeometry()
    start = QPointF(area.center().x(), area.bottom() - 20)
    w.press(start)
    w.move(QPointF(area.center().x() + 100, area.top() + 30))
    w.release(QPointF(area.center().x() + 100, area.top() + 30))
    assert w.side == "top" and not w.look.falling          # it grabs the edge: no fall
    assert w.geometry().top() == area.top()
    assert w.x_center == pytest.approx(area.center().x() + 100, abs=2)
    window.clock.t += 2
    w._apply("speaking", "Sorry, I couldn't find that file.")
    window.clock.t += 3
    w.tick()
    assert w.frame_name.startswith("top_")
    assert not w.grab().isNull()                           # bubble and tear drawn below the head


def test_little_animations(window):
    from PySide6.QtCore import QPointF
    w = window.window
    w.enterEvent(None)
    assert "hop" in w.anims and w.timer.interval() == 33   # hover: a hop, drawn fast
    assert not w.grab().isNull()
    window.clock.t += 5
    w.tick()
    assert not w.animating(window.clock.t)
    w.press(QPointF(500, 500))
    w.move(QPointF(520, 300))
    assert "pop" in w.anims                                # picked up: a springy stretch
    assert not w.grab().isNull()
    window.clock.t += avatar.SLEEP_AFTER_SECONDS + 10
    w.release(QPointF(520, 300))
    for _ in range(300):
        window.clock.t += 1 / 30
        w.tick()
        if not w.look.falling:
            break
    assert w.anims["land"] == pytest.approx(window.clock.t, abs=0.1)     # landed: a squash
    w.look.state = "sleeping"
    w.enterEvent(None)
    assert "jolt" in w.anims                               # woken up: startled


def test_dropped_near_a_side_goes_into_the_corner(window):
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QGuiApplication
    w = window.window
    area = QGuiApplication.primaryScreen().availableGeometry()
    start = QPointF(area.center().x(), area.bottom() - 20)
    w.press(start)
    w.move(QPointF(area.left() + 40, area.top() + 300))
    w.release(QPointF(area.left() + 40, area.top() + 300))
    for _ in range(300):
        window.clock.t += 1 / 30
        w.tick()
        if not w.look.falling:
            break
    assert w.side == "left"
    assert w.geometry().left() == area.left()
    assert w.frame_name == "cornerL_notice"


def test_no_pickup_sound_over_reds_voice(window):
    from PySide6.QtCore import QPointF
    w = window.window
    rate = 24_000
    window.meter.start(np.full(rate, 0.5, np.float32), rate)
    window.meter._start = window.clock.t
    window.meter._clock = window.clock
    w.press(QPointF(500, 500))
    w.move(QPointF(500, 300))
    assert window.played == []


def test_hides_for_full_screen_apps(window):
    w = window.window
    w.show()
    w.check_fullscreen = lambda: True
    w._check_fullscreen()
    assert not w.isVisible()
    w.check_fullscreen = lambda: False
    w._check_fullscreen()
    assert w.isVisible()


def test_switch_companion(window, tmp_path):
    make_sprites(tmp_path / "models" / "companion" / "remy")
    w = window.window
    w.switch("remy")
    assert w.companion == "remy"
    assert json.loads((tmp_path / "spot.json").read_text())["companion"] == "remy"
    assert "af_bella" in w.pickup_clips[0].name


def test_overlay_falls_back_to_the_glow_without_pictures(app, monkeypatch, tmp_path):
    from red import overlay as ov
    for name in ("RED_OVERLAY", "RED_COMPANION", "RED_COMPANION_SIZE"):
        monkeypatch.delenv(name, raising=False)
    settings = load_settings(tmp_path)
    _, shown = ov._start_qt(1.0, "companion", settings)
    try:
        assert isinstance(shown, ov.GlowOverlay)
    finally:
        shown.close()


def test_companion_overlay_from_settings(app, monkeypatch, tmp_path):
    from red import overlay as ov
    from red.avatar.window import CompanionOverlay
    for name in ("RED_OVERLAY", "RED_COMPANION", "RED_COMPANION_SIZE"):
        monkeypatch.delenv(name, raising=False)
    make_sprites(tmp_path / "models" / "companion" / "red")
    settings = load_settings(tmp_path)
    _, shown = ov._start_qt(1.0, "companion", settings)
    try:
        assert isinstance(shown, CompanionOverlay)
        assert shown.window.companion == "red"
    finally:
        shown.close()
