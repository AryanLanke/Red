"""The menu's connections to the voice loop, with fakes: no listener, no speakers, no real windows."""

import os
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from red import events  # noqa: E402
from red.avatar import wiring  # noqa: E402


class Listener:
    def __init__(self):
        self.fired = []

    def _fire(self, source):
        self.fired.append(source)


def test_talk_fires_the_listener_like_the_hotkey():
    listener = Listener()
    wiring.talk_function(lambda: listener)()
    assert listener.fired == ["menu"]
    with pytest.raises(RuntimeError):
        wiring.talk_function(lambda: None)()


def test_a_public_trigger_is_preferred_to_the_private_one():
    class New(Listener):
        def trigger(self, source):
            self.fired.append("public-" + source)
    listener = New()
    wiring.talk_function(lambda: listener)()
    assert listener.fired == ["public-menu"]


def test_music_announces_then_plays_on_its_own_thread():
    import threading
    said, played, done = [], [], threading.Event()
    app = SimpleNamespace(settings=SimpleNamespace(home="x"), executor=SimpleNamespace(registry={}),
                          greet=lambda text: said.append(text) or True)

    def play():
        played.append(threading.current_thread().name)
        done.set()
    song = SimpleNamespace(announce="Putting on Back in Black.", play=play)
    music = wiring.music_function(app, make_music=lambda registry: (lambda companion: song),
                                  active=lambda: "red")
    assert music() is None
    assert done.wait(3)
    assert said == ["Putting on Back in Black."] and played == ["red-menu-song"]
    nothing = wiring.music_function(app, make_music=lambda registry: (lambda companion: None),
                                    active=lambda: "red")
    assert nothing() == "I can't find anything to play."


def test_a_song_that_fails_to_start_is_logged_not_raised():
    import threading
    done = threading.Event()

    def greet(text):
        done.set()
        raise OSError("no speakers")
    app = SimpleNamespace(settings=SimpleNamespace(home="x"), executor=SimpleNamespace(registry={}), greet=greet)
    song = SimpleNamespace(announce="x", play=lambda: None)
    wiring.music_function(app, make_music=lambda r: (lambda c: song), active=lambda: "red")()
    assert done.wait(3)


def test_quiet_mode_blocks_the_idle_life_and_gives_it_back():
    life = SimpleNamespace(_blocked=lambda: False)
    app = SimpleNamespace(idle=life)
    quiet = wiring.quiet_function(app)
    quiet(True)
    assert life._blocked() is True
    quiet(False)
    assert life._blocked() is False
    wiring.quiet_function(SimpleNamespace(idle=None))(True)            # no idle life: nothing happens


def test_switching_goes_through_set_active(monkeypatch, tmp_path):
    from red import companions
    seen = []
    monkeypatch.setattr(companions, "set_active", lambda cid, home=None: seen.append((cid, home)))
    app = SimpleNamespace(settings=SimpleNamespace(home=tmp_path))
    wiring.switch_function(app)("remy")
    assert seen == [("remy", tmp_path)]


def test_settings_opens_the_app_in_its_own_process(monkeypatch):
    calls = []
    monkeypatch.setattr(wiring.subprocess, "Popen", lambda cmd, **kw: calls.append(cmd))
    wiring.settings_function()()
    assert calls[0][-3:] == ["-m", "red", "app"]


def test_wire_menu_fills_the_window_and_survives_a_broken_app(tmp_path):
    window = SimpleNamespace(actions=None)
    overlay = SimpleNamespace(window=window)
    app = SimpleNamespace(settings=SimpleNamespace(home=tmp_path), listener=None,
                          executor=SimpleNamespace(registry={}), idle=None)
    actions = wiring.wire_menu(overlay, app)
    assert window.actions is actions and actions.can_talk and actions.can_play_music
    assert callable(window.on_switch) and callable(window.on_quiet) and callable(window.on_settings)
    assert wiring.wire_menu(SimpleNamespace(), SimpleNamespace()) is None       # no window, no settings: no crash
    events.clear()


def test_the_summon_hotkey_calls_the_windows_queued_signal():
    emitted = []
    window = SimpleNamespace(summon_signal=SimpleNamespace(emit=lambda: emitted.append("summon")))
    overlay = SimpleNamespace(window=window)
    started = []

    class Hotkey:
        def stop(self):
            started.append("stopped")

    def starter(hotkey, callback):
        started.append(hotkey)
        callback()                                       # pynput's thread pressing it
        return Hotkey()
    listener = wiring.start_summon_hotkey(overlay, SimpleNamespace(summon_hotkey="<ctrl>+<alt>+h"), starter)
    assert started == ["<ctrl>+<alt>+h"] and emitted == ["summon"] and overlay.summon_hotkey is listener
    assert wiring.start_summon_hotkey(overlay, SimpleNamespace(summon_hotkey=None), starter) is None   # off
    assert wiring.start_summon_hotkey(overlay, SimpleNamespace(), starter) is None

    def broken(hotkey, callback):
        raise OSError("no keyboard hook")
    assert wiring.start_summon_hotkey(overlay, SimpleNamespace(summon_hotkey="x"), broken) is None


def test_a_mouth_left_zipped_shows_the_zip_from_the_start():
    emitted = []
    overlay = SimpleNamespace(window=SimpleNamespace(conv_signal=SimpleNamespace(
        emit=lambda kind, on: emitted.append((kind, on)))))
    assert wiring.sync_zipped(overlay, SimpleNamespace(conversation=SimpleNamespace(zipped=True))) is True
    assert emitted == [("zipped", True)]
    assert wiring.sync_zipped(overlay, SimpleNamespace(conversation=SimpleNamespace(zipped=False))) is False
    assert wiring.sync_zipped(overlay, SimpleNamespace()) is False                # no conversation: nothing
    assert emitted == [("zipped", True)]


def test_a_microphone_left_off_shows_its_badge_once_the_listener_exists():
    emitted = []
    overlay = SimpleNamespace(window=SimpleNamespace(mic_signal=SimpleNamespace(emit=emitted.append)))
    listeners = iter([None, None, SimpleNamespace(muted=True)])
    naps = []
    assert wiring.sync_mic_badge(overlay, lambda: next(listeners), sleep=naps.append) is True
    assert emitted == [True] and naps == [0.5, 0.5]
    assert wiring.sync_mic_badge(overlay, lambda: SimpleNamespace(muted=False)) is False
    assert wiring.sync_mic_badge(overlay, lambda: None, sleep=lambda s: None, tries=3) is False
    assert emitted == [True]
