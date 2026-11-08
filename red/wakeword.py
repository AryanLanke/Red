"""The "Hey Red" wake word, without a trained model.

How it works:
1. A voice activity detector (Silero VAD, which ships with faster-whisper)
   runs on every 32 ms of audio. It is very cheap.
2. Only a short burst of speech with a pause before and after it, the way
   people say a wake phrase, is passed on. Long speech, as in a conversation
   or a video, is skipped without running anything else.
3. That clip goes to Whisper tiny.en on the CPU (about 0.3 s of work on two
   threads), nudged towards "Hey Red" with Whisper's hotwords option.
4. The transcript is matched against "hey red" and close variants.

The score is 1.0 for an exact "hey red", lower for close variants, and 0
otherwise; RED_WAKEWORD_THRESHOLD (default 0.5) decides which count.

Say "Hey Red", pause briefly, then wait for the beep before the command.
"""

from __future__ import annotations

import logging
import re
import time
from collections import deque
from pathlib import Path
from typing import Callable

import numpy as np

from red.audio import SAMPLE_RATE, to_float32

log = logging.getLogger(__name__)

HEY_RED = "hey_red"
WAKE_WHISPER_MODEL = "tiny.en"
WAKE_CPU_THREADS = 2

VAD_CHUNK = 512                    # Silero works on 32 ms chunks at 16 kHz
VAD_CONTEXT = 64
SPEECH_ON = 0.5                    # VAD probability that starts speech
SPEECH_OFF = 0.35                  # ... and that counts as silence again
MIN_CLIP_SECONDS = 0.35            # "Hey Red" takes about 0.5-1.1 s
MAX_CLIP_SECONDS = 1.6
PAUSE_BEFORE_SECONDS = 0.25        # quiet needed before the phrase
PAUSE_AFTER_SECONDS = 0.3          # quiet that ends the phrase
PRE_ROLL_SECONDS = 0.2

_HEY = {"hey", "hay", "hei", "heh", "hej"}
_HEY_CLOSE = {"hi", "eh", "ay"}     # not "a": "a red car" must not match
_RED = {"red"}
_RED_CLOSE = {"redd", "rhed", "read", "wred", "rad", "rid"}
_MERGED = {"heyred": 0.9, "hayred": 0.8, "heyread": 0.5}


def _words(text: str) -> list[str]:
    return re.sub(r"[^a-z' ]", " ", text.lower().replace("-", " ")).split()


def match_score(text: str) -> float:
    """How much a short transcript sounds like "Hey Red": 1.0, partial, or 0.

    Only the start of the clip counts, so "I read the red book" or "they said
    red" never match. A clip with more than a couple of extra words isn't a
    wake phrase either.
    """
    words = _words(text)
    if not words or len(words) > 4:
        return 0.0
    if words[0] in _MERGED:
        return _MERGED[words[0]]
    if len(words) < 2:
        return 0.0
    first, second = words[0], words[1]
    if first in _HEY:
        hey = 1.0
    elif first in _HEY_CLOSE:
        hey = 0.7
    else:
        return 0.0
    if second in _RED:
        red = 1.0
    elif second in _RED_CLOSE:
        red = 0.6
    else:
        return 0.0
    # The phrase is said on its own, so extra words make it unlikely: Whisper's
    # "Hey Red" bias can turn "a red light" into "Hey Red Light".
    extra = 0.45 if len(words) > 2 else 1.0
    return round(hey * red * extra, 3)


class StreamingVAD:
    """Silero VAD run on a live stream, 512 samples at a time, keeping its state."""

    def __init__(self, model_path: str | None = None):
        import onnxruntime
        if model_path is None:
            from faster_whisper.utils import get_assets_path
            model_path = str(Path(get_assets_path()) / "silero_vad_v6.onnx")
        opts = onnxruntime.SessionOptions()
        opts.inter_op_num_threads = 1
        opts.intra_op_num_threads = 1
        opts.log_severity_level = 4
        self._session = onnxruntime.InferenceSession(model_path, providers=["CPUExecutionProvider"],
                                                     sess_options=opts)
        self.reset()

    def reset(self) -> None:
        self._h = np.zeros((1, 1, 128), np.float32)
        self._c = np.zeros((1, 1, 128), np.float32)
        self._context = np.zeros(VAD_CONTEXT, np.float32)

    def __call__(self, chunk: np.ndarray) -> float:
        """Speech probability for one 512-sample float32 chunk."""
        x = np.concatenate([self._context, chunk]).reshape(1, -1).astype(np.float32)
        out, self._h, self._c = self._session.run(None, {"input": x, "h": self._h, "c": self._c})
        self._context = chunk[-VAD_CONTEXT:]
        return float(np.asarray(out).reshape(-1)[0])


class HeyRedDetector:
    """A Listener detector: score(int16 frame) -> 0..1, and reset().

    vad: 512-sample float32 chunk -> speech probability.
    transcribe: a short float32 clip -> text.
    """

    def __init__(self, vad: Callable[[np.ndarray], float], transcribe: Callable[[np.ndarray], str],
                 clock: Callable[[], float] = time.perf_counter):
        self._vad = vad
        self._transcribe = transcribe
        self._clock = clock
        self.evaluations = 0                 # clips sent to Whisper
        self.busy_seconds = 0.0              # time spent in Whisper
        self.last_text = ""
        self.reset()

    @classmethod
    def create(cls, model_dir: Path) -> "HeyRedDetector":
        """The real detector. model_dir is RED_HOME\\models\\wakeword; Whisper goes in models\\whisper."""
        from red.stt import Transcriber

        def factory(path: str, device: str, compute_type: str):
            from faster_whisper import WhisperModel
            return WhisperModel(path, device=device, compute_type=compute_type,
                                cpu_threads=WAKE_CPU_THREADS)

        whisper = Transcriber(Path(model_dir).parent / "whisper", WAKE_WHISPER_MODEL, device="cpu",
                              beam_size=1, vad_filter=False, hotwords="Hey Red", max_new_tokens=12,
                              model_factory=factory)
        whisper.load()
        return cls(StreamingVAD(), whisper.transcribe)

    def reset(self) -> None:
        if hasattr(self._vad, "reset"):
            self._vad.reset()
        self._pending = np.zeros(0, np.float32)
        self._history: deque[np.ndarray] = deque(maxlen=int(PRE_ROLL_SECONDS * SAMPLE_RATE / VAD_CHUNK) + 1)
        self._clip: list[np.ndarray] | None = None
        self._speech_chunks = 0
        self._quiet_run = 0
        self._quiet_before = 10 ** 6         # the stream starts quiet
        self._too_long = False

    def _chunks_for(self, seconds: float) -> int:
        return int(round(seconds * SAMPLE_RATE / VAD_CHUNK))

    def _evaluate(self) -> float:
        clip = np.concatenate(self._clip + [np.zeros(int(0.2 * SAMPLE_RATE), np.float32)])
        t0 = self._clock()
        text = self._transcribe(clip)
        self.busy_seconds += self._clock() - t0
        self.evaluations += 1
        self.last_text = text
        score = match_score(text)
        log.debug("Wake clip %.2f s heard %r (score %.2f)", clip.size / SAMPLE_RATE, text, score)
        return score

    def _step(self, chunk: np.ndarray) -> float:
        p = self._vad(chunk)
        if self._clip is None:
            if p >= SPEECH_ON:
                self._clip = list(self._history) + [chunk]
                self._preroll = len(self._history)
                self._speech_chunks = 1
                self._quiet_run = 0
                self._too_long = False
                self._start_quiet = self._quiet_before
            else:
                self._quiet_before += 1
            self._history.append(chunk)
            return 0.0

        self._clip.append(chunk)
        if p < SPEECH_OFF:
            self._quiet_run += 1
        else:
            self._quiet_run = 0
            self._speech_chunks = len(self._clip) - self._preroll
        if self._speech_chunks > self._chunks_for(MAX_CLIP_SECONDS):
            self._too_long = True
        if self._quiet_run < self._chunks_for(PAUSE_AFTER_SECONDS):
            return 0.0

        # The burst of speech is over.
        score = 0.0
        long_enough = self._speech_chunks >= self._chunks_for(MIN_CLIP_SECONDS)
        if (not self._too_long and long_enough
                and self._start_quiet >= self._chunks_for(PAUSE_BEFORE_SECONDS)):
            score = self._evaluate()
        self._clip = None
        self._quiet_before = self._quiet_run
        self._history.clear()
        return score

    def score(self, frame: np.ndarray) -> float:
        """Feed one frame (int16 or float32, 16 kHz). Returns the best score in it."""
        audio = np.concatenate([self._pending, to_float32(frame)])
        best = 0.0
        n = audio.size // VAD_CHUNK * VAD_CHUNK
        for i in range(0, n, VAD_CHUNK):
            best = max(best, self._step(audio[i:i + VAD_CHUNK]))
        self._pending = audio[n:]
        return best
