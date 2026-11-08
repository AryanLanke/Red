"""Speech to text with Whisper through faster-whisper.

The model is pinned to a Hugging Face commit and SHA-256 per file and stored
under RED_HOME\\models\\whisper\\<model>. It loads on first use: on the GPU
(float16) when CUDA works, otherwise on the CPU (int8). Any CUDA error, at
load time or during the first transcription, switches to the CPU for the rest
of the session.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Callable

import numpy as np

from red.audio import PinnedFiles, hf_url, to_float32
from red.llm import Asset

log = logging.getLogger(__name__)

DEVICE_CHOICES = ("auto", "cuda", "cpu")

WHISPER_MODELS: dict[str, PinnedFiles] = {
    "small": PinnedFiles(
        hf_url("Systran/faster-whisper-small", "536b0662742c02347bc0e980a01041f333bce120"),
        (
            Asset("config.json", "b55496ac7940a7ae47d2c01eab40edfd8701feec1229d9cce3b40014383fb828"),
            Asset("model.bin", "3e305921506d8872816023e4c273e75d2419fb89b24da97b4fe7bce14170d671"),
            Asset("tokenizer.json", "fb7b63191e9bb045082c79fd742a3106a12c99513ab30df4a0d47fa6cb6fd0ab"),
            Asset("vocabulary.txt", "34ce3fe1c5041027b3f8d42912270993f986dbc4bb34cf27f951e34a1e453913"),
        ),
    ),
}

COMPUTE_TYPE = {"cuda": "float16", "cpu": "int8"}

# (model folder, device, compute type) -> an object with faster-whisper's transcribe()
ModelFactory = Callable[[str, str, str], object]


def cuda_available() -> bool:
    try:
        import ctranslate2
        return ctranslate2.get_cuda_device_count() > 0
    except Exception:
        return False


def _faster_whisper_model(path: str, device: str, compute_type: str):
    from faster_whisper import WhisperModel
    return WhisperModel(path, device=device, compute_type=compute_type)


class Transcriber:
    def __init__(self, model_dir: Path, model: str = "small", device: str = "auto", *,
                 language: str | None = "en", beam_size: int = 5,
                 model_factory: ModelFactory = _faster_whisper_model,
                 cuda_check: Callable[[], bool] = cuda_available):
        if model not in WHISPER_MODELS:
            raise ValueError(f"Unknown Whisper model {model!r}; choose from {sorted(WHISPER_MODELS)}")
        device = device.lower()
        if device not in DEVICE_CHOICES:
            raise ValueError(f"Whisper device must be one of {DEVICE_CHOICES}, got {device!r}")
        self.model_dir = Path(model_dir)
        self.model_name = model
        self.requested_device = device
        self.language = language
        self.beam_size = beam_size
        self._factory = model_factory
        self._cuda_check = cuda_check
        self._model = None
        self.device: str | None = None      # the device actually in use, once loaded
        self._lock = threading.Lock()

    @property
    def path(self) -> Path:
        return self.model_dir / self.model_name

    @property
    def compute_type(self) -> str | None:
        return COMPUTE_TYPE.get(self.device) if self.device else None

    @property
    def loaded(self) -> bool:
        return self._model is not None

    def download(self) -> Path:
        """Fetch the pinned model files if they're missing. Returns the model folder."""
        return WHISPER_MODELS[self.model_name].ensure(self.path, label=f"Whisper {self.model_name}")

    def _create(self, device: str):
        self._model = self._factory(str(self.path), device, COMPUTE_TYPE[device])
        self.device = device

    def load(self) -> None:
        """Load the model now instead of on the first transcription."""
        with self._lock:
            if self._model is not None:
                return
            self.download()
            want_gpu = self.requested_device == "cuda" or (
                self.requested_device == "auto" and self._cuda_check())
            if want_gpu:
                try:
                    self._create("cuda")
                    return
                except Exception as e:
                    log.warning("Whisper could not start on the GPU (%s); using the CPU.", e)
            self._create("cpu")

    def _fall_back_to_cpu(self, error: Exception) -> None:
        log.warning("Whisper failed on the GPU (%s); switching to the CPU.", error)
        with self._lock:
            self._model = None
            self._create("cpu")

    def _run(self, audio: np.ndarray) -> str:
        segments, _info = self._model.transcribe(
            audio,
            language=self.language,
            beam_size=self.beam_size,
            vad_filter=True,
            condition_on_previous_text=False,
            without_timestamps=True,
        )
        # segments is a generator: decoding (and any CUDA error) happens here.
        text = " ".join(s.text.strip() for s in segments)
        return " ".join(text.split())

    def transcribe(self, audio) -> str:
        """16 kHz mono audio -> text. Empty audio gives an empty string."""
        audio = to_float32(audio)
        if audio.size == 0:
            return ""
        self.load()
        try:
            return self._run(audio)
        except Exception as e:
            if self.device != "cuda":
                raise
            self._fall_back_to_cpu(e)
            return self._run(audio)
