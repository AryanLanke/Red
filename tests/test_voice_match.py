"""Voice match: only the owner's "Hey Red" wakes Red. Saved audio fixtures, never the microphone."""

import json
import wave
from pathlib import Path

import numpy as np
import pytest

from red import voice_match as vm
from red.config import load_settings
from red.voice_setup import run_setup
from red.wakeword import HeyRedDetector

FIXTURES = Path(__file__).parent / "fixtures" / "voice"


def load(name):
    with wave.open(str(FIXTURES / f"{name}.wav"), "rb") as w:
        return np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float32) / 32768


# --- features ---------------------------------------------------------------------------

def test_fbank_shape_and_mean():
    audio = load("owner_enrol_1")
    feats = vm.fbank(audio)
    assert feats.shape == (1 + (audio.size - 400) // 160, 80) and feats.dtype == np.float32
    assert np.allclose(feats.mean(axis=0), 0, atol=1e-3)        # "global-mean" normalised
    speech = audio[3200:-3200]                                   # without the silent padding
    # Loudness hardly matters (only the quietest bands reach the energy floor).
    assert np.mean(np.abs(vm.fbank(speech * 0.25) - vm.fbank(speech))) < 0.05
    assert vm.fbank(np.zeros(100, np.float32)).shape == (0, 80)


def test_mel_filters_cover_the_spectrum():
    bank = vm._mel_bank()
    assert bank.shape == (80, 257) and (bank.sum(axis=1) > 0).all()


# --- the profile and the check, with a fake embedding ----------------------------------

def unit(v):
    v = np.asarray(v, dtype=np.float32)
    return v / np.linalg.norm(v)


def owner_like(i):
    rng = np.random.default_rng(i)
    return unit(np.ones(512) + 0.15 * rng.normal(size=512))


def test_profile_keeps_numbers_not_audio_and_picks_a_threshold(tmp_path):
    profile = vm.make_profile([owner_like(i) for i in range(10)])
    assert set(profile) >= {"model", "mean", "samples", "own_lowest", "threshold"}
    assert len(profile["mean"]) == 512 and profile["samples"] == 10
    assert vm.LOWEST <= profile["threshold"] <= vm.HIGHEST
    assert profile["threshold"] <= profile["own_lowest"] - vm.MARGIN + 1e-6 or profile["threshold"] == vm.LOWEST
    vm.save_profile(tmp_path, profile)
    mean, threshold = vm.load_profile(tmp_path)
    assert mean.shape == (512,) and threshold == profile["threshold"]


def test_a_profile_from_another_model_is_ignored(tmp_path):
    vm.save_profile(tmp_path, {**vm.make_profile([owner_like(1)] * 3), "model": "other.onnx"})
    assert vm.load_profile(tmp_path) is None


class FakeModel:
    def __init__(self, vectors):
        self.vectors = vectors

    def embed(self, audio):
        return self.vectors.pop(0)


def test_owner_check_lets_you_in_and_keeps_others_out():
    owner = unit(np.ones(512))
    stranger = unit(np.r_[np.ones(256), -np.ones(256)])
    check = vm.OwnerCheck(FakeModel([owner_like(5), stranger, None]), owner, threshold=0.6)
    assert check(np.zeros(1)) is True
    assert check(np.zeros(1)) is False and check.last_score < 0.1
    assert check(np.zeros(1)) is True        # too short to judge: the words already matched


def test_a_broken_model_never_locks_you_out():
    class Broken:
        def embed(self, audio):
            raise RuntimeError("onnx")
    assert vm.OwnerCheck(Broken(), unit(np.ones(512)))(np.zeros(1)) is True


@pytest.mark.parametrize("env, on, threshold", [
    ({}, False, None), ({"RED_VOICE_MATCH": "on"}, True, None),
    ({"RED_VOICE_MATCH": "on", "RED_VOICE_MATCH_THRESHOLD": "0.7"}, True, 0.7),
    ({"RED_VOICE_MATCH": "off", "RED_VOICE_MATCH_THRESHOLD": "x"}, False, None),
])
def test_settings_from_env(monkeypatch, env, on, threshold):
    for name in ("RED_VOICE_MATCH", "RED_VOICE_MATCH_THRESHOLD"):
        monkeypatch.delenv(name, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    assert vm.settings_from_env() == (on, threshold)


def test_off_or_no_profile_means_everyone(tmp_path, monkeypatch):
    monkeypatch.delenv("RED_VOICE_MATCH", raising=False)
    assert vm.OwnerCheck.create(tmp_path) is None
    monkeypatch.setenv("RED_VOICE_MATCH", "on")
    assert vm.OwnerCheck.create(tmp_path) is None              # on, but no voice-setup yet
    vm.save_profile(tmp_path, {**vm.make_profile([owner_like(i) for i in range(5)]), "threshold": 0.52})
    check = vm.OwnerCheck.create(tmp_path)
    assert check is not None and check.threshold == 0.52        # voice-setup's pick
    monkeypatch.setenv("RED_VOICE_MATCH_THRESHOLD", "0.66")
    assert vm.OwnerCheck.create(tmp_path).threshold == 0.66     # yours wins


def test_settings_check_the_values(tmp_path, monkeypatch):
    monkeypatch.setenv("RED_VOICE_MATCH", "maybe")
    with pytest.raises(ValueError, match="RED_VOICE_MATCH"):
        load_settings(tmp_path)
    monkeypatch.setenv("RED_VOICE_MATCH", "on")
    monkeypatch.setenv("RED_VOICE_MATCH_THRESHOLD", "1.5")
    with pytest.raises(ValueError, match="RED_VOICE_MATCH_THRESHOLD"):
        load_settings(tmp_path)
    monkeypatch.setenv("RED_VOICE_MATCH_THRESHOLD", "0.55")
    s = load_settings(tmp_path)
    assert s.voice_match is True and s.voice_match_threshold == 0.55


# --- the detector asks only when the words matched -------------------------------------

def detector(text, owner):
    vad = lambda chunk: 0.9 if np.abs(chunk).max() > 0.01 else 0.0   # noqa: E731
    return HeyRedDetector(vad, lambda clip: text, owner=owner)


def say_once(det):
    speech = np.concatenate([np.zeros(16000, np.float32), 0.3 * np.ones(12000, np.float32),
                             np.zeros(16000, np.float32)])
    return max(det.score(speech[i:i + 1280]) for i in range(0, speech.size, 1280))


def test_the_detector_ignores_hey_red_in_another_voice():
    asked = []
    assert say_once(detector("Hey Red", lambda clip: asked.append(clip.size) or False)) == 0.0
    assert len(asked) == 1
    assert say_once(detector("Hey Red", lambda clip: True)) == 1.0


def test_other_words_never_run_the_voice_check():
    asked = []
    assert say_once(detector("What time is it", lambda clip: asked.append(1) or True)) == 0.0
    assert asked == []


# --- voice-setup learns the voice from the same recordings ------------------------------

class Audio:
    def __init__(self, n=16000):
        self.size = n


def test_voice_setup_saves_the_voice(tmp_path):
    vectors = [owner_like(i) for i in range(10)]
    out = []
    profile = run_setup(tmp_path, record=lambda **kw: Audio(), transcribe=lambda a: "Hey Red",
                        say=lambda t: None, chime=lambda: None, out=out.append,
                        embed=lambda audio: vectors.pop(0))
    assert profile is not None and profile["samples"] == 10
    saved = json.loads((tmp_path / vm.PROFILE_NAME).read_text())
    assert saved["samples"] == 10 and "RED_VOICE_MATCH=on" in " ".join(out)


def test_voice_setup_without_the_voice_model_still_learns_the_words(tmp_path):
    profile = run_setup(tmp_path, record=lambda **kw: Audio(), transcribe=lambda a: "Hey Red",
                        say=lambda t: None, chime=lambda: None, out=lambda t: None)
    assert profile is not None and not (tmp_path / vm.PROFILE_NAME).exists()


# --- the real model on the saved recordings (only if it's already downloaded) ------------

MODEL_DIR = Path(r"D:\RED\models\wakeword")


@pytest.mark.skipif(not (MODEL_DIR / vm.MODEL_NAME).exists(), reason="voice match model not downloaded")
def test_the_real_model_tells_the_owner_from_others():
    model = vm.VoiceModel(MODEL_DIR)
    profile = vm.make_profile([model.embed(load(f"owner_enrol_{i}")) for i in range(1, 5)])
    owner = np.asarray(profile["mean"], dtype=np.float32)
    check = vm.OwnerCheck(model, owner, threshold=vm.DEFAULT_THRESHOLD)
    for name in ("owner_test_1", "owner_test_2"):
        assert check(load(name)), (name, check.last_score)
    for name in ("other_ryan", "other_alan", "other_libritts"):
        assert not check(load(name)), (name, check.last_score)
