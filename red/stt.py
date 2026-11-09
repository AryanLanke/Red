"""Speech to text with Whisper through faster-whisper.

The model is pinned to a Hugging Face commit and SHA-256 per file and stored
under RED_HOME\\models\\whisper\\<model>. It loads on first use: on the GPU
(float16) when CUDA works, otherwise on the CPU (int8). Any CUDA error, at
load time or during the first transcription, switches to the CPU for the rest
of the session.
"""

from __future__ import annotations

import logging
import re
import threading
from pathlib import Path
from typing import Callable

import numpy as np

from red.audio import SAMPLE_RATE, PinnedFiles, hf_url, to_float32
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
    # Small English-only models, used by the "Hey Red" wake word detector.
    "tiny.en": PinnedFiles(
        hf_url("Systran/faster-whisper-tiny.en", "0d3d19a32d3338f10357c0889762bd8d64bbdeba"),
        (
            Asset("config.json", "14b1b421a90349bc551b881461426b561a874049cb9e4c4864f2ca384f6a7cc5"),
            Asset("model.bin", "1a5afae06a4db91c975c9a9d78be5cc110ee4ea022ad57d55492e4550e936b2a"),
            Asset("tokenizer.json", "929c5252409436dce1b38a75d1abbcb5e132d170d8e324e4e04ed915fa2d22df"),
            Asset("vocabulary.txt", "ff77588746d3a2595d32ab5b69ffd7b95ce2441ac57533cb66fc3eb575a115cf"),
        ),
    ),
    # For PCs with an 8 GB+ GPU, where it runs on the GPU next to the model.
    "small.en": PinnedFiles(
        hf_url("Systran/faster-whisper-small.en", "d1d751a5f8271d482d14ca55d9e2deeebbae577f"),
        (
            Asset("config.json", "666a9605530ac1f61fa8177f3702b4dacec9966749e42610839fcc32661d5fae"),
            Asset("model.bin", "62b2a45b05ee59acb4a5341b33ee35e041395d378d418a18acfe4c9e768ee37a"),
            Asset("tokenizer.json", "929c5252409436dce1b38a75d1abbcb5e132d170d8e324e4e04ed915fa2d22df"),
            Asset("vocabulary.txt", "ff77588746d3a2595d32ab5b69ffd7b95ce2441ac57533cb66fc3eb575a115cf"),
        ),
    ),
    "base.en": PinnedFiles(
        hf_url("Systran/faster-whisper-base.en", "3d3d5dee26484f91867d81cb899cfcf72b96be6c"),
        (
            Asset("config.json", "f3bc3821e9fc76a27bae538e11ae5b677dcdd352b4600429ce7951d398569aeb"),
            Asset("model.bin", "2a166925539a16005f14ff328359f9b9adb9dc4fb631bb3b227526862e93e2ef"),
            Asset("tokenizer.json", "929c5252409436dce1b38a75d1abbcb5e132d170d8e324e4e04ed915fa2d22df"),
            Asset("vocabulary.txt", "ff77588746d3a2595d32ab5b69ffd7b95ce2441ac57533cb66fc3eb575a115cf"),
        ),
    ),
}

COMPUTE_TYPE = {"cuda": "float16", "cpu": "int8"}

# Names Whisper mishears without help ("Heiko Pilot", "Hey CD"). Given to
# faster-whisper as hotwords: on Piper test sentences, base.en got 97% of
# these names right with them and 87% without, in the same time
# (progress.md 7.2). Kept short: a long prompt slows Whisper down and can
# make it invent words.
BASE_VOCABULARY = ("Hey Copilot", "Hey Siri", "Alexa", "OK Google", "Gemini", "YouTube",
                   "Chrome", "Edge", "Red")
MAX_VOCABULARY_CHARS = 250

# Split forms of "Copilot" that remain even with the hotwords.
_COPILOT = re.compile(r"\b(?:hey\s*co|heyco|heiko|haco|haeco)[\s-]*pilot\b", re.IGNORECASE)


def command_vocabulary(*names: str) -> str:
    """The hotwords for commands: the fixed names, then app and contact names, kept short."""
    seen: set[str] = set()
    words: list[str] = []
    size = 0
    for name in (*BASE_VOCABULARY, *names):
        name = " ".join(str(name).split())
        key = name.lower()
        if not name or key in seen or len(name) > 40:
            continue
        if size + len(name) + 2 > MAX_VOCABULARY_CHARS:
            break
        seen.add(key)
        words.append(name)
        size += len(name) + 2
    return ", ".join(words)


def fix_names(text: str) -> str:
    """'Heyco Pilot' -> 'Hey Copilot'."""
    return _COPILOT.sub("Hey Copilot", text)

# (model folder, device, compute type) -> an object with faster-whisper's transcribe()
ModelFactory = Callable[[str, str, str], object]


def cuda_available() -> bool:
    try:
        import ctranslate2
        return ctranslate2.get_cuda_device_count() > 0
    except Exception:
        return False


def add_nvidia_dll_dirs() -> list[str]:
    """Let CTranslate2 find cuBLAS/cuDNN from the optional nvidia-*-cu12 pip packages.

    Only this process's PATH changes. Returns the folders that were added.
    """
    import importlib.util
    import os

    spec = importlib.util.find_spec("nvidia")
    if spec is None or not spec.submodule_search_locations:
        return []
    added = []
    path = os.environ.get("PATH", "")
    for root in spec.submodule_search_locations:
        for pkg in ("cublas", "cudnn", "cuda_runtime", "cuda_nvrtc"):
            d = Path(root) / pkg / "bin"
            if d.is_dir() and str(d) not in path:
                added.append(str(d))
    if added:
        os.environ["PATH"] = os.pathsep.join(added + [path])
        for d in added:
            os.add_dll_directory(d)
    return added


def _faster_whisper_model(path: str, device: str, compute_type: str):
    from faster_whisper import WhisperModel
    return WhisperModel(path, device=device, compute_type=compute_type)


class Transcriber:
    def __init__(self, model_dir: Path, model: str = "small", device: str = "auto", *,
                 language: str | None = "en", beam_size: int = 5,
                 vad_filter: bool = True, hotwords: str | None = None,
                 max_new_tokens: int | None = None,
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
        self.vad_filter = vad_filter
        self.hotwords = hotwords
        self.max_new_tokens = max_new_tokens
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
        model = self._factory(str(self.path), device, COMPUTE_TYPE[device])
        if device == "cuda":
            # CUDA libraries load lazily, so a missing cuBLAS only shows up when
            # the model first runs. Run it once now, so a failure falls back to
            # the CPU at startup instead of during your first command.
            segments, _ = model.transcribe(np.zeros(SAMPLE_RATE, np.float32), language=self.language,
                                           beam_size=1, vad_filter=False, without_timestamps=True)
            list(segments)
        self._model = model
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
                add_nvidia_dll_dirs()
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
        extra = {"max_new_tokens": self.max_new_tokens} if self.max_new_tokens else {}
        segments, _info = self._model.transcribe(
            audio,
            language=self.language,
            beam_size=self.beam_size,
            vad_filter=self.vad_filter,
            hotwords=self.hotwords,
            condition_on_previous_text=False,
            without_timestamps=True,
            **extra,
        )
        # segments is a generator: decoding (and any CUDA error) happens here.
        text = " ".join(s.text.strip() for s in segments)
        return fix_names(" ".join(text.split()))

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
