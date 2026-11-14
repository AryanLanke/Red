import threading

import numpy as np
import pytest

import red.audio as audio
from red.audio import (SAMPLE_RATE, Endpointer, PinnedFiles, hf_url, record_command, resample,
                       rms, to_float32, to_int16)
from red.llm import Asset
from voice_fakes import FakeMic, fake_download, noise, tone


def test_speech_then_silence_stops_early():
    mic = FakeMic(noise(0.5), tone(1.0), noise(3.0))
    out = record_command(max_seconds=8.0, silence_seconds=0.8, mic=mic)
    # 1 s of speech + 0.3 s pre-roll + ~0.8 s of trailing silence
    assert 1.8 < out.size / SAMPLE_RATE < 2.5
    assert mic.seconds_read < 2.5
    assert out.dtype == np.float32 and out.ndim == 1
    assert not mic.is_open


def test_keeps_speech_onset_through_pre_roll():
    speech = tone(0.8, amp=0.3)
    out = record_command(mic=FakeMic(noise(0.5), speech, noise(2.0)))
    # The loudest part of the result is the whole tone, from its very start.
    loud = np.flatnonzero(np.abs(out) > 0.1)
    assert (loud[-1] - loud[0]) / SAMPLE_RATE == pytest.approx(0.8, abs=0.02)


def test_pause_between_words_shorter_than_silence_does_not_stop():
    mic = FakeMic(noise(0.4), tone(0.5), noise(0.4), tone(0.5), noise(2.0))
    out = record_command(silence_seconds=0.8, mic=mic)
    assert out.size / SAMPLE_RATE > 1.7      # both words are in


def test_a_prefix_said_with_the_wake_word_ends_at_the_next_pause():
    # "Hey Red, open YouTube" already heard in one breath; the user has stopped talking.
    prefix = tone(1.5, amp=0.3)
    mic = FakeMic(noise(3.0))
    out = record_command(silence_seconds=0.8, start_timeout=0.5, mic=mic, prefix=prefix)
    assert out[:prefix.size].tolist() == prefix.tolist()        # kept, from its first sample
    assert mic.seconds_read == pytest.approx(0.8, abs=0.15)      # only the closing pause
    assert out.size / SAMPLE_RATE == pytest.approx(1.5 + mic.seconds_read, abs=0.01)


def test_a_prefix_carries_on_while_you_keep_talking():
    prefix = tone(1.5, amp=0.3)
    mic = FakeMic(tone(1.0, amp=0.3), noise(3.0))
    out = record_command(silence_seconds=0.8, mic=mic, prefix=prefix)
    assert out.size / SAMPLE_RATE > 2.5                          # the prefix and the rest


def test_no_speech_returns_empty_after_start_timeout():
    mic = FakeMic()
    out = record_command(max_seconds=8.0, start_timeout=1.0, mic=mic)
    assert out.size == 0
    assert mic.seconds_read == pytest.approx(1.0, abs=0.05)


def test_no_speech_defaults_to_max_seconds():
    mic = FakeMic()
    assert record_command(max_seconds=2.0, mic=mic).size == 0
    assert mic.seconds_read == pytest.approx(2.0, abs=0.05)


def test_endless_speech_stops_at_max_seconds():
    mic = FakeMic(noise(0.3), tone(20.0))
    out = record_command(max_seconds=3.0, mic=mic)
    assert mic.seconds_read == pytest.approx(3.0, abs=0.05)
    assert out.size > 0


def test_a_single_click_is_not_speech():
    click = tone(0.03, amp=0.5)
    out = record_command(max_seconds=2.0, mic=FakeMic(noise(0.4), click, noise(3.0)))
    assert out.size == 0


def test_noisy_room_raises_the_threshold():
    ep = Endpointer()
    for _ in range(20):
        ep.feed(noise(0.03, amp=0.004))
    assert ep.noise_floor == pytest.approx(0.004, rel=0.3)
    quiet_hum = noise(0.5, amp=0.006, seed=3)   # louder than MIN_SPEECH_RMS, but just noise
    for i in range(0, quiet_hum.size, 480):
        ep.feed(quiet_hum[i:i + 480])
    assert not ep.started
    ep.feed(tone(0.2, amp=0.1))
    assert ep.started


def test_digital_silence_at_mic_start_is_not_calibration():
    ep = Endpointer()
    for _ in range(15):                          # 0.45 s of warm-up zeros
        ep.feed(np.zeros(480, np.float32))
    assert ep.noise_floor is None
    for _ in range(10):
        ep.feed(noise(0.03, amp=0.004))
    assert ep.noise_floor == pytest.approx(0.004, rel=0.3)


def test_noise_floor_is_capped_when_you_talk_straight_away():
    ep = Endpointer()
    loud = tone(1.0, amp=0.3)
    for i in range(0, loud.size, 480):
        ep.feed(loud[i:i + 480])
    assert ep.noise_floor <= audio.MAX_NOISE_FLOOR
    assert ep.started


def test_stop_event_ends_recording():
    stop = threading.Event()
    stop.set()
    mic = FakeMic(tone(5.0))
    assert record_command(mic=mic, stop_event=stop).size == 0
    assert mic.reads == 0


def test_resample_and_conversions():
    a = tone(1.0)
    assert resample(a, 16_000, 16_000) is not None and resample(a, 16_000).size == a.size
    assert resample(np.zeros(22_050, np.float32), 22_050).size == 16_000
    assert resample(np.zeros(48_000, np.float32), 48_000).size == 16_000
    i16 = np.array([0, 16384, -32768], dtype=np.int16)
    assert to_float32(i16).tolist() == [0.0, 0.5, -1.0]
    stereo = np.array([[1.0, 0.0], [0.5, 0.5]], dtype=np.float32)
    assert to_float32(stereo).tolist() == [0.5, 0.5]
    assert to_int16(np.array([2.0, -2.0, 0.0])).tolist() == [32767, -32767, 0]
    assert rms(np.zeros(0)) == 0.0
    assert rms(np.full(10, 0.5)) == pytest.approx(0.5)


def test_pinned_files_download_each_file_with_its_hash(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(audio, "download", fake_download(calls))
    spec = PinnedFiles(hf_url("org/repo", "abc123", "en/voice"),
                       (Asset("a.onnx", "1" * 64), Asset("a.onnx.json", "2" * 64)))
    assert not spec.present(tmp_path)
    assert spec.ensure(tmp_path) == tmp_path
    assert spec.present(tmp_path)
    assert [c[0] for c in calls] == [
        "https://huggingface.co/org/repo/resolve/abc123/en/voice/a.onnx",
        "https://huggingface.co/org/repo/resolve/abc123/en/voice/a.onnx.json",
    ]
    assert [c[2] for c in calls] == ["1" * 64, "2" * 64]
    assert hf_url("o/r", "rev") == "https://huggingface.co/o/r/resolve/rev/"


def test_mic_device_from_env(monkeypatch):
    monkeypatch.delenv("RED_MIC_DEVICE", raising=False)
    assert audio.default_input_device() is None
    monkeypatch.setenv("RED_MIC_DEVICE", "3")
    assert audio.default_input_device() == 3
    monkeypatch.setenv("RED_MIC_DEVICE", "Headset")
    assert audio.default_input_device() == "Headset"


def test_the_microphone_chime_plays_on_its_own_stream_and_is_quiet(monkeypatch):
    import sys
    import types
    written = []

    class Stream:
        def __init__(self, **kw):
            self.kw = kw

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return None

        def write(self, data):
            written.append(data)

    fake = types.SimpleNamespace(OutputStream=Stream, play=lambda *a, **k: pytest.fail("sd.play would cut Red's voice"))
    monkeypatch.setitem(sys.modules, "sounddevice", fake)
    audio.soft_chime(True)
    audio.soft_chime(False)
    off, on = written
    assert 0.15 < off.size / 22_050 < 0.3 and abs(off).max() < 0.1
    assert off.shape == on.shape and not (off == on).all()      # falling is not the same as rising
