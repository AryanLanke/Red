"""Speech to text with Whisper through faster-whisper.

The model is pinned to a Hugging Face commit and SHA-256 per file and stored
under RED_HOME\\models\\whisper\\<model>. It loads on first use: on the GPU
(float16) when CUDA works, otherwise on the CPU (int8). Any CUDA error, at
load time or during the first transcription, switches to the CPU for the rest
of the session.
"""

from __future__ import annotations

import contextlib
import functools
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


def read_vocabulary(path: Path | str | None) -> list[str]:
    """Names from RED_HOME\\config\\vocabulary.txt: one per line, # comments and blanks skipped.

    The user writes artist names ("LE SSERAFIM", "Arijit Singh") here so Whisper
    hears them right; the file is read on every transcription, so edits apply
    without restarting Red.
    """
    if path is None:
        return []
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return []
    names = []
    for line in lines:
        name = line.split("#", 1)[0].strip()
        if name:
            names.append(name)
    return names


def command_vocabulary(*names: str, first: tuple[str, ...] = ()) -> str:
    """The hotwords for commands: `first` (the user's name, the companions), the fixed names, then app
    and contact names, kept short."""
    seen: set[str] = set()
    words: list[str] = []
    size = 0
    for name in (*first, *BASE_VOCABULARY, *names):
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


# --- A shorter encoder window ------------------------------------------------
#
# Whisper's encoder always reads 30 s of audio, padded with silence, so a 2 s
# command costs as much as a 30 s one: about 0.5 s on this CPU (base.en). The
# encoder works on any shorter window too. Measured on this PC's 10 recorded
# "Hey Red, open YouTube" clips (base.en, int8, 8 threads): 30 s window 0.62 s,
# 10 s window 0.19 s. But 4-10 s windows made Whisper repeat words on clean
# spoken test clips (word errors 170-300%), while 14 s kept them (7.2% against
# 6.9% for the full window) at 0.2 s instead of 0.52 s (scripts/voice_bench.py,
# progress.md "Hearing fast"). So: the clip's length plus a margin, at least
# 14 s, in steps of 2 s; the full 30 s for long clips; and a transcript that
# loops is redone with the full window.

FULL_WINDOW_FRAMES = 3000            # 30 s at Whisper's 100 frames per second
MIN_WINDOW_SECONDS = 14.0           # 4-10 s windows made Whisper loop on clean clips (voice_bench)
WINDOW_STEP_SECONDS = 2.0
WINDOW_MARGIN_SECONDS = 0.6
MAX_SHORT_WINDOW_SECONDS = 16.0      # longer clips use the full window

_window = threading.local()
_window_patched = False
_window_lock = threading.Lock()


def encoder_frames(seconds: float) -> int:
    """The encoder window, in 10 ms frames, for a clip `seconds` long."""
    want = max(MIN_WINDOW_SECONDS, seconds + WINDOW_MARGIN_SECONDS)
    steps = -(-want // WINDOW_STEP_SECONDS)             # round up to a whole step
    window = steps * WINDOW_STEP_SECONDS
    if window > MAX_SHORT_WINDOW_SECONDS:
        return FULL_WINDOW_FRAMES
    return int(window * 100)


def looks_looped(text: str, run: int = 5) -> bool:
    """Whisper stuck on one word or phrase: the same word `run` times in a row, or '//' loops."""
    words = text.lower().split()
    streak = 1
    for before, word in zip(words, words[1:]):
        streak = streak + 1 if word == before else 1
        if streak >= run:
            return True
    return False


def install_window_patch() -> bool:
    """Let this thread choose faster-whisper's encoder window (see above).

    faster-whisper pads every segment's features with `pad_or_trim(segment)`. This
    wraps that function so that, inside `short_window(...)`, it pads to the chosen
    length instead. Outside it nothing changes. Returns False (and the full window
    stays) if faster-whisper's internals are not what this expects.
    """
    global _window_patched
    with _window_lock:
        if _window_patched:
            return True
        try:
            import faster_whisper.transcribe as ft
            original = ft.pad_or_trim
            if not callable(original):
                return False
        except Exception:  # noqa: BLE001 - no faster-whisper: nothing to patch
            return False

        def pad_or_trim(array, length=FULL_WINDOW_FRAMES, *, axis=-1):
            frames = getattr(_window, "frames", None)
            if frames and length == FULL_WINDOW_FRAMES:
                length = frames
            return original(array, length, axis=axis)

        ft.pad_or_trim = pad_or_trim
        _window_patched = True
        return True


class short_window:
    """`with short_window(seconds):` Whisper runs in this thread with a window that fits the clip."""

    def __init__(self, seconds: float):
        self.frames = encoder_frames(seconds)

    def __enter__(self):
        self._before = getattr(_window, "frames", None)
        _window.frames = self.frames if self.frames < FULL_WINDOW_FRAMES else None
        return self

    def __exit__(self, *exc):
        _window.frames = self._before


def _faster_whisper_model(path: str, device: str, compute_type: str, cpu_threads: int = 0):
    from faster_whisper import WhisperModel
    install_window_patch()
    return WhisperModel(path, device=device, compute_type=compute_type, cpu_threads=cpu_threads)


class Transcriber:
    def __init__(self, model_dir: Path, model: str = "small", device: str = "auto", *,
                 language: str | None = "en", beam_size: int = 5,
                 vad_filter: bool = True, hotwords: str | None = None,
                 vocabulary_file: Path | str | None = None,
                 max_new_tokens: int | None = None, fit_window: bool = True, cpu_threads: int = 0,
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
        self.vocabulary_file = Path(vocabulary_file) if vocabulary_file else None
        self.max_new_tokens = max_new_tokens
        self.fit_window = fit_window              # fit Whisper's window to the clip (see above)
        if cpu_threads and model_factory is _faster_whisper_model:
            model_factory = functools.partial(_faster_whisper_model, cpu_threads=cpu_threads)
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

    def hotwords_text(self) -> str | None:
        """The names to bias Whisper toward: the fixed ones plus the user's vocabulary file."""
        names = read_vocabulary(self.vocabulary_file)
        if not names:
            return self.hotwords
        base = [n.strip() for n in (self.hotwords or "").split(",") if n.strip()]
        return command_vocabulary(*base, *names)

    def _run(self, audio: np.ndarray, full: bool = False) -> str:
        extra = {"max_new_tokens": self.max_new_tokens} if self.max_new_tokens else {}
        window = short_window(audio.size / SAMPLE_RATE) if self.fit_window and not full else contextlib.nullcontext()
        with window:
            segments, _info = self._model.transcribe(
                audio,
                language=self.language,
                beam_size=self.beam_size,
                vad_filter=self.vad_filter,
                hotwords=self.hotwords_text(),
                condition_on_previous_text=False,
                without_timestamps=True,
                **extra,
            )
            # segments is a generator: decoding (and any CUDA error) happens here.
            text = " ".join(s.text.strip() for s in segments)
        text = " ".join(text.split())
        if self.fit_window and not full and looks_looped(text) and audio.size / SAMPLE_RATE < MAX_SHORT_WINDOW_SECONDS:
            log.info("Whisper repeated itself with a short window; running again with the full one.")
            return self._run(audio, full=True)
        return fix_names(text)

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
