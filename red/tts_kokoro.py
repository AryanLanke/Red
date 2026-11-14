"""Text to speech with Kokoro: a more natural voice than Piper, still on this PC.

Kokoro-82M (Apache-2.0) runs on the CPU through the onnxruntime Red already has.
Its text goes through the espeak-ng that piper-tts already bundles, so no new
native code is installed (the kokoro-onnx package would add its own unsigned
espeak-ng DLL). Checked on 2026-11-09: the same phonemes as kokoro-onnx, and
identical audio.

Speed on this PC's CPU (int8 model): a short phrase in 0.3-0.4 s, a sentence in
0.6-0.8 s, about 3.5 times faster than it plays. The GPU (DirectML) can't run
this model: one of its layers isn't supported there.

If Kokoro's files are missing or it fails to load, it speaks with Piper instead
(`fallback`), so Red is never silent. Files are pinned by SHA-256 and kept in
RED_HOME\\models\\kokoro; `python -m red setup` downloads them.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
from pathlib import Path
from typing import Callable

import numpy as np

from red.audio import PinnedFiles
from red.llm import Asset
from red.tts import Speaker

log = logging.getLogger(__name__)

SAMPLE_RATE = 24_000
MODEL_FILE = "kokoro-v1.0.int8.onnx"          # 88 MB; fp16 and fp32 were no faster on CPU
VOICES_FILE = "voices-v1.0.bin"               # every voice's style vectors, 27 MB
KOKORO_FILES = PinnedFiles(
    "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/",
    (Asset(MODEL_FILE, "6e742170d309016e5891a994e1ce1559c702a2ccd0075e67ef7157974f6406cb"),
     Asset(VOICES_FILE, "bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d")))
DEFAULT_VOICE = "af_heart"
# English voices, for RED_VOICE and the setting page. a = American, b = British; f/m = woman/man.
VOICES = ("af_heart", "af_bella", "af_nicole", "af_sarah", "af_alloy", "af_aoede", "af_jessica",
          "af_kore", "af_nova", "af_river", "af_sky", "am_michael", "am_fenrir", "am_puck",
          "am_adam", "am_echo", "am_eric", "am_liam", "am_onyx", "bf_emma", "bf_alice",
          "bf_isabella", "bf_lily", "bm_george", "bm_daniel", "bm_fable", "bm_lewis")
MAX_TOKENS = 510
PAUSE_SECONDS = 0.12        # a breath after each piece, so sentences don't run into each other
VOCAB: dict[str, int] = json.loads((Path(__file__).with_name("kokoro_vocab.json")).read_text(encoding="utf-8"))


def _language(voice: str) -> str:
    # Piper's bundled espeak-ng has no plain "en-gb" voice (set_voice fails); "en-gb-x-rp" is the
    # British voice kokoro-onnx's "en-gb" maps to. Found 2026-11-13 while testing the bm_* voices.
    return "en-gb-x-rp" if voice.startswith("b") else "en-us"


# espeak-ng keeps one global state, so phonemizing is done one text at a time.
_espeak_lock = threading.Lock()
_espeak_ready = False


def phonemize(text: str, language: str = "en-us") -> str:
    """Text -> Kokoro's phonemes, with piper-tts's bundled espeak-ng.

    Like kokoro-onnx: espeak's IPA with stress marks and the punctuation that ends
    each clause, keeping only symbols in Kokoro's vocabulary. Piper's espeak adds a
    'ʲ' glide that kokoro-onnx's doesn't, so it is dropped.
    """
    global _espeak_ready
    from piper import espeakbridge
    from piper.phonemize_espeak import ESPEAK_DATA_DIR
    with _espeak_lock:
        if not _espeak_ready:
            espeakbridge.initialize(str(ESPEAK_DATA_DIR))
            _espeak_ready = True
        espeakbridge.set_voice(language)
        clauses = espeakbridge.get_phonemes(text)
    out = ""
    for phonemes, terminator, end in clauses:
        phonemes = re.sub(r"\([^)]+\)", "", phonemes).replace("ʲ", "")
        out += phonemes + terminator + (" " if terminator in ",:;" or end else "")
    return "".join(c for c in out if c in VOCAB).strip()


def trim(audio: np.ndarray, top_db: float = 60.0, frame: int = 512, hop: int = 128,
         margin: float = 0.04) -> np.ndarray:
    """Cut the quiet start and end: frames more than top_db under the loudest (as librosa)."""
    if audio.size < frame:
        return audio
    n = 1 + (audio.size - frame) // hop
    frames = np.lib.stride_tricks.sliding_window_view(audio, frame)[::hop][:n]
    rms = np.sqrt(np.mean(frames.astype(np.float64) ** 2, axis=1))
    loud = np.nonzero(rms > rms.max() * 10 ** (-top_db / 20))[0]
    if loud.size == 0:
        return audio
    pad = int(margin * SAMPLE_RATE)
    return audio[max(0, loud[0] * hop - pad): min(audio.size, loud[-1] * hop + frame + pad)]


class KokoroEngine:
    """The model and the voices, loaded once. create(text) -> float32 audio at 24 kHz."""

    def __init__(self, model_path: Path, voices_path: Path, session_factory: Callable | None = None):
        if session_factory is None:
            import onnxruntime as rt

            def session_factory(path):
                return rt.InferenceSession(str(path), providers=["CPUExecutionProvider"])
        self.session = session_factory(model_path)
        names = {i.name for i in self.session.get_inputs()}
        self._tokens_input = "input_ids" if "input_ids" in names else "tokens"
        self.voices = np.load(voices_path)

    def create(self, text: str, voice: str, speed: float = 1.0) -> np.ndarray:
        tokens = [VOCAB[c] for c in phonemize(text, _language(voice))][:MAX_TOKENS]
        if not tokens:
            return np.zeros(0, dtype=np.float32)
        styles = self.voices[voice]
        style = styles[min(len(tokens), len(styles)) - 1]       # one style per phoneme count
        feed = {self._tokens_input: np.array([[0, *tokens, 0]], dtype=np.int64),
                "style": np.asarray(style, dtype=np.float32),
                "speed": np.array([speed], dtype=np.float32)}
        audio = np.asarray(self.session.run(None, feed)[0], dtype=np.float32).ravel()
        return trim(audio)


def _load_kokoro(model_path: Path, voices_path: Path) -> KokoroEngine:
    return KokoroEngine(model_path, voices_path)


class KokoroSpeaker(Speaker):
    """tts.Speaker with Kokoro's voice; speaks with `fallback` (Piper) if Kokoro can't."""

    def __init__(self, model_dir: Path, voice: str | None = None, *, speed: float = 1.0,
                 fallback: Speaker | None = None, engine_loader: Callable = _load_kokoro,
                 player=None):
        super().__init__(model_dir, voice or DEFAULT_VOICE, player=player)
        if self.voice_name not in VOICES:
            log.warning("Unknown Kokoro voice %r; using %s", self.voice_name, DEFAULT_VOICE)
            self.voice_name = DEFAULT_VOICE
        self.speed = speed
        self.fallback = fallback
        if fallback is not None:
            fallback.player = self.player          # one player, so stop() stops either voice
        self._engine_loader = engine_loader
        self.using_fallback = False

    def set_voice(self, voice: str, speed: float | None = None) -> None:
        """Speak with another Kokoro voice from the next sentence on (the companion changed)."""
        if voice not in VOICES:
            log.warning("Unknown Kokoro voice %r; keeping %s", voice, self.voice_name)
            return
        self.voice_name = voice
        if speed is not None:
            self.speed = speed

    @property
    def model_path(self) -> Path:
        return self.voice_dir / MODEL_FILE

    @property
    def voices_path(self) -> Path:
        return self.voice_dir / VOICES_FILE

    def download(self) -> Path:
        """Fetch Kokoro (and the Piper fallback) if missing. Returns Kokoro's model path."""
        KOKORO_FILES.ensure(self.voice_dir, label="Kokoro voice")
        if self.fallback is not None:
            self.fallback.download()
        return self.model_path

    def load(self) -> None:
        with self._load_lock:
            if self._voice is not None or self.using_fallback:
                return
            try:
                if not KOKORO_FILES.present(self.voice_dir):
                    raise FileNotFoundError("Kokoro's files aren't downloaded (python -m red setup)")
                self._voice = self._engine_loader(self.model_path, self.voices_path)
                return
            except Exception as e:  # noqa: BLE001 - Red must still speak
                if self.fallback is None:
                    raise
                log.warning("Kokoro voice unavailable, speaking with Piper instead: %s", e)
                self.using_fallback = True
        self.fallback.load()

    def synthesize(self, text: str) -> tuple[np.ndarray, int]:
        """Text -> (float32 audio, sample rate), with a short breath at the end."""
        self.load()
        if self.using_fallback:
            return self.fallback.synthesize(text)
        audio = self._voice.create(speakable(text), self.voice_name, self.speed)
        if audio.size:
            audio = np.concatenate([audio, np.zeros(int(PAUSE_SECONDS * SAMPLE_RATE), np.float32)])
        return audio, SAMPLE_RATE

    def _speak(self, text: str, cancel: threading.Event) -> None:
        """Speak sentence by sentence: the next is made while the last one plays."""
        from red.speech import sentences
        parts = list(sentences([text])) or [text]
        try:
            audio, rate = self.synthesize(parts[0])
            for i in range(len(parts)):
                if cancel.is_set():
                    return
                if audio.size:
                    self._speaking.set()
                    self.player.play(audio, rate)
                if i + 1 < len(parts):
                    audio, rate = self.synthesize(parts[i + 1])   # while this one plays
                if not cancel.is_set():
                    self.player.wait()
        finally:
            self._speaking.clear()


def companion_voice(settings, companion_id: str | None = None) -> tuple[str, float]:
    """(Kokoro voice, speed) to speak with: the user's own RED_VOICE / RED_VOICE_SPEED if they set
    them, else the active companion's voice (companions/<id>/companion.toml, plus the user's edits).
    Red is a man (am_michael), Remy and Asha women."""
    explicit_voice = (os.environ.get("RED_VOICE") or "").strip()
    explicit_speed = bool((os.environ.get("RED_VOICE_SPEED") or "").strip())
    voice, speed = settings.voice, settings.voice_speed
    try:
        from red import companions
        who = companions.load(companion_id, settings.home) if companion_id else companions.active(settings.home)
        if who.voice.get("engine", "kokoro") == "kokoro" and who.voice_id in VOICES:
            voice = who.voice_id if not explicit_voice else voice
            if not explicit_speed:
                speed = float(who.voice.get("speed", 1.0))
    except Exception:  # noqa: BLE001 - a broken companion file must not silence Red
        log.warning("Couldn't read the companion's voice; using %s", voice, exc_info=True)
    return voice, speed


def make_speaker(settings, *, follow_companion: bool = True) -> Speaker:
    """Red's speaker from its settings: Kokoro with Piper behind it, or Piper alone.

    Kokoro speaks with the active companion's voice, and switches voice when the companion does
    (the `companion` event, red/companions.py), unless the user pinned one with RED_VOICE.
    """
    piper = Speaker(settings.models_dir / "piper", settings.piper_voice)
    if settings.tts != "kokoro":
        return piper
    voice, speed = companion_voice(settings)
    speaker = KokoroSpeaker(settings.models_dir / "kokoro", voice, speed=speed, fallback=piper)
    if follow_companion:
        from red import events

        def switch(id: str = "", **_):
            new_voice, new_speed = companion_voice(settings, id or None)
            speaker.set_voice(new_voice, new_speed)

        events.on("companion", switch)
    return speaker


# --- Text the way it is said --------------------------------------------------

_REPLACE = [
    (re.compile(r"(\d)\s*%"), r"\1 percent"),
    (re.compile(r"\s*°\s*C\b"), " degrees Celsius"),
    (re.compile(r"\s*°\s*F\b"), " degrees Fahrenheit"),
    (re.compile(r"\s*°"), " degrees"),
    (re.compile(r"\s+&\s+"), " and "),
    (re.compile(r"\be\.g\.,?\s*", re.I), "for example, "),
    (re.compile(r"\bi\.e\.,?\s*", re.I), "that is, "),
    (re.compile(r"\betc\.", re.I), "and so on"),
    (re.compile(r"\bvs\.?\s", re.I), "versus "),
    (re.compile(r"\s*\(([^)]*)\)"), r", \1,"),                 # asides read as asides
    (re.compile(r"\b(\d{1,2}):00\s*([ap])\.?m\.?(?!\w)", re.I),
     lambda m: f"{m.group(1)} {m.group(2).upper()}M"),           # 11:00 p.m. -> 11 PM
    (re.compile(r"\b(\d{1,2}):0(\d)\b"), r"\1 oh \2"),          # 11:05 -> 11 oh 5
    (re.compile(r"\b(\d{1,2}):(\d{2})\b"), r"\1 \2"),           # 11:40 -> 11 40
    (re.compile(r"\b([ap])\.m\.(?!\w)", re.I), lambda m: m.group(1).upper() + "M"),
]
_YEAR = re.compile(r"(?<![\d,.$£€])\b(1[1-9]|20)(\d{2})\b(?![\d%]|[.,]\d|\s*(?:percent|degrees|people|"
                   r"dollars|euros|pounds|rupees|km|kilometres|kilometers|metres|meters|miles|mb|gb|kb|tb|"
                   r"users|hours|minutes|seconds|times|words|calories))", re.I)


def _year(m: re.Match) -> str:
    """'2021' as people say a year: 'twenty twenty-one'; leave 2000-2009 to espeak ('two thousand one')."""
    hi, lo = int(m.group(1)), int(m.group(2))
    if hi == 20 and lo < 10:
        return m.group(0)
    if lo == 0:
        return f"{hi} hundred"
    if lo < 10:
        return f"{hi} oh {lo}"
    return f"{hi} {lo}"


def speakable(text: str) -> str:
    """Written forms a voice reads badly, the way people say them: %, °C, &, e.g., years, times."""
    for pattern, repl in _REPLACE:
        text = pattern.sub(repl, text)
    text = _YEAR.sub(_year, text)
    text = re.sub(r",\s*,", ",", text)
    text = re.sub(r",\s*([.!?;:])", r"\1", text)              # "(light rain)." -> "light rain."
    return " ".join(text.split()).strip(" ,")
