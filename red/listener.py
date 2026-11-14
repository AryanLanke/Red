"""Triggers: a global hotkey and an always-on wake word.

on_trigger("hotkey") or on_trigger("wakeword") runs on the listener's own
worker thread, one trigger at a time. A trigger that arrives while the
previous one is still being handled is ignored, so pressing the hotkey twice
doesn't start two recordings.

While a trigger is being handled, the wake word is paused automatically (its
microphone stream is closed), so Red never hears itself. Call pause() and
resume() around anything else that records or speaks. Pauses nest.

The one exception is while Red is talking: the voice loop calls
allow_interrupt(True), the wake word listens again, and "Hey Red" or the
hotkey calls on_interrupt() (stop talking) instead of being ignored.

The default wake phrase is "Hey Red" (red/wakeword.py: a voice activity
gate plus a small pinned Whisper model). Other openWakeWord ONNX phrases and
custom .onnx models also work (tflite has no Windows wheels); they're pinned
by SHA-256 under RED_HOME\\models\\wakeword. The keyboard hook, microphone and
detector are passed in, so tests use fakes.
"""

from __future__ import annotations

import json
import logging
import queue
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Protocol

import numpy as np

from red import events
from red.audio import AudioError, Microphone, PinnedFiles, to_int16
from red.config import red_home
from red.llm import Asset

log = logging.getLogger(__name__)

_OWW = "https://github.com/dscripka/openWakeWord/releases/download/v0.5.1/"

# Shared feature models every openWakeWord phrase needs.
FEATURE_MODELS = PinnedFiles(_OWW, (
    Asset("melspectrogram.onnx", "ba2b0e0f8b7b875369a2c89cb13360ff53bac436f2895cced9f479fa65eb176f"),
    Asset("embedding_model.onnx", "70d164290c1d095d1d4ee149bc5e00543250a7316b59f31d056cff7bd3075c1f"),
))

# Other pre-trained openWakeWord phrases, kept as options. A custom model can be
# passed as a path to its .onnx file.
WAKEWORDS: dict[str, Asset] = {
    "hey_mycroft": Asset("hey_mycroft_v0.1.onnx", "c2a311e8fa1338de89c31b3b46dc4dffd4af2f9a8d6ddead48893c2d301b1f18"),
    "hey_rhasspy": Asset("hey_rhasspy_v0.1.onnx", "5a9b3ed3be2910e35780e097905aa9f35a9c10038df47914cf2b3ec4d670f6ea"),
    "alexa": Asset("alexa_v0.1.onnx", "6ff566a01d12670e8d9e3c59da32651db1575d17272a601b7f8a39283dfbae3e"),
}
HEY_RED = "hey_red"            # Red's own wake phrase; see red/wakeword.py
DEFAULT_WAKEWORD = HEY_RED
DEFAULT_THRESHOLD = 0.5
DEFAULT_HOTKEY = "<ctrl>+<alt>+r"
DEFAULT_MIC_HOTKEY = "<ctrl>+<alt>+m"      # microphone off / on
WAKE_BLOCK_SECONDS = 0.08      # openWakeWord works on 80 ms frames (1280 samples)

_MODIFIERS = {"ctrl", "control", "alt", "shift", "cmd", "win", "super", "alt_gr"}
_ALIASES = {"control": "ctrl", "win": "cmd", "super": "cmd", "windows": "cmd", "escape": "esc",
            "return": "enter", "del": "delete"}


def normalize_hotkey(text: str) -> str:
    """'Ctrl+Alt+R' or '<ctrl>+<alt>+r' -> pynput's '<ctrl>+<alt>+r'."""
    parts = [p.strip().strip("<>").lower() for p in text.split("+")]
    if not parts or any(not p for p in parts):
        raise ValueError(f"Invalid hotkey {text!r}; use something like Ctrl+Alt+R")
    out = []
    for p in parts:
        p = _ALIASES.get(p, p)
        out.append(p if len(p) == 1 else f"<{p}>")
    if len(out) < 2 or not all(o.strip("<>") in _MODIFIERS for o in out[:-1]):
        raise ValueError(f"Invalid hotkey {text!r}; use one or more modifiers and a key, like Ctrl+Alt+R")
    return "+".join(out)


def resolve_wakeword(wakeword: str) -> str:
    """'Hey Red' -> 'hey_red'. A path to an .onnx file is returned as is."""
    if wakeword.lower().endswith(".onnx"):
        return wakeword
    key = "_".join(wakeword.lower().replace("-", " ").replace(",", " ").split())
    if key != HEY_RED and key not in WAKEWORDS:
        raise ValueError(f"Unknown wake word {wakeword!r}; choose from "
                         f"{[HEY_RED] + sorted(WAKEWORDS)} or give the path to a custom .onnx model")
    return key


def download_wakeword(model_dir: Path, wakeword: str) -> Path:
    """Fetch what the wake word needs. Returns the phrase model's path (a folder for hey_red)."""
    key = resolve_wakeword(wakeword)
    if key == HEY_RED:
        from red.stt import WHISPER_MODELS
        from red.wakeword import WAKE_WHISPER_MODEL
        folder = Path(model_dir).parent / "whisper" / WAKE_WHISPER_MODEL
        return WHISPER_MODELS[WAKE_WHISPER_MODEL].ensure(folder, label=f"Whisper {WAKE_WHISPER_MODEL}")
    FEATURE_MODELS.ensure(model_dir, label="openWakeWord")
    if key.lower().endswith(".onnx"):
        path = Path(key)
        if not path.exists():
            raise FileNotFoundError(f"Wake word model not found: {path}")
        return path
    asset = WAKEWORDS[key]
    PinnedFiles(_OWW, (asset,)).ensure(model_dir, label="openWakeWord")
    return model_dir / asset.filename


class Detector(Protocol):
    def score(self, frame: np.ndarray) -> float: ...   # int16 16 kHz frame -> 0..1
    def reset(self) -> None: ...


class WakeWordDetector:
    """openWakeWord with the ONNX runtime."""

    def __init__(self, model_dir: Path, wakeword: str):
        from openwakeword.model import Model

        path = download_wakeword(model_dir, wakeword)
        self._model = Model(
            wakeword_models=[str(path)],
            inference_framework="onnx",
            melspec_model_path=str(model_dir / "melspectrogram.onnx"),
            embedding_model_path=str(model_dir / "embedding_model.onnx"),
        )

    def score(self, frame: np.ndarray) -> float:
        scores = self._model.predict(frame)
        return float(max(scores.values())) if scores else 0.0

    def reset(self) -> None:
        self._model.reset()


def make_detector(model_dir: Path, wakeword: str) -> Detector:
    """The right detector for a wake word: "Hey Red" or an openWakeWord model."""
    if resolve_wakeword(wakeword) == HEY_RED:
        from red.wakeword import HeyRedDetector
        download_wakeword(model_dir, wakeword)
        return HeyRedDetector.create(model_dir)
    return WakeWordDetector(model_dir, wakeword)


def read_mic_state(path: Path | None) -> bool:
    """Was the microphone left off? (the cache folder's mic.json: {"muted": true})."""
    if path is None:
        return False
    try:
        return bool(json.loads(Path(path).read_text(encoding="utf-8")).get("muted"))
    except (OSError, ValueError, AttributeError):
        return False


def write_mic_state(path: Path, muted: bool) -> None:
    try:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps({"muted": bool(muted)}), encoding="utf-8")
    except OSError:
        log.warning("Couldn't save the microphone state to %s", path, exc_info=True)


class _HotKeys(Protocol):
    def start(self) -> None: ...
    def stop(self) -> None: ...


def _pynput_hotkeys(mapping: dict[str, Callable[[], None]]) -> _HotKeys:
    from pynput import keyboard
    return keyboard.GlobalHotKeys(mapping)


class Listener:
    def __init__(self, on_trigger: Callable[[str], None], hotkey: str | None = DEFAULT_HOTKEY,
                 wakeword: str | None = None, *,
                 model_dir: Path | None = None,
                 threshold: float = DEFAULT_THRESHOLD,
                 mute_hotkey: str | None = None,
                 mic_state: Path | None = None,
                 mute_sound: Callable[[bool], None] | None = None,
                 hotkey_factory: Callable[[dict], _HotKeys] = _pynput_hotkeys,
                 mic_factory: Callable[[], object] = lambda: Microphone(block_seconds=WAKE_BLOCK_SECONDS),
                 detector_factory: Callable[[Path, str], Detector] = make_detector):
        self.on_trigger = on_trigger
        self.hotkey = normalize_hotkey(hotkey) if hotkey else None
        self.wakeword = resolve_wakeword(wakeword) if wakeword else None
        self.model_dir = Path(model_dir) if model_dir else red_home() / "models" / "wakeword"
        self.threshold = threshold
        self.mute_hotkey = normalize_hotkey(mute_hotkey) if mute_hotkey else None
        self._mic_state = Path(mic_state) if mic_state else None    # the cache folder's mic.json
        self._mute_sound = mute_sound
        self._muted = read_mic_state(self._mic_state)
        self._hotkey_factory = hotkey_factory
        self._mic_factory = mic_factory
        self._detector_factory = detector_factory

        self._cond = threading.Condition()
        self._pauses = 0
        self._running = False
        self._stopping = False
        self._mic_closed = threading.Event()
        self._mic_closed.set()
        self._busy = threading.Event()
        self._triggers: queue.Queue[str | None] = queue.Queue()
        self._hotkeys: _HotKeys | None = None
        self._detector: Detector | None = None
        self._audio_thread: threading.Thread | None = None
        self._worker: threading.Thread | None = None
        self.last_error: Exception | None = None
        # Called (from the wake word or hotkey thread) for "Hey Red" while Red talks.
        self.on_interrupt: Callable[[], None] | None = None
        self._interrupt_open = False
        # Speech heard with the wake word ("Hey Red, open..."), for the trigger handler to take.
        self.wake_audio = None

    # --- public API ---------------------------------------------------------

    @property
    def paused(self) -> bool:
        return self._pauses > 0

    @property
    def busy(self) -> bool:
        return self._busy.is_set()

    def start(self) -> None:
        """Start the hotkey and wake word. Model loading errors are raised here."""
        if self._running:
            return
        if self.wakeword:
            self._detector = self._detector_factory(self.model_dir, self.wakeword)
        self._stopping = False
        self._running = True
        self._worker = threading.Thread(target=self._work, name="red-trigger", daemon=True)
        self._worker.start()
        if self._detector is not None:
            self._audio_thread = threading.Thread(target=self._listen, name="red-wakeword", daemon=True)
            self._audio_thread.start()
        mapping: dict[str, Callable[[], None]] = {}
        if self.hotkey:
            mapping[self.hotkey] = lambda: self._fire("hotkey")
        if self.mute_hotkey:
            # On its own thread: the pynput thread must not wait for the sound.
            mapping[self.mute_hotkey] = lambda: threading.Thread(
                target=self.mute, name="red-mute", daemon=True).start()
        if mapping:
            self._hotkeys = self._hotkey_factory(mapping)
            self._hotkeys.start()

    def stop(self) -> None:
        with self._cond:
            if not self._running:
                return
            self._running = False
            self._stopping = True
            self._cond.notify_all()
        if self._hotkeys is not None:
            self._hotkeys.stop()
            self._hotkeys = None
        self._triggers.put(None)
        me = threading.current_thread()
        for t in (self._audio_thread, self._worker):
            if t is not None and t is not me:
                t.join(timeout=5)
        self._audio_thread = self._worker = None

    @property
    def muted(self) -> bool:
        """Microphone off: Red hears nothing, not even "Hey Red" (the hotkey does nothing either)."""
        return self._muted

    def mute(self, on: bool | None = None) -> bool:
        """Turn the microphone off (True), on (False), or the other way round (None).

        Remembered in mic.json in the cache folder, so Red stays deaf after a restart. Says so with a
        soft chime, not words. Returns once the wake word's microphone is closed. Returns the new state.
        """
        with self._cond:
            on = (not self._muted) if on is None else bool(on)
            changed = on != self._muted
            self._muted = on
            self._cond.notify_all()
        if self._mic_state is not None:
            write_mic_state(self._mic_state, on)
        if on and threading.current_thread() is not self._audio_thread:
            self._mic_closed.wait(timeout=3)
        if changed:
            log.info("Microphone %s", "off" if on else "on")
            events.emit("mic", muted=on)
            if self._mute_sound is not None:
                try:
                    self._mute_sound(on)
                except Exception:  # noqa: BLE001 - a sound that fails must not undo the mute
                    log.warning("Couldn't play the microphone sound", exc_info=True)
        return on

    def pause(self) -> None:
        """Stop listening for the wake word until resume(). Returns once the mic is closed."""
        with self._cond:
            self._pauses += 1
            self._cond.notify_all()
        if threading.current_thread() is not self._audio_thread:
            self._mic_closed.wait(timeout=3)

    def resume(self) -> None:
        with self._cond:
            self._pauses = max(0, self._pauses - 1)
            self._cond.notify_all()

    @property
    def wake_personal(self) -> frozenset:
        """How Whisper hears this user's "Hey Red" (voice-setup), to strip it from a command."""
        return frozenset(getattr(self._detector, "personal", ()) or ())

    def take_wake_audio(self):
        """The speech heard with the last wake word, once (None if it was "Hey Red" alone)."""
        audio, self.wake_audio = self.wake_audio, None
        return audio

    def allow_interrupt(self, on: bool) -> None:
        """While Red talks: listen for "Hey Red" again, so you can cut in."""
        with self._cond:
            if on == self._interrupt_open:
                return
            self._interrupt_open = on
        if on:
            self.resume()
        else:
            self.pause()

    @contextmanager
    def paused_while(self):
        self.pause()
        try:
            yield
        finally:
            self.resume()

    # --- internals ----------------------------------------------------------

    def _fire(self, source: str) -> None:
        """Called from the hotkey or wake word thread. Must return quickly."""
        if not self._running or self._muted:
            return
        if self._busy.is_set():
            # Busy: ignored, unless Red is talking and you may cut in.
            if self._interrupt_open and self.on_interrupt is not None:
                try:
                    self.on_interrupt()
                except Exception:  # noqa: BLE001
                    log.exception("Interrupt handler failed")
            return
        self._busy.set()
        if source != "wakeword":
            self.wake_audio = None
        self._triggers.put(source)

    def _work(self) -> None:
        while True:
            source = self._triggers.get()
            if source is None:
                return
            self.pause()
            try:
                self.on_trigger(source)
            except Exception:
                log.exception("Trigger handler failed")
            finally:
                if self._interrupt_open:      # the handler forgot to close it
                    self.allow_interrupt(False)
                self.resume()
                self._busy.clear()

    def _should_listen(self) -> bool:
        return self._running and self._pauses == 0 and not self._muted

    def _listen(self) -> None:
        detector = self._detector
        failures = 0
        while True:
            with self._cond:
                while not self._stopping and not self._should_listen():
                    self._cond.wait()
                if self._stopping:
                    return
                self._mic_closed.clear()
            wait = 0.0
            try:
                detector.reset()
                with self._mic_factory() as mic:
                    while self._should_listen():
                        frame = mic.read()
                        if detector.score(to_int16(frame)) >= self.threshold:
                            if not self._busy.is_set():
                                # "Hey Red, open YouTube" in one breath: the command's start.
                                self.wake_audio = getattr(detector, "command_audio", None)
                            self._fire("wakeword")
                failures = 0
                self.last_error = None
            except AudioError as e:
                failures += 1
                self.last_error = e
                wait = min(0.25 * (2 ** (failures - 1)), 5.0)
                log.warning("Wake word microphone problem: %s. Retrying in %.1f s.", e, wait)
            except Exception as e:  # noqa: BLE001 - a crash here would deafen Red for good
                failures += 1
                self.last_error = e
                wait = min(0.25 * (2 ** (failures - 1)), 5.0)
                log.exception("Wake word crashed; retrying in %.1f s.", wait)
            finally:
                self._mic_closed.set()
            if wait:
                with self._cond:
                    self._cond.wait(timeout=wait)
