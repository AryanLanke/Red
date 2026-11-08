"""Fakes for the voice tests: no microphone, speakers, keyboard hook or real model."""

from __future__ import annotations

import threading
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from red.audio import SAMPLE_RATE, AudioError

BLOCK = int(0.03 * SAMPLE_RATE)


def tone(seconds: float, amp: float = 0.2, freq: float = 220.0) -> np.ndarray:
    t = np.arange(int(seconds * SAMPLE_RATE)) / SAMPLE_RATE
    return (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def noise(seconds: float, amp: float = 0.002, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return (amp * rng.standard_normal(int(seconds * SAMPLE_RATE))).astype(np.float32)


class FakeMic:
    """Serves pre-made audio in blocks. After the script runs out, serves quiet noise."""

    def __init__(self, *pieces: np.ndarray, block: int = BLOCK, tail_amp: float = 0.002,
                 fail_after: int | None = None):
        self.audio = np.concatenate(pieces) if pieces else np.zeros(0, np.float32)
        self.block = block
        self.tail_amp = tail_amp
        self.pos = 0
        self.reads = 0
        self.opened = 0
        self.is_open = False
        self.fail_after = fail_after
        self._rng = np.random.default_rng(1)

    def __enter__(self):
        self.opened += 1
        self.is_open = True
        return self

    def __exit__(self, *exc):
        self.is_open = False

    def read(self, timeout: float = 2.0) -> np.ndarray:
        assert self.is_open, "read from a closed mic"
        self.reads += 1
        if self.fail_after is not None and self.reads > self.fail_after:
            raise AudioError("fake mic unplugged")
        if self.pos < self.audio.size:
            out = self.audio[self.pos:self.pos + self.block]
            self.pos += out.size
            return out
        return (self.tail_amp * self._rng.standard_normal(self.block)).astype(np.float32)

    @property
    def seconds_read(self) -> float:
        return self.reads * self.block / SAMPLE_RATE


def fake_download(calls: list | None = None):
    """Stands in for red.downloads.download: writes a placeholder file, no network."""

    def download(url: str, dest: Path, sha256: str, label: str | None = None) -> Path:
        if calls is not None:
            calls.append((url, dest, sha256))
        if not dest.exists():
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(b"fake")
        return dest

    return download


class FakeWhisper:
    """Looks like faster_whisper.WhisperModel."""

    def __init__(self, path, device, compute_type, text=" Open downloads. ", fail_on_transcribe=None):
        self.path, self.device, self.compute_type = path, device, compute_type
        self.text = text
        self.fail_on_transcribe = fail_on_transcribe
        self.calls = []

    def transcribe(self, audio, **kwargs):
        self.calls.append((audio, kwargs))

        def segments():
            if self.fail_on_transcribe:
                raise self.fail_on_transcribe
            for part in self.text.split("|"):
                yield SimpleNamespace(text=part)

        return segments(), SimpleNamespace(language="en")


class FakePlayer:
    """Looks like tts.SoundDevicePlayer. wait() blocks until finish() or stop()."""

    def __init__(self, auto_finish: bool = True):
        self.played: list[tuple[np.ndarray, int]] = []
        self.stops = 0
        self.auto_finish = auto_finish
        self._done = threading.Event()
        self.started = threading.Event()

    def play(self, audio, samplerate):
        self._done.clear()
        self.played.append((audio, samplerate))
        self.started.set()

    def wait(self):
        if not self.auto_finish:
            self._done.wait(timeout=5)

    def stop(self):
        self.stops += 1
        self._done.set()

    def finish(self):
        self._done.set()


class FakeVoice:
    """Looks like piper.PiperVoice: one chunk per sentence."""

    def __init__(self, rate: int = 22_050):
        self.rate = rate
        self.texts: list[str] = []

    def synthesize(self, text):
        self.texts.append(text)
        for sentence in [s for s in text.split(".") if s.strip()]:
            yield SimpleNamespace(sample_rate=self.rate,
                                  audio_float_array=np.full(len(sentence) * 10, 0.1, np.float32))


class FakeHotKeys:
    """Looks like pynput.keyboard.GlobalHotKeys. press() simulates the shortcut."""

    instances: list["FakeHotKeys"] = []

    def __init__(self, mapping):
        self.mapping = mapping
        self.started = self.stopped = False
        FakeHotKeys.instances.append(self)

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

    def press(self, combo: str | None = None):
        combo = combo or next(iter(self.mapping))
        self.mapping[combo]()


class FakeDetector:
    """Scores frames from a script: fire_at lists the frame numbers that hit the wake word."""

    def __init__(self, fire_at=()):
        self.fire_at = set(fire_at)
        self.frames = 0
        self.resets = 0
        self.dtypes = set()

    def score(self, frame):
        self.dtypes.add(frame.dtype)
        self.frames += 1
        return 0.9 if self.frames in self.fire_at else 0.01

    def reset(self):
        self.resets += 1
