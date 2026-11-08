"""Text to speech with Piper.

Voices are pinned to a Hugging Face commit and SHA-256 and stored under
RED_HOME\\models\\piper. A voice that isn't pinned here can still be used by
putting <name>.onnx and <name>.onnx.json in that folder yourself.

Synthesis and playback are passed in, so tests never load a model or play sound.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable, Protocol

import numpy as np

from red.audio import PinnedFiles, hf_url, to_float32
from red.llm import Asset

_PIPER_REV = "e7229f7d33a10e145e109b886d661984201ac3c4"

PIPER_VOICES: dict[str, PinnedFiles] = {
    "en_US-lessac-medium": PinnedFiles(
        hf_url("rhasspy/piper-voices", _PIPER_REV, "en/en_US/lessac/medium"),
        (
            Asset("en_US-lessac-medium.onnx",
                  "5efe09e69902187827af646e1a6e9d269dee769f9877d17b16b1b46eeaaf019f"),
            Asset("en_US-lessac-medium.onnx.json",
                  "efe19c417bed055f2d69908248c6ba650fa135bc868b0e6abb3da181dab690a0"),
        ),
    ),
}
DEFAULT_VOICE = "en_US-lessac-medium"


class Player(Protocol):
    def play(self, audio: np.ndarray, samplerate: int) -> None: ...   # starts playback, returns at once
    def wait(self) -> None: ...                                        # until playback ends or stop()
    def stop(self) -> None: ...


class SoundDevicePlayer:
    """Plays through the default output device."""

    def play(self, audio: np.ndarray, samplerate: int) -> None:
        import sounddevice as sd
        sd.play(audio, samplerate)

    def wait(self) -> None:
        import sounddevice as sd
        sd.wait()

    def stop(self) -> None:
        import sounddevice as sd
        sd.stop()


def _load_piper(model_path: Path):
    from piper import PiperVoice
    return PiperVoice.load(model_path)


# model .onnx path -> an object with Piper's synthesize(text) -> chunks
VoiceLoader = Callable[[Path], object]


class Speaker:
    def __init__(self, voice_dir: Path, voice: str | None = None, *,
                 voice_loader: VoiceLoader = _load_piper, player: Player | None = None):
        self.voice_dir = Path(voice_dir)
        self.voice_name = voice or DEFAULT_VOICE
        self._loader = voice_loader
        self.player = player if player is not None else SoundDevicePlayer()
        self._voice = None
        self._load_lock = threading.Lock()
        self._say_lock = threading.Lock()
        self._cancel = threading.Event()
        self._thread: threading.Thread | None = None
        self._speaking = threading.Event()

    @property
    def model_path(self) -> Path:
        return self.voice_dir / f"{self.voice_name}.onnx"

    @property
    def speaking(self) -> bool:
        return self._speaking.is_set()

    def download(self) -> Path:
        """Fetch the pinned voice if it's missing. Returns the .onnx path."""
        pinned = PIPER_VOICES.get(self.voice_name)
        if pinned is not None:
            pinned.ensure(self.voice_dir, label=f"Piper {self.voice_name}")
        elif not (self.model_path.exists() and Path(f"{self.model_path}.json").exists()):
            raise FileNotFoundError(
                f"Piper voice {self.voice_name!r} isn't pinned in Red. Put "
                f"{self.voice_name}.onnx and {self.voice_name}.onnx.json in {self.voice_dir}, "
                f"or use one of {sorted(PIPER_VOICES)}.")
        return self.model_path

    def load(self) -> None:
        with self._load_lock:
            if self._voice is None:
                self._voice = self._loader(self.download())

    def synthesize(self, text: str) -> tuple[np.ndarray, int]:
        """Text -> (float32 audio, sample rate)."""
        self.load()
        chunks = list(self._voice.synthesize(text))
        if not chunks:
            return np.zeros(0, dtype=np.float32), 22_050
        rate = chunks[0].sample_rate
        audio = np.concatenate([to_float32(c.audio_float_array) for c in chunks])
        return audio, rate

    def _speak(self, text: str, cancel: threading.Event) -> None:
        try:
            audio, rate = self.synthesize(text)
            if cancel.is_set() or audio.size == 0:
                return
            self._speaking.set()
            self.player.play(audio, rate)
            if not cancel.is_set():
                self.player.wait()
        finally:
            self._speaking.clear()

    def say(self, text: str, block: bool = True) -> None:
        """Speak text. Anything still being spoken is stopped first."""
        self.stop()
        text = " ".join(text.split())
        if not text:
            return
        with self._say_lock:
            self._cancel = cancel = threading.Event()
            if block:
                self._speak(text, cancel)
            else:
                self._thread = threading.Thread(target=self._speak, args=(text, cancel),
                                                name="red-tts", daemon=True)
                self._thread.start()

    def stop(self) -> None:
        """Stop speaking at once. Safe to call when nothing is playing."""
        self._cancel.set()
        self.player.stop()
        t = self._thread
        if t is not None and t is not threading.current_thread():
            t.join(timeout=5)
        self._thread = None
