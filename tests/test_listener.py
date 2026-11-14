import json
import threading
import time

import numpy as np
import pytest

import red.audio as audio
from red.audio import AudioError
from red.listener import (DEFAULT_WAKEWORD, WAKEWORDS, Listener, download_wakeword,
                          make_detector, normalize_hotkey, resolve_wakeword)
from voice_fakes import FakeDetector, FakeHotKeys, FakeMic, fake_download


def wait_for(cond, timeout=3.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.005)
    return False


class Recorder:
    def __init__(self, block: threading.Event | None = None):
        self.calls = []
        self.threads = []
        self.block = block
        self.entered = threading.Event()

    def __call__(self, source):
        self.calls.append(source)
        self.threads.append(threading.current_thread())
        self.entered.set()
        if self.block is not None:
            self.block.wait(5)


class SlowMic(FakeMic):
    """A FakeMic that takes real time per block, like a microphone."""

    def read(self, timeout=2.0):
        time.sleep(0.002)
        return super().read(timeout)


@pytest.fixture
def listener_factory(tmp_path):
    made = []

    def make(on_trigger, hotkey="<ctrl>+<alt>+r", wakeword=None, detector=None, mic=None, **extra):
        mic = mic or SlowMic(block=1280)
        detector = detector or FakeDetector()
        lst = Listener(on_trigger, hotkey, wakeword, model_dir=tmp_path,
                       hotkey_factory=FakeHotKeys, mic_factory=lambda: mic,
                       detector_factory=lambda d, w: detector, **extra)
        made.append(lst)
        return lst, mic, detector

    yield make
    for lst in made:
        lst.stop()


# --- hotkey parsing ----------------------------------------------------------

@pytest.mark.parametrize("text, expected", [
    ("Ctrl+Alt+R", "<ctrl>+<alt>+r"),
    ("<ctrl>+<alt>+r", "<ctrl>+<alt>+r"),
    ("control + shift + F9", "<ctrl>+<shift>+<f9>"),
    ("Win+Space", "<cmd>+<space>"),
])
def test_normalize_hotkey(text, expected):
    assert normalize_hotkey(text) == expected


@pytest.mark.parametrize("bad", ["", "R", "Ctrl+", "R+Ctrl", "Ctrl++R"])
def test_bad_hotkeys_are_rejected(bad):
    with pytest.raises(ValueError):
        normalize_hotkey(bad)


def test_resolve_wakeword():
    assert resolve_wakeword("Hey Red") == "hey_red"
    assert resolve_wakeword("hey, red") == "hey_red"
    assert resolve_wakeword("hey_red") == "hey_red"
    assert resolve_wakeword("hey-mycroft") == "hey_mycroft"
    assert resolve_wakeword(r"D:\models\hey_red.onnx") == r"D:\models\hey_red.onnx"
    with pytest.raises(ValueError):
        resolve_wakeword("hey computer")


def test_hey_red_is_the_default_and_no_other_assistant_name_is_offered():
    assert DEFAULT_WAKEWORD == "hey_red"
    assert set(WAKEWORDS) == {"hey_mycroft", "hey_rhasspy", "alexa"}
    import inspect
    params = inspect.signature(Listener).parameters
    assert params["detector_factory"].default is make_detector


def test_download_hey_red_fetches_pinned_base_whisper(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(audio, "download", fake_download(calls))
    wake_dir = tmp_path / "wakeword"
    path = download_wakeword(wake_dir, "hey_red")
    assert path == tmp_path / "whisper" / "base.en"
    assert {d.name for _, d, _ in calls} == {"config.json", "model.bin", "tokenizer.json", "vocabulary.txt"}
    assert all("Systran/faster-whisper-base.en/resolve/3d3d5de" in u for u, _, _ in calls)


def test_make_detector_picks_the_hey_red_detector(tmp_path, monkeypatch):
    import red.wakeword as wakeword
    made = []
    monkeypatch.setattr(audio, "download", fake_download())
    monkeypatch.setattr(wakeword.HeyRedDetector, "create", classmethod(lambda cls, d: made.append(d) or "det"))
    assert make_detector(tmp_path / "wakeword", "hey_red") == "det"
    assert made == [tmp_path / "wakeword"]


def test_download_wakeword_fetches_pinned_onnx_models(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(audio, "download", fake_download(calls))
    path = download_wakeword(tmp_path, "hey_mycroft")
    assert path == tmp_path / "hey_mycroft_v0.1.onnx"
    names = [d.name for _, d, _ in calls]
    assert names == ["melspectrogram.onnx", "embedding_model.onnx", "hey_mycroft_v0.1.onnx"]
    assert all(u.startswith("https://github.com/dscripka/openWakeWord/releases/download/v0.5.1/")
               and u.endswith(".onnx") for u, _, _ in calls)
    assert all(len(a.sha256) == 64 for a in WAKEWORDS.values())


def test_custom_wakeword_model_must_exist(tmp_path, monkeypatch):
    monkeypatch.setattr(audio, "download", fake_download())
    with pytest.raises(FileNotFoundError):
        download_wakeword(tmp_path, str(tmp_path / "hey_red.onnx"))
    (tmp_path / "hey_red.onnx").write_bytes(b"x")
    assert download_wakeword(tmp_path, str(tmp_path / "hey_red.onnx")) == tmp_path / "hey_red.onnx"


# --- hotkey trigger ----------------------------------------------------------

def test_hotkey_triggers_on_a_background_thread(listener_factory):
    rec = Recorder()
    lst, _, _ = listener_factory(rec)
    lst.start()
    hk = FakeHotKeys.instances[-1]
    assert hk.started and list(hk.mapping) == ["<ctrl>+<alt>+r"]
    hk.press()
    assert wait_for(lambda: rec.calls == ["hotkey"])
    assert rec.threads[0] is not threading.main_thread()
    lst.stop()
    assert hk.stopped


def test_trigger_while_busy_is_ignored(listener_factory):
    release = threading.Event()
    rec = Recorder(block=release)
    lst, _, _ = listener_factory(rec)
    lst.start()
    hk = FakeHotKeys.instances[-1]
    hk.press()
    assert rec.entered.wait(2)
    assert lst.busy
    hk.press()
    hk.press()
    release.set()
    assert wait_for(lambda: not lst.busy)
    time.sleep(0.05)
    assert rec.calls == ["hotkey"]
    hk.press()                                     # works again once idle
    assert wait_for(lambda: rec.calls == ["hotkey", "hotkey"])


def test_handler_errors_do_not_kill_the_listener(listener_factory):
    calls = []

    def boom(source):
        calls.append(source)
        raise RuntimeError("handler failed")

    lst, _, _ = listener_factory(boom)
    lst.start()
    hk = FakeHotKeys.instances[-1]
    hk.press()
    assert wait_for(lambda: len(calls) == 1 and not lst.busy)
    hk.press()
    assert wait_for(lambda: len(calls) == 2)


def test_no_hotkey(listener_factory):
    before = len(FakeHotKeys.instances)
    lst, _, _ = listener_factory(Recorder(), hotkey=None)
    lst.start()
    assert len(FakeHotKeys.instances) == before


def test_triggers_after_stop_are_ignored(listener_factory):
    rec = Recorder()
    lst, _, _ = listener_factory(rec)
    lst.start()
    hk = FakeHotKeys.instances[-1]
    lst.stop()
    hk.press()
    time.sleep(0.05)
    assert rec.calls == []


# --- wake word ---------------------------------------------------------------

def test_wakeword_triggers_and_mic_is_closed_while_handling(listener_factory):
    release = threading.Event()
    rec = Recorder(block=release)
    det = FakeDetector(fire_at={20})
    lst, mic, _ = listener_factory(rec, wakeword="hey_red", detector=det)
    lst.start()
    assert rec.entered.wait(3)
    assert rec.calls == ["wakeword"]
    assert wait_for(lambda: not mic.is_open)       # paused while recording or speaking
    assert det.dtypes == {np.dtype(np.int16)}
    frames = det.frames
    time.sleep(0.05)
    assert det.frames == frames                    # nothing is read while paused
    release.set()
    assert wait_for(lambda: mic.is_open and det.frames > frames)
    assert det.resets >= 2                         # fresh state after every resume
    assert rec.calls == ["wakeword"]


def test_the_command_heard_with_the_wake_word_is_handed_over_once(listener_factory):
    rec = Recorder()
    det = FakeDetector(fire_at={20})
    det.command_audio = np.ones(100, np.float32)
    lst, _, _ = listener_factory(rec, wakeword="hey_red", detector=det)
    lst.start()
    assert rec.entered.wait(3)
    taken = lst.take_wake_audio()
    assert taken is not None and taken.size == 100
    assert lst.take_wake_audio() is None


def test_the_hotkey_never_gets_a_stale_wake_command(listener_factory):
    rec = Recorder()
    lst, _, _ = listener_factory(rec)
    lst.wake_audio = np.ones(10, np.float32)       # left from an earlier wake
    lst.start()
    lst._hotkeys.press()
    assert rec.entered.wait(3)
    assert lst.take_wake_audio() is None


def test_pause_closes_mic_and_resume_reopens(listener_factory):
    lst, mic, det = listener_factory(Recorder(), wakeword="hey_red")
    lst.start()
    assert wait_for(lambda: mic.is_open)
    lst.pause()
    assert not mic.is_open and lst.paused         # closed by the time pause() returns
    lst.pause()                                    # pauses nest
    lst.resume()
    time.sleep(0.05)
    assert not mic.is_open
    lst.resume()
    assert wait_for(lambda: mic.is_open)
    assert mic.opened == 2
    with lst.paused_while():
        assert not mic.is_open
    assert wait_for(lambda: mic.is_open)


def test_extra_resume_is_harmless(listener_factory):
    lst, mic, _ = listener_factory(Recorder(), wakeword="hey_red")
    lst.start()
    lst.resume()
    lst.resume()
    lst.pause()
    assert not mic.is_open


def test_hotkey_still_works_while_wakeword_is_paused(listener_factory):
    rec = Recorder()
    lst, _, _ = listener_factory(rec, wakeword="hey_red")
    lst.start()
    lst.pause()
    FakeHotKeys.instances[-1].press()
    assert wait_for(lambda: rec.calls == ["hotkey"])


def test_mic_errors_are_retried(listener_factory):
    mic = SlowMic(block=1280, fail_after=3)
    lst, _, _ = listener_factory(Recorder(), wakeword="hey_red", mic=mic)
    lst.start()
    assert wait_for(lambda: isinstance(lst.last_error, AudioError))
    lst.stop()                                     # doesn't hang while waiting to retry


def test_stop_ends_all_threads(listener_factory):
    lst, mic, _ = listener_factory(Recorder(), wakeword="hey_red")
    lst.start()
    assert wait_for(lambda: mic.is_open)
    lst.stop()
    assert not mic.is_open
    names = {t.name for t in threading.enumerate() if t.is_alive()}
    assert not names & {"red-wakeword", "red-trigger"}
    lst.stop()                                     # twice is fine


def test_stop_from_inside_the_handler(listener_factory):
    done = threading.Event()
    holder = {}

    def handler(source):
        holder["l"].stop()
        done.set()

    lst, _, _ = listener_factory(handler)
    holder["l"] = lst
    lst.start()
    FakeHotKeys.instances[-1].press()
    assert done.wait(3)


def test_detector_load_errors_surface_in_start(tmp_path):
    def broken(model_dir, wakeword):
        raise RuntimeError("bad model")

    lst = Listener(Recorder(), wakeword="hey_red", model_dir=tmp_path,
                   hotkey_factory=FakeHotKeys, detector_factory=broken)
    with pytest.raises(RuntimeError, match="bad model"):
        lst.start()


# --- cutting in while Red talks (plan.md task 6) ----------------------------------------

def test_hotkey_while_red_talks_interrupts(listener_factory):
    release = threading.Event()
    rec = Recorder(block=release)
    lst, _, _ = listener_factory(rec)
    cut = []
    lst.on_interrupt = lambda: cut.append("cut")
    lst.start()
    hk = FakeHotKeys.instances[-1]
    hk.press()
    assert rec.entered.wait(2)
    hk.press()                                     # busy, not talking: ignored as before
    assert cut == []
    lst.allow_interrupt(True)                      # Red starts talking
    hk.press()
    assert cut == ["cut"]
    lst.allow_interrupt(False)
    hk.press()
    assert cut == ["cut"]
    release.set()
    assert wait_for(lambda: not lst.busy)
    assert rec.calls == ["hotkey"]                 # an interrupt never starts a second command


def test_wake_word_listens_again_only_while_red_talks(listener_factory):
    release = threading.Event()
    rec = Recorder(block=release)
    det = FakeDetector(fire_at={20})
    lst, mic, _ = listener_factory(rec, wakeword="hey_red", detector=det)
    cut = []
    lst.on_interrupt = lambda: cut.append("cut")
    lst.start()
    assert rec.entered.wait(3)
    assert wait_for(lambda: not mic.is_open)       # recording: the mic is closed to the wake word
    det.fire_at = {det.frames + 30}
    lst.allow_interrupt(True)                      # talking: "Hey Red" is heard
    assert wait_for(lambda: cut == ["cut"] or cut == ["cut", "cut"])
    lst.allow_interrupt(False)
    assert wait_for(lambda: not mic.is_open)
    lst.allow_interrupt(False)                     # twice is harmless
    release.set()
    assert wait_for(lambda: not lst.busy and mic.is_open)


def test_a_handler_that_leaves_it_open_is_closed(listener_factory):
    def handler(source):
        lst.allow_interrupt(True)
    lst, mic, _ = listener_factory(handler, wakeword="hey_red")
    lst.start()
    FakeHotKeys.instances[-1].press()
    assert wait_for(lambda: not lst.busy)
    assert lst._interrupt_open is False and lst._pauses == 0


# --- microphone off (night 1) ---------------------------------------------------------

def test_muting_closes_the_mic_and_nothing_is_heard(listener_factory):
    rec = Recorder()
    det = FakeDetector(fire_at={50})
    lst, mic, _ = listener_factory(rec, wakeword="hey_red", detector=det)
    lst.start()
    assert wait_for(lambda: mic.is_open)
    assert lst.mute(True) is True
    assert lst.muted and not mic.is_open            # closed by the time mute() returns
    frames = det.frames
    time.sleep(0.05)
    assert det.frames == frames and rec.calls == []  # not even the wake word is checked


def test_unmuting_listens_again(listener_factory):
    lst, mic, det = listener_factory(Recorder(), wakeword="hey_red")
    lst.start()
    lst.mute(True)
    lst.mute(False)
    assert wait_for(lambda: mic.is_open)
    assert not lst.muted


def test_mute_with_no_argument_toggles(listener_factory):
    lst, _, _ = listener_factory(Recorder())
    assert lst.mute() is True and lst.mute() is False


def test_the_hotkey_does_nothing_while_muted(listener_factory):
    rec = Recorder()
    lst, _, _ = listener_factory(rec)
    lst.start()
    lst.mute(True)
    lst._hotkeys.press()
    time.sleep(0.05)
    assert rec.calls == []
    lst.mute(False)
    lst._hotkeys.press()
    assert rec.entered.wait(3)


def test_mute_is_remembered_in_mic_json(listener_factory, tmp_path):
    state = tmp_path / "cache" / "mic.json"
    lst, _, _ = listener_factory(Recorder(), mic_state=state)
    lst.mute(True)
    assert json.loads(state.read_text(encoding="utf-8")) == {"muted": True}
    # A new Listener (a restart) starts deaf.
    again, _, _ = listener_factory(Recorder(), mic_state=state)
    assert again.muted
    again.mute(False)
    assert not json.loads(state.read_text(encoding="utf-8"))["muted"]


def test_mute_keeps_the_zipped_mouth_in_mic_json(listener_factory, tmp_path):
    from red import conversation as conv
    state = tmp_path / "mic.json"
    conv.Conversation(state).zip("test")
    lst, _, _ = listener_factory(Recorder(), mic_state=state)
    lst.mute(True)
    lst.mute(False)
    assert json.loads(state.read_text(encoding="utf-8")) == {"zipped": True, "muted": False}
    assert conv.Conversation(state).zipped                 # a restart is still zipped


def test_a_broken_mic_json_means_not_muted(listener_factory, tmp_path):
    state = tmp_path / "mic.json"
    state.write_text("{not json", encoding="utf-8")
    lst, _, _ = listener_factory(Recorder(), mic_state=state)
    assert not lst.muted


def test_mute_emits_the_mic_event_and_plays_a_sound_not_words(listener_factory):
    from red import events
    seen, sounds = [], []
    events.on("mic", lambda muted: seen.append(muted))
    try:
        lst, _, _ = listener_factory(Recorder(), mute_sound=sounds.append)
        lst.mute(True)
        lst.mute(True)                                # no change: no second event or sound
        lst.mute(False)
    finally:
        events.clear()
    assert seen == [True, False] and sounds == [True, False]


def test_the_mute_hotkey_toggles(listener_factory):
    lst, _, _ = listener_factory(Recorder(), mute_hotkey="Ctrl+Alt+M")
    lst.start()
    hk = lst._hotkeys
    assert set(hk.mapping) == {"<ctrl>+<alt>+r", "<ctrl>+<alt>+m"}
    hk.press("<ctrl>+<alt>+m")
    assert wait_for(lambda: lst.muted)
    hk.press("<ctrl>+<alt>+m")
    assert wait_for(lambda: not lst.muted)


def test_a_failing_sound_does_not_undo_the_mute(listener_factory):
    def boom(muted):
        raise RuntimeError("no speakers")
    lst, _, _ = listener_factory(Recorder(), mute_sound=boom)
    assert lst.mute(True) is True and lst.muted
