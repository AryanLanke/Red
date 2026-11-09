"""Answer only the owner: is this "Hey Red" in your voice? (plan.md task 8)

`python -m red voice-setup` records "Hey Red" 10 times. Besides the words
(red/voice_setup.py), each recording is turned into a voice embedding: 512
numbers from a small speaker-recognition model, CAM++ from 3D-Speaker (29.6 MB
ONNX, pinned by SHA-256, run with onnxruntime, which Red already uses). The
embeddings, never the audio, are saved in
RED_HOME\\models\\wakeword\\owner_voice.json.

With RED_VOICE_MATCH=on, every "Hey Red" the detector hears is compared with
them (cosine similarity). Below RED_VOICE_MATCH_THRESHOLD, Red stays silent.
The hotkey always works. Off by default until the user has tried it with
another person speaking.

The model wants 80-band log-mel features ("fbank", like Kaldi's) with the
mean over time taken off; `fbank()` computes them with numpy.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Callable, Sequence

import numpy as np

from .audio import SAMPLE_RATE, PinnedFiles, to_float32
from .llm import Asset

log = logging.getLogger(__name__)

MODEL_NAME = "3dspeaker_speech_campplus_sv_en_voxceleb_16k.onnx"
MODEL = PinnedFiles(
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models/",
    (Asset(MODEL_NAME, "357a834f702b80161e5b981182c038e18553c1f2ca752ed6cec2052365d4129b"),),
)
PROFILE_NAME = "owner_voice.json"
# On Piper test voices (2026-11-09, progress.md 7.2) the owner's own clips scored
# at least 0.61 (Joe) and 0.73 (Amy), other voices 0.20 and 0.32 on average: at 0.60
# no owner clip was refused, no voice got in as Joe, and 6% got in as Amy. Real microphones will differ, so
# voice-setup works out a threshold for you (see make_profile) and this is the fallback.
DEFAULT_THRESHOLD = 0.60
MARGIN = 0.10              # below your own weakest recording
LOWEST, HIGHEST = 0.40, 0.75
MIN_SECONDS = 0.4          # shorter than this, a voice can't be told apart

# --- features -------------------------------------------------------------------------

FRAME, HOP, FFT, MELS = 400, 160, 512, 80      # 25 ms frames every 10 ms at 16 kHz


def _mel_bank() -> np.ndarray:
    """Kaldi's triangular mel filters (20 Hz to 8 kHz), on the FFT bins."""
    def mel(f):
        return 1127.0 * np.log1p(np.asarray(f, dtype=np.float64) / 700.0)
    low, high = mel(20.0), mel(SAMPLE_RATE / 2)
    centers = np.linspace(low, high, MELS + 2)
    bins = mel(np.arange(FFT // 2 + 1) * SAMPLE_RATE / FFT)
    bank = np.zeros((MELS, FFT // 2 + 1), dtype=np.float64)
    for m in range(MELS):
        left, mid, right = centers[m], centers[m + 1], centers[m + 2]
        up = (bins - left) / (mid - left)
        down = (right - bins) / (right - mid)
        bank[m] = np.clip(np.minimum(up, down), 0.0, None)
    return bank


_BANK = _mel_bank()
_WINDOW = (0.5 - 0.5 * np.cos(2 * np.pi * np.arange(FRAME) / (FRAME - 1))) ** 0.85   # Povey


def fbank(audio) -> np.ndarray:
    """16 kHz audio -> (frames, 80) log-mel features, mean over time removed."""
    x = to_float32(audio).astype(np.float64)
    if x.size < FRAME:
        return np.zeros((0, MELS), dtype=np.float32)
    n = 1 + (x.size - FRAME) // HOP
    idx = np.arange(FRAME)[None, :] + HOP * np.arange(n)[:, None]
    frames = x[idx]
    frames = frames - frames.mean(axis=1, keepdims=True)                 # remove DC
    frames = np.concatenate([frames[:, :1] * 0.03, frames[:, 1:] - 0.97 * frames[:, :-1]], axis=1)
    power = np.abs(np.fft.rfft(frames * _WINDOW, n=FFT)) ** 2
    # Kaldi's floor (float32 epsilon), with samples in [-1, 1] as the model expects.
    feats = np.log(np.maximum(power @ _BANK.T, np.finfo(np.float32).eps))
    feats -= feats.mean(axis=0, keepdims=True)                           # "global-mean"
    return feats.astype(np.float32)


# --- embeddings -----------------------------------------------------------------------

def _onnx_session(path: Path):
    import onnxruntime as ort
    options = ort.SessionOptions()
    options.intra_op_num_threads = 2
    return ort.InferenceSession(str(path), options, providers=["CPUExecutionProvider"])


class VoiceModel:
    """audio -> a unit-length voice embedding. Loads the pinned model on first use."""

    def __init__(self, model_dir: Path, session_factory: Callable[[Path], object] = _onnx_session):
        self.model_dir = Path(model_dir)
        self._factory = session_factory
        self._session = None
        self._lock = threading.Lock()

    @property
    def path(self) -> Path:
        return self.model_dir / MODEL_NAME

    def download(self) -> Path:
        MODEL.ensure(self.model_dir, label="Voice match model")
        return self.path

    def embed(self, audio) -> np.ndarray | None:
        feats = fbank(audio)
        if feats.shape[0] < int(MIN_SECONDS * 100):
            return None
        with self._lock:
            if self._session is None:
                self.download()
                self._session = self._factory(self.path)
            out = self._session.run(None, {"x": feats[None, :, :]})[0]
        vec = np.asarray(out, dtype=np.float32).reshape(-1)
        norm = float(np.linalg.norm(vec))
        return vec / norm if norm > 0 else None


def similarity(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-9))


# --- the owner's profile --------------------------------------------------------------

def profile_path(model_dir: Path) -> Path:
    return Path(model_dir) / PROFILE_NAME


def make_profile(embeddings: Sequence[np.ndarray], now: datetime | None = None) -> dict:
    vecs = [np.asarray(e, dtype=np.float32) for e in embeddings if e is not None]
    if not vecs:
        raise ValueError("no usable recordings")
    mean = np.mean(vecs, axis=0)
    mean /= np.linalg.norm(mean) + 1e-9
    # Each recording against the others' average: how a new "Hey Red" of yours
    # will score. Your threshold sits a little below the weakest.
    if len(vecs) >= 3:
        own = [similarity(v, np.mean(vecs[:i] + vecs[i + 1:], axis=0)) for i, v in enumerate(vecs)]
    else:
        own = [similarity(v, mean) for v in vecs]
    threshold = min(max(min(own) - MARGIN, LOWEST), HIGHEST)
    return {"model": MODEL_NAME, "mean": [round(float(x), 6) for x in mean],
            "samples": len(vecs), "own_lowest": round(min(own), 3),
            "threshold": round(threshold, 3),
            "created": (now or datetime.now()).isoformat(timespec="seconds")}


def save_profile(model_dir: Path, profile: dict) -> Path:
    path = profile_path(model_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(profile), encoding="utf-8")
    return path


def load_profile(model_dir: Path) -> tuple[np.ndarray, float | None] | None:
    """(your voice, the threshold voice-setup worked out), or None."""
    try:
        data = json.loads(profile_path(model_dir).read_text(encoding="utf-8"))
        if data.get("model") != MODEL_NAME:
            return None
        mean = np.asarray(data["mean"], dtype=np.float32)
        threshold = data.get("threshold")
        threshold = float(threshold) if isinstance(threshold, (int, float)) else None
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return (mean, threshold) if mean.shape == (512,) else None


# --- settings -------------------------------------------------------------------------

def settings_from_env() -> tuple[bool, float | None]:
    """(RED_VOICE_MATCH is on, RED_VOICE_MATCH_THRESHOLD or None), as red.config reads them."""
    on = os.environ.get("RED_VOICE_MATCH", "").strip().lower() in {"on", "1", "true", "yes"}
    text = os.environ.get("RED_VOICE_MATCH_THRESHOLD", "").strip()
    try:
        threshold = min(max(float(text), 0.0), 1.0) if text else None
    except ValueError:
        threshold = None
    return on, threshold


class OwnerCheck:
    """For the wake word detector: is this clip the owner's voice?"""

    def __init__(self, model: VoiceModel, owner: np.ndarray, threshold: float = DEFAULT_THRESHOLD):
        self.model, self.owner, self.threshold = model, owner, threshold
        self.last_score: float | None = None

    @classmethod
    def create(cls, model_dir: Path) -> "OwnerCheck | None":
        """None when voice match is off or there's no profile (then everyone wakes Red)."""
        on, threshold = settings_from_env()
        if not on:
            return None
        found = load_profile(model_dir)
        if found is None:
            log.warning("RED_VOICE_MATCH is on, but there's no voice profile yet. Run voice-setup.")
            return None
        owner, yours = found
        threshold = threshold if threshold is not None else (yours or DEFAULT_THRESHOLD)
        log.info("Voice match is on (threshold %.2f)", threshold)
        return cls(VoiceModel(model_dir), owner, threshold)

    def __call__(self, audio) -> bool:
        try:
            vec = self.model.embed(audio)
        except Exception:  # noqa: BLE001 - a broken model must not lock the owner out
            log.exception("Voice match failed; letting this one through")
            return True
        if vec is None:
            self.last_score = None
            return True               # too short to judge: the words already matched
        self.last_score = similarity(vec, self.owner)
        ok = self.last_score >= self.threshold
        log.info("Voice match: %.2f (%s)", self.last_score, "you" if ok else "not you, ignored")
        return ok
