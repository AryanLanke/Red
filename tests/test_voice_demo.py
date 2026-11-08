import wave

import numpy as np
import pytest

import red.voice_demo as voice_demo
from red.confirm import is_yes
from red.voice_demo import VoiceConfig, _pretty_hotkey, _read_wav, _spoken_name

VARS = ("RED_HOTKEY", "RED_WAKEWORD", "RED_WAKEWORD_THRESHOLD", "RED_WHISPER_MODEL",
        "RED_WHISPER_DEVICE", "RED_PIPER_VOICE")


@pytest.fixture
def clean_env(monkeypatch):
    for v in VARS:
        monkeypatch.delenv(v, raising=False)
    return monkeypatch


def test_defaults(clean_env):
    cfg = VoiceConfig.from_env()
    assert cfg == VoiceConfig(hotkey="<ctrl>+<alt>+r", wakeword="hey_red", wakeword_threshold=0.5,
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


def test_demo_uses_the_real_yes_check():
    assert voice_demo.is_yes is is_yes


@pytest.mark.parametrize("wakeword, name", [
    ("hey_red", "Hey Red"),
    ("hey_mycroft", "Hey Mycroft"),
    (r"D:\RED\models\wakeword\hey_red_v0.1.onnx", "Hey Red"),
])
def test_spoken_name(wakeword, name):
    assert _spoken_name(wakeword) == name


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
