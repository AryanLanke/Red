import wave

import numpy as np
import pytest

from red.voice_demo import VoiceConfig, _is_yes, _pretty_hotkey, _read_wav

VARS = ("RED_HOTKEY", "RED_WAKEWORD", "RED_WAKEWORD_THRESHOLD", "RED_WHISPER_MODEL",
        "RED_WHISPER_DEVICE", "RED_PIPER_VOICE")


@pytest.fixture
def clean_env(monkeypatch):
    for v in VARS:
        monkeypatch.delenv(v, raising=False)
    return monkeypatch


def test_defaults(clean_env):
    cfg = VoiceConfig.from_env()
    assert cfg == VoiceConfig(hotkey="<ctrl>+<alt>+r", wakeword="hey_jarvis", wakeword_threshold=0.5,
                              whisper_model="small", whisper_device="auto",
                              piper_voice="en_US-lessac-medium")


def test_env_overrides(clean_env):
    clean_env.setenv("RED_HOTKEY", "Ctrl+Shift+Space")
    clean_env.setenv("RED_WAKEWORD", "off")
    clean_env.setenv("RED_WAKEWORD_THRESHOLD", "0.7")
    clean_env.setenv("RED_WHISPER_DEVICE", "CPU")
    cfg = VoiceConfig.from_env()
    assert cfg.hotkey == "Ctrl+Shift+Space"
    assert cfg.wakeword is None
    assert cfg.wakeword_threshold == 0.7
    assert cfg.whisper_device == "cpu"


@pytest.mark.parametrize("answer, yes", [
    ("Yes.", True), (" yes ", True), ("Y", True), ("YES!", True),
    ("Yeah.", False), ("No.", False), ("yes please", False), ("", False), (None, False),
])
def test_is_yes_stand_in(answer, yes):
    assert _is_yes(answer) is yes


def test_pretty_hotkey():
    assert _pretty_hotkey("<ctrl>+<alt>+r") == "Ctrl+Alt+R"


def test_read_wav_resamples_to_16k(tmp_path):
    path = tmp_path / "a.wav"
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(48_000)
        w.writeframes(np.zeros((48_000, 2), np.int16).tobytes())
    out = _read_wav(path)
    assert out.dtype == np.float32 and out.size == 16_000
