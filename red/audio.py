"""Microphone recording that stops on silence, plus shared voice helpers.

Everything here works on 16 kHz mono float32 audio in [-1, 1], which is what
Whisper and openWakeWord expect. The microphone is passed in, so tests feed
fake audio and never open a real device.
"""

from __future__ import annotations

import os
import queue
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import numpy as np

from red.downloads import download
from red.llm import Asset

SAMPLE_RATE = 16_000
BLOCK_SECONDS = 0.03            # 30 ms blocks for silence detection

# Silence detection (RMS of float32 audio). The noise floor is measured from
# the first quarter second; speech is anything clearly louder than that.
CALIBRATION_SECONDS = 0.25
MIN_SPEECH_RMS = 0.008          # never treat quieter audio as speech
MAX_NOISE_FLOOR = 0.02          # cap, in case you start talking straight away
SPEECH_FACTOR = 3.0             # speech must be this many times the noise floor
SPEECH_START_SECONDS = 0.09     # loud for this long before speech counts (skips clicks)
PRE_ROLL_SECONDS = 0.3          # keep this much audio from before speech started


class AudioError(RuntimeError):
    pass


# --- Pinned model files (shared by stt, tts and listener) --------------------

@dataclass(frozen=True)
class PinnedFiles:
    """A set of model files at a fixed URL prefix, each with a SHA-256."""

    base_url: str                # files are fetched from base_url + filename
    files: tuple[Asset, ...]

    def ensure(self, dest_dir: Path, label: str | None = None) -> Path:
        """Download any missing file into dest_dir and return dest_dir.

        red.downloads.download only moves a file into place after its checksum
        matches, so a file that already exists has been verified.
        """
        for asset in self.files:
            download(self.base_url + asset.filename, dest_dir / asset.filename,
                     asset.sha256, label=f"{label}: {asset.filename}" if label else None)
        return dest_dir

    def present(self, dest_dir: Path) -> bool:
        return all((dest_dir / a.filename).exists() for a in self.files)


def hf_url(repo: str, revision: str, subdir: str = "") -> str:
    """Base URL for files in a Hugging Face repo, pinned to one commit."""
    sub = subdir.strip("/") + "/" if subdir else ""
    return f"https://huggingface.co/{repo}/resolve/{revision}/{sub}"


# --- Small signal helpers ----------------------------------------------------

def to_float32(audio) -> np.ndarray:
    """Any mono or stereo int16/float array -> 1-D float32 in [-1, 1]."""
    a = np.asarray(audio)
    if a.ndim == 2:
        a = a.mean(axis=1)
    if a.dtype == np.int16:
        return (a.astype(np.float32) / 32768.0).reshape(-1)
    return a.astype(np.float32, copy=False).reshape(-1)


def to_int16(audio: np.ndarray) -> np.ndarray:
    return (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16)


def resample(audio: np.ndarray, from_rate: int, to_rate: int = SAMPLE_RATE) -> np.ndarray:
    """Linear resampling. Good enough for speech going into Whisper."""
    audio = to_float32(audio)
    if from_rate == to_rate or audio.size == 0:
        return audio
    n_out = int(round(audio.size * to_rate / from_rate))
    x_old = np.arange(audio.size, dtype=np.float64) / from_rate
    x_new = np.arange(n_out, dtype=np.float64) / to_rate
    return np.interp(x_new, x_old, audio).astype(np.float32)


def rms(block: np.ndarray) -> float:
    if block.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(np.square(block, dtype=np.float64))))


# --- Microphone --------------------------------------------------------------

class AudioSource(Protocol):
    """What record_command and the wake word listener read from."""

    def __enter__(self) -> "AudioSource": ...
    def __exit__(self, *exc) -> None: ...
    def read(self, timeout: float = 2.0) -> np.ndarray: ...   # 16 kHz mono float32 block


def default_input_device() -> int | str | None:
    """RED_MIC_DEVICE: an input device index or part of its name. Empty means the system default."""
    value = os.environ.get("RED_MIC_DEVICE", "").strip()
    if not value:
        return None
    return int(value) if value.isdigit() else value


class Microphone:
    """The real microphone, through sounddevice. Re-openable context manager.

    Asks the device for 16 kHz mono. If the device refuses that rate, it
    records at the device's own rate and resamples.
    """

    def __init__(self, device: int | str | None = None, block_seconds: float = BLOCK_SECONDS):
        self.device = device if device is not None else default_input_device()
        self.block_seconds = block_seconds
        self._queue: queue.Queue[np.ndarray] = queue.Queue()
        self._stream = None
        self._rate = SAMPLE_RATE

    def _callback(self, indata, frames, time_info, status) -> None:
        self._queue.put(indata[:, 0].copy())

    def __enter__(self) -> "Microphone":
        import sounddevice as sd

        self._queue = queue.Queue()
        last_error: Exception | None = None
        rates = [SAMPLE_RATE]
        try:
            native = int(sd.query_devices(self.device, "input")["default_samplerate"])
            if native != SAMPLE_RATE:
                rates.append(native)
        except Exception as e:  # no input device at all
            raise AudioError(f"No microphone found ({e}). Check Windows sound settings.") from e
        for rate in rates:
            try:
                stream = sd.InputStream(samplerate=rate, channels=1, dtype="float32",
                                        blocksize=int(rate * self.block_seconds),
                                        device=self.device, callback=self._callback)
                stream.start()
            except Exception as e:
                last_error = e
                continue
            self._stream, self._rate = stream, rate
            return self
        raise AudioError(f"Cannot open the microphone ({last_error}).")

    def __exit__(self, *exc) -> None:
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            finally:
                self._stream = None

    def read(self, timeout: float = 2.0) -> np.ndarray:
        try:
            block = self._queue.get(timeout=timeout)
        except queue.Empty:
            raise AudioError("The microphone stopped sending audio.") from None
        return resample(block, self._rate) if self._rate != SAMPLE_RATE else block


# --- Silence detection -------------------------------------------------------

class Endpointer:
    """Finds where speech starts and ends in a stream of audio blocks.

    Pure logic with no device access, so it's easy to test.
    """

    def __init__(self, silence_seconds: float = 0.8, samplerate: int = SAMPLE_RATE,
                 min_rms: float = MIN_SPEECH_RMS):
        self.sr = samplerate
        self.silence_samples = int(silence_seconds * samplerate)
        self.min_rms = min_rms
        self._blocks: list[np.ndarray] = []
        self._calibration: list[float] = []
        self._calibration_samples = 0
        self.noise_floor: float | None = None
        self.total = 0                  # samples seen
        self.start: int | None = None   # sample index where speech began
        self._loud_run = 0              # samples in the current loud run
        self._loud_run_start = 0
        self._quiet_run = 0             # samples of silence since speech

    @property
    def threshold(self) -> float:
        floor = self.noise_floor if self.noise_floor is not None else 0.0
        return max(self.min_rms, floor * SPEECH_FACTOR)

    @property
    def started(self) -> bool:
        return self.start is not None

    def feed(self, block: np.ndarray) -> bool:
        """Add a block. Returns True once speech has started and then gone quiet."""
        block = to_float32(block)
        n = block.size
        self._blocks.append(block)
        level = rms(block)
        pos = self.total
        self.total += n

        if self.noise_floor is None:
            self._calibration.append(level)
            self._calibration_samples += n
            if self._calibration_samples >= CALIBRATION_SECONDS * self.sr:
                self.noise_floor = min(float(np.median(self._calibration)), MAX_NOISE_FLOOR)

        if self.start is None:
            if level > self.threshold:
                if self._loud_run == 0:
                    self._loud_run_start = pos
                self._loud_run += n
                if self._loud_run >= SPEECH_START_SECONDS * self.sr:
                    self.start = self._loud_run_start
            else:
                self._loud_run = 0
            return False

        if level > self.threshold * 0.8:
            self._quiet_run = 0
        else:
            self._quiet_run += n
        return self._quiet_run >= self.silence_samples

    def audio(self) -> np.ndarray:
        """The speech, with a little audio before it. Empty if no speech was heard."""
        if self.start is None or not self._blocks:
            return np.zeros(0, dtype=np.float32)
        allaudio = np.concatenate(self._blocks)
        begin = max(0, self.start - int(PRE_ROLL_SECONDS * self.sr))
        return allaudio[begin:]


def record_command(max_seconds: float = 8.0, silence_seconds: float = 0.8, *,
                   start_timeout: float | None = None,
                   mic: AudioSource | None = None,
                   stop_event: threading.Event | None = None) -> np.ndarray:
    """Record one spoken command from the microphone.

    Recording stops `silence_seconds` after you stop talking, or after
    `max_seconds` in total. If no speech starts within `start_timeout`
    (default: `max_seconds`), it returns an empty array, so silence is never
    sent to Whisper (which tends to invent words for silence).

    Returns 16 kHz mono float32.
    """
    if start_timeout is None:
        start_timeout = max_seconds
    mic = mic if mic is not None else Microphone()
    ep = Endpointer(silence_seconds=silence_seconds)
    max_samples = int(max_seconds * SAMPLE_RATE)
    start_samples = int(start_timeout * SAMPLE_RATE)
    with mic:
        while ep.total < max_samples:
            if stop_event is not None and stop_event.is_set():
                break
            if ep.feed(mic.read()):
                break
            if not ep.started and ep.total >= start_samples:
                break
    return ep.audio()


def chime(frequency: float = 880.0, seconds: float = 0.12, volume: float = 0.2) -> None:
    """A short beep that says "speak now". Blocks until it has played."""
    import sounddevice as sd

    sr = 22_050
    t = np.arange(int(sr * seconds)) / sr
    fade = np.minimum(1.0, np.minimum(t, seconds - t) / 0.01)   # avoid clicks
    tone = (volume * np.sin(2 * np.pi * frequency * t) * fade).astype(np.float32)
    sd.play(tone, sr)
    sd.wait()
