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
LONG_PHRASE_SECONDS = 1.25         # a "Hey Red" alone is shorter; longer has a command after it
HEAD_SECONDS = 1.3                 # the start of a longer burst that is checked for "Hey Red"

_HEY = {"hey", "hay", "hei", "heh", "hej"}
_HEY_CLOSE = {"hi", "eh", "ay"}     # not "a": "a red car" must not match
_RED = {"red"}
_RED_CLOSE = {"redd", "rhed", "read", "wred", "rad", "rid"}
_MERGED = {"heyred": 0.9, "hayred": 0.8, "heyread": 0.5}


def _words(text: str) -> list[str]:
    return re.sub(r"[^a-z' ]", " ", text.lower().replace("-", " ")).split()


def phrase_key(text: str) -> str:
    """The first two words of a transcript, the part a wake phrase lives in."""
    return " ".join(_words(text)[:2])


def collapse_repeats(words: list[str]) -> list[str]:
    """'hey red red red red' and 'hey red hey red hey red' (Whisper repeats the phrase) -> 'hey red'."""
    out: list[str] = []
    for w in words:
        if not (out and out[-1] == w):
            out.append(w)
    i = 0
    while i + 4 <= len(out):
        if out[i:i + 2] == out[i + 2:i + 4]:
            del out[i + 2:i + 4]
        else:
            i += 1
    return out


def match_score(text: str, personal: frozenset[str] = frozenset(), head: bool = False) -> float:
    """How much a short transcript sounds like "Hey Red": 1.0, partial, or 0.

    Only the start of the clip counts, so "I read the red book" or "they said
    red" never match. A clip with more than a couple of extra words isn't a
    wake phrase either. `personal` holds how Whisper hears *your* "Hey Red"
    (from python -m red voice-setup); those count as a strong match.
    """
    words = collapse_repeats(_words(text))
    if head:
        words = words[:2]                # the rest of the sentence was cut off; only its start counts
    if not words or len(words) > 4:
        return 0.0
    if personal and " ".join(words[:2]) in personal:
        return 0.9 if len(words) <= 2 else 0.6
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


PROFILE_NAME = "hey_red_profile.json"


def load_profile(model_dir: Path) -> dict:
    """Your voice profile from voice-setup, or {} if there isn't one (or it's broken)."""
    import json

    path = Path(model_dir) / PROFILE_NAME
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def make_wake_transcriber(model_dir: Path):
    """Whisper tiny.en set up exactly as the detector uses it (voice-setup uses it too)."""
    from red.stt import Transcriber

    def factory(path: str, device: str, compute_type: str):
        from faster_whisper import WhisperModel
        return WhisperModel(path, device=device, compute_type=compute_type,
                            cpu_threads=WAKE_CPU_THREADS)

    return Transcriber(Path(model_dir).parent / "whisper", WAKE_WHISPER_MODEL, device="cpu",
                       beam_size=1, vad_filter=False, hotwords="Hey Red", max_new_tokens=12,
                       model_factory=factory)


class HeyRedDetector:
    """A Listener detector: score(int16 frame) -> 0..1, and reset().

    vad: 512-sample float32 chunk -> speech probability.
    transcribe: a short float32 clip -> text.
    """

    def __init__(self, vad: Callable[[np.ndarray], float], transcribe: Callable[[np.ndarray], str],
                 clock: Callable[[], float] = time.perf_counter, *,
                 personal: frozenset[str] = frozenset(), max_clip_seconds: float = MAX_CLIP_SECONDS,
                 owner: Callable[[np.ndarray], bool] | None = None):
        self._vad = vad
        # RED_VOICE_MATCH: is it the owner's voice? (red/voice_match.py). None: anyone.
        self.owner = owner
        self._transcribe = transcribe
        self._clock = clock
        self.personal = frozenset(personal)
        self.max_clip_seconds = max_clip_seconds
        self.evaluations = 0                 # clips sent to Whisper
        self.busy_seconds = 0.0              # time spent in Whisper
        self.last_text = ""
        self.reset()

    @classmethod
    def create(cls, model_dir: Path) -> "HeyRedDetector":
        """The real detector. model_dir is RED_HOME\models\wakeword; Whisper goes in models\whisper."""
        whisper = make_wake_transcriber(model_dir)
        whisper.load()
        profile = load_profile(model_dir)
        personal = frozenset(p for p in profile.get("phrases", []) if isinstance(p, str))
        max_clip = profile.get("max_clip_seconds", MAX_CLIP_SECONDS)
        if not isinstance(max_clip, (int, float)) or not 1.0 <= max_clip <= 3.0:
            max_clip = MAX_CLIP_SECONDS
        if personal:
            log.info("Using your voice profile for \"Hey Red\": %s", ", ".join(sorted(personal)))
        from .voice_match import OwnerCheck
        return cls(StreamingVAD(), whisper.transcribe, personal=personal,
                   max_clip_seconds=float(max_clip), owner=OwnerCheck.create(model_dir))

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

    def _evaluate(self, chunks: list | None = None, head: bool = False) -> float:
        """Score a clip. head: only the start of a longer burst ("Hey Red, open YouTube")."""
        clip = np.concatenate((chunks or self._clip) + [np.zeros(int(0.2 * SAMPLE_RATE), np.float32)])
        t0 = self._clock()
        text = self._transcribe(clip)
        self.busy_seconds += self._clock() - t0
        self.evaluations += 1
        self.last_text = text
        score = match_score(text, self.personal, head=head)
        # Logged so a missed "Hey Red" can be explained (RED_HOME\logs\red.log).
        # The loudness shows a microphone that is too quiet.
        log.info("Wake check: heard %r (score %.2f, %s, peak %.2f)", text[:60], score,
                 "start of a longer phrase" if head else "short phrase", float(np.abs(clip).max()))
        if score > 0 and self.owner is not None and not self.owner(clip):
            return 0.0                       # the right words, but not your voice
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
        if self._speech_chunks > self._chunks_for(self.max_clip_seconds) and not self._too_long:
            self._too_long = True
            # Said in one breath ("Hey Red, open YouTube"): look at just the start, once.
            if self._start_quiet >= self._chunks_for(PAUSE_BEFORE_SECONDS):
                head = self._clip[:self._preroll + self._chunks_for(HEAD_SECONDS)]
                score = self._evaluate(head, head=True)
                if score > 0:
                    return score
        if self._quiet_run < self._chunks_for(PAUSE_AFTER_SECONDS):
            return 0.0

        # The burst of speech is over.
        score = 0.0
        long_enough = self._speech_chunks >= self._chunks_for(MIN_CLIP_SECONDS)
        if (not self._too_long and long_enough
                and self._start_quiet >= self._chunks_for(PAUSE_BEFORE_SECONDS)):
            # Over about 1.25 s it is "Hey Red" plus words, not a bare phrase: only its start counts.
            score = self._evaluate(head=self._speech_chunks > self._chunks_for(LONG_PHRASE_SECONDS))
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
