"""The training script's pieces that don't need Piper or long runs."""

import importlib.util
import random
from pathlib import Path

import numpy as np
import pytest

from red.audio import SAMPLE_RATE

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "train_hey_red" / "hey_red.py"


@pytest.fixture(scope="module")
def hey_red():
    spec = importlib.util.spec_from_file_location("hey_red_train", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_phrase_is_placed_near_the_end_of_the_window(hey_red):
    rng = np.random.default_rng(0)
    phrase = np.ones(int(0.8 * SAMPLE_RATE), np.float32)
    for _ in range(20):
        out = hey_red.place_at_end(phrase, rng)
        assert out.size == int(hey_red.CLIP_SECONDS * SAMPLE_RATE)
        last = np.flatnonzero(out)[-1]
        assert out.size - last <= 0.3 * SAMPLE_RATE + 1
        assert np.count_nonzero(out) == phrase.size


def test_augment_keeps_length_and_range(hey_red):
    rng = np.random.default_rng(0)
    x = np.sin(np.linspace(0, 200, 32000)).astype(np.float32)
    babble = np.random.default_rng(1).standard_normal(64000).astype(np.float32)
    for _ in range(10):
        y = hey_red.augment(x, rng, babble)
        assert y.shape == x.shape and y.dtype == np.float32
        assert 0 < np.max(np.abs(y)) <= 0.9 + 1e-6


def test_held_out_voices_are_never_trained_on(hey_red):
    assert hey_red.TRAIN_VOICE not in hey_red.HELD_OUT_VOICES
    from red.tts import PIPER_VOICES
    assert all(v in PIPER_VOICES for v in hey_red.HELD_OUT_VOICES + [hey_red.TRAIN_VOICE])


def test_no_other_assistant_name_is_a_positive(hey_red):
    assert all("red" in p.lower() for p in hey_red.POSITIVE)
    rnd = random.Random(0)
    assert all(isinstance(hey_red.random_sentence(rnd), str) for _ in range(20))


def test_onnx_export_matches_torch_and_loads_in_openwakeword(hey_red, tmp_path):
    torch = pytest.importorskip("torch")
    pytest.importorskip("onnx")
    from torch import nn
    model = nn.Sequential(nn.Flatten(), nn.Linear(16 * 96, 8), nn.LayerNorm(8), nn.ReLU(),
                          nn.Linear(8, 1))
    path = tmp_path / "hey_red_test.onnx"
    hey_red.export_onnx(model, path)            # asserts ONNX == torch inside

    from openwakeword.model import Model
    from red.config import red_home
    wake = red_home() / "models" / "wakeword"
    if not (wake / "melspectrogram.onnx").exists():
        pytest.skip("openWakeWord feature models not downloaded")
    m = Model(wakeword_models=[str(path)], inference_framework="onnx",
              melspec_model_path=str(wake / "melspectrogram.onnx"),
              embedding_model_path=str(wake / "embedding_model.onnx"))
    scores = m.predict(np.zeros(1280, np.int16))
    assert list(scores) == ["hey_red_test"]
