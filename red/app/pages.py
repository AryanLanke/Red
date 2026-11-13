"""The pages of the Red app: hardware, models, audio, voice, general and memory."""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QPlainTextEdit, QPushButton, QSlider,
                               QVBoxLayout, QWidget)

from red import audio as audio_mod
from red.chat import MAX_PERSONALITY, read_personality
from red.config import Settings
from red.tts import PIPER_VOICES
from red.tts_kokoro import DEFAULT_VOICE, VOICES

from . import status

# A microphone's RMS is small even when you talk; this makes the bar move.
LEVEL_GAIN = 8.0
STATE_COLORS = {"ready": "#2e7d32", "missing": "#b26a00", "unknown": "#6b6b6b", "off": "#6b6b6b"}
VOICE_HINTS = {"af": "American woman", "am": "American man",
               "bf": "British woman", "bm": "British man"}


def _title(text: str) -> QLabel:
    label = QLabel(text)
    label.setStyleSheet("font-size: 16px; font-weight: 600;")
    return label


def _hint(text: str) -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    label.setStyleSheet("color: #6b6b6b;")
    return label


def _clear(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.deleteLater()
        elif item.layout() is not None:
            _clear(item.layout())


def pretty_hotkey(hotkey: str | None) -> str:
    """"<ctrl>+<alt>+r" -> "Ctrl+Alt+R"; None or off -> "off"."""
    if not hotkey or hotkey.strip().lower() in {"off", "none", "0", "no", "false", "disabled"}:
        return "off"
    return "+".join(part.strip("<>").capitalize() if len(part) > 1 else part.upper()
                    for part in hotkey.split("+"))


def voice_label(name: str) -> str:
    hint = VOICE_HINTS.get(name[:2])
    return f"{name} ({hint})" if hint else name


# --- audio ---------------------------------------------------------------------------

def input_devices() -> list[tuple[int, str]]:
    """The microphones Windows offers, as (device index, name)."""
    import sounddevice as sd
    return [(i, str(device.get("name", f"Input {i}")))
            for i, device in enumerate(sd.query_devices())
            if device.get("max_input_channels", 0) > 0]


def open_input_stream(callback, device, samplerate: int, block_seconds: float):
    import sounddevice as sd
    stream = sd.InputStream(samplerate=samplerate, channels=1, dtype="float32",
                            blocksize=int(samplerate * block_seconds), device=device,
                            callback=callback)
    stream.start()
    return stream


class MicLevelMonitor:
    """The microphone, open just long enough for the level meter test."""

    def __init__(self, on_level, device=None, *, samplerate: int = 16_000,
                 block_seconds: float = 0.05, stream_factory=open_input_stream):
        self._on_level = on_level
        self.device = device
        self.samplerate = samplerate
        self.block_seconds = block_seconds
        self._stream_factory = stream_factory
        self._stream = None

    def start(self) -> None:
        self._stream = self._stream_factory(self._callback, self.device,
                                            self.samplerate, self.block_seconds)

    def stop(self) -> None:
        stream, self._stream = self._stream, None
        if stream is not None:
            stream.stop()
            stream.close()

    def _callback(self, indata, frames, time_info, status) -> None:
        try:
            self._on_level(min(1.0, audio_mod.rms(indata[:, 0]) * LEVEL_GAIN))
        except Exception:  # noqa: BLE001 - a meter must never break the stream
            pass


class LevelMeter(QWidget):
    """A simple bar that follows the microphone's loudness (0 to 1)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.level = 0.0
        self.setMinimumHeight(20)
        self.setMinimumWidth(220)

    def set_level(self, level: float) -> None:
        self.level = max(0.0, min(1.0, float(level)))
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt's name
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#e6e6e6"))
            painter.drawRoundedRect(QRectF(self.rect()), 10, 10)
            width = self.width() * self.level
            if width > 0:
                painter.setBrush(QColor("#d63c3f"))
                painter.drawRoundedRect(QRectF(0, 0, width, self.height()), 10, 10)
        finally:
            painter.end()


# --- pages ---------------------------------------------------------------------------

class HardwareCheckPage(QWidget):
    """What this PC has, and the model Red would pick for it."""

    NAMES = ("CPU", "GPU", "VRAM", "RAM", "Red's pick")

    def __init__(self, *, hardware=None, parent=None):
        super().__init__(parent)
        self._rows = hardware or (lambda: status.hardware_rows())
        layout = QVBoxLayout(self)
        layout.addWidget(_title("Hardware Check"))
        layout.addWidget(_hint("Red only looks here. Nothing is installed or changed."))
        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(10)
        self.values: dict[str, QLabel] = {}
        for row, name in enumerate(self.NAMES):
            grid.addWidget(QLabel(name), row, 0, Qt.AlignmentFlag.AlignTop)
            value = QLabel("...")
            value.setWordWrap(True)
            grid.addWidget(value, row, 1)
            self.values[name] = value
        layout.addLayout(grid)
        self.refresh_button = QPushButton("Check again")
        self.refresh_button.clicked.connect(self.refresh)
        layout.addWidget(self.refresh_button, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addStretch(1)
        self.refresh()

    def refresh(self) -> None:
        try:
            rows = dict(self._rows())
        except Exception as e:  # noqa: BLE001 - show it instead of closing the app
            for value in self.values.values():
                value.setText(f"Couldn't read it: {e}")
            return
        for name, value in self.values.items():
            value.setText(rows.get(name, "—"))


class ModelStatusPage(QWidget):
    """Which models are on disk, and where to get the ones that aren't."""

    def __init__(self, settings: Settings, *, model_rows=None, parent=None):
        super().__init__(parent)
        self.settings = settings
        self._rows = model_rows or status.model_rows
        layout = QVBoxLayout(self)
        layout.addWidget(_title("Model Status"))
        layout.addWidget(_hint("Every model runs on this PC. Missing ones are one setup away."))
        self.list_layout = QVBoxLayout()
        self.list_layout.setSpacing(8)
        layout.addLayout(self.list_layout)
        self.refresh_button = QPushButton("Check again")
        self.refresh_button.clicked.connect(self.refresh)
        layout.addWidget(self.refresh_button, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addStretch(1)
        self.rows: list[tuple[QLabel, QLabel, QLabel]] = []
        self.refresh()

    def refresh(self) -> None:
        _clear(self.list_layout)
        self.rows = []
        try:
            rows = self._rows(self.settings)
        except Exception as e:  # noqa: BLE001 - show it instead of closing the app
            label = QLabel(f"Couldn't check the models: {e}")
            label.setWordWrap(True)
            self.list_layout.addWidget(label)
            return
        for row in rows:
            frame = QFrame()
            frame.setFrameShape(QFrame.Shape.StyledPanel)
            line = QHBoxLayout(frame)
            text = QVBoxLayout()
            name = QLabel(row.name)
            name.setStyleSheet("font-weight: 600;")
            detail = QLabel(row.detail)
            detail.setWordWrap(True)
            detail.setStyleSheet("color: #6b6b6b;")
            text.addWidget(name)
            text.addWidget(detail)
            line.addLayout(text, 1)
            state = QLabel(status_label(row.state))
            state.setStyleSheet(f"color: {STATE_COLORS.get(row.state, '#6b6b6b')}; font-weight: 600;")
            line.addWidget(state, 0, Qt.AlignmentFlag.AlignTop)
            self.list_layout.addWidget(frame)
            self.rows.append((name, state, detail))


def status_label(state: str) -> str:
    return {"ready": "Ready", "missing": "Missing", "unknown": "Not checked",
            "off": "Off"}.get(state, state)


class AudioSetupPage(QWidget):
    """Pick the microphone, and watch the meter while you talk."""

    level = Signal(float)

    def __init__(self, settings: Settings, *, devices=None, monitor_factory=None, parent=None):
        super().__init__(parent)
        self._settings = settings
        self._devices = devices or input_devices
        self._monitor_factory = monitor_factory or MicLevelMonitor
        self.monitor = None

        layout = QVBoxLayout(self)
        layout.addWidget(_title("Audio Setup"))
        layout.addWidget(_hint("Talk at your mic: if the bar wakes up, Red can hear you."))

        row = QHBoxLayout()
        row.addWidget(QLabel("Microphone"))
        self.device_combo = QComboBox()
        self.device_combo.setMinimumWidth(320)
        row.addWidget(self.device_combo, 1)
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.clicked.connect(self.refresh_devices)
        row.addWidget(self.refresh_button)
        layout.addLayout(row)

        test_row = QHBoxLayout()
        self.meter = LevelMeter()
        test_row.addWidget(self.meter, 1)
        self.audio_test = QPushButton("Test microphone")
        self.audio_test.setObjectName("audio_test")
        self.audio_test.clicked.connect(self.toggle_test)
        test_row.addWidget(self.audio_test)
        layout.addLayout(test_row)

        self.level_label = QLabel("Level: 0%")
        layout.addWidget(self.level_label)
        self.error = QLabel("")
        self.error.setWordWrap(True)
        self.error.setStyleSheet("color: #b3261e;")
        layout.addWidget(self.error)
        layout.addStretch(1)

        self.level.connect(self._show_level)
        self.refresh_devices()

    def refresh_devices(self) -> None:
        wanted = str(self.device_combo.currentData() or self._settings.mic_device or "")
        self.device_combo.clear()
        self.device_combo.addItem("System default", "")
        try:
            devices = self._devices()
        except Exception as e:  # noqa: BLE001 - no sound system at all
            self.error.setText(f"Couldn't list microphones: {e}")
            devices = []
        for index, name in devices:
            self.device_combo.addItem(str(name), str(index))
        index = self.device_combo.findData(wanted) if wanted else 0
        if index < 0:
            self.device_combo.addItem(f"{wanted} (from .env)", wanted)
            index = self.device_combo.count() - 1
        self.device_combo.setCurrentIndex(index)

    def toggle_test(self) -> None:
        if self.monitor is None:
            self.start_test()
        else:
            self.stop_test()

    def start_test(self) -> None:
        device = self.device_combo.currentData() or None
        if isinstance(device, str) and device.isdigit():
            device = int(device)
        try:
            monitor = self._monitor_factory(self._on_level, device)
            monitor.start()
        except Exception as e:  # noqa: BLE001 - no mic, or another app is using it
            self.error.setText(f"Couldn't open the microphone: {e}")
            return
        self.error.setText("")
        self.monitor = monitor
        self.audio_test.setText("Stop")

    def stop_test(self) -> None:
        monitor, self.monitor = self.monitor, None
        if monitor is not None:
            try:
                monitor.stop()
            except Exception as e:  # noqa: BLE001 - it's only a test meter
                self.error.setText(f"Couldn't close the microphone: {e}")
        self.audio_test.setText("Test microphone")
        self.level.emit(0.0)

    def _on_level(self, value: float) -> None:
        # Runs on the audio thread; a signal carries it to the UI thread.
        self.level.emit(float(value))

    def _show_level(self, value: float) -> None:
        self.meter.set_level(value)
        self.level_label.setText(f"Level: {round(self.meter.level * 100)}%")

    def values(self) -> dict[str, str]:
        return {"RED_MIC_DEVICE": str(self.device_combo.currentData() or "")}


class VoiceSettingsPage(QWidget):
    """Kokoro by default; Piper stays available as the lighter fallback."""

    def __init__(self, settings: Settings, parent=None):
        super().__init__(parent)
        self._filling = False
        self._engine = "piper" if settings.tts == "piper" else "kokoro"
        self._picks = {"kokoro": settings.voice or DEFAULT_VOICE,
                       "piper": settings.piper_voice}

        layout = QVBoxLayout(self)
        layout.addWidget(_title("Voice Settings"))
        layout.addWidget(_hint("Kokoro is Red's default voice. Piper is the lightweight fallback."))
        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(12)

        grid.addWidget(QLabel("Voice engine"), 0, 0)
        self.engine = QComboBox()
        self.engine.addItem("Kokoro (natural, default)", "kokoro")
        self.engine.addItem("Piper (lighter fallback)", "piper")
        self.engine.setCurrentIndex(1 if self._engine == "piper" else 0)
        grid.addWidget(self.engine, 0, 1)

        grid.addWidget(QLabel("Voice"), 1, 0)
        self.voice = QComboBox()
        self.voice.setMinimumWidth(280)
        grid.addWidget(self.voice, 1, 1)

        grid.addWidget(QLabel("Speed"), 2, 0)
        speed_row = QHBoxLayout()
        self.speed = QSlider(Qt.Orientation.Horizontal)
        self.speed.setRange(70, 150)
        self.speed.setSingleStep(5)
        self.speed.setPageStep(10)
        self.speed.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.speed.setTickInterval(10)
        self.speed.setValue(int(round(settings.voice_speed * 100)))
        speed_row.addWidget(self.speed, 1)
        self.speed_label = QLabel(f"{self.speed.value() / 100:.2f}×")
        speed_row.addWidget(self.speed_label)
        grid.addLayout(speed_row, 2, 1)
        grid.setColumnStretch(1, 1)
        layout.addLayout(grid)
        layout.addStretch(1)

        self.engine.currentIndexChanged.connect(lambda *_: self._engine_changed())
        self.voice.currentIndexChanged.connect(lambda *_: self._remember())
        self.speed.valueChanged.connect(self._show_speed)
        self._fill_voices(self._picks[self._engine])

    def _choices(self) -> list[tuple[str, str]]:
        if self.engine.currentData() == "piper":
            return [(name, name) for name in sorted(PIPER_VOICES)]
        return [(name, voice_label(name)) for name in VOICES]

    def _fill_voices(self, preferred: str = "") -> None:
        self._filling = True
        try:
            self.voice.clear()
            for value, label in self._choices():
                self.voice.addItem(label, value)
            index = self.voice.findData(preferred) if preferred else -1
            self.voice.setCurrentIndex(index if index >= 0 else 0)
        finally:
            self._filling = False

    def _engine_changed(self) -> None:
        chosen = self.engine.currentData()
        if chosen == self._engine:
            return
        if self._engine and self.voice.currentData():
            self._picks[self._engine] = self.voice.currentData()   # the old engine's pick
        self._engine = chosen
        self._fill_voices(self._picks.get(chosen, ""))

    def _remember(self) -> None:
        if self._filling:
            return
        voice = self.voice.currentData()
        if self._engine and voice:
            self._picks[self._engine] = voice

    def _show_speed(self, value: int) -> None:
        self.speed_label.setText(f"{value / 100:.2f}×")

    def values(self) -> dict[str, str]:
        return {"RED_TTS": self.engine.currentData(),
                "RED_VOICE": self._picks["kokoro"],
                "RED_PIPER_VOICE": self._picks["piper"],
                "RED_VOICE_SPEED": f"{self.speed.value() / 100:.2f}"}


class GeneralSettingsPage(QWidget):
    """The hotkey and how Red shows what it's doing."""

    def __init__(self, settings: Settings, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.addWidget(_title("General Settings"))
        layout.addWidget(_hint("Changes are picked up the next time Red starts."))
        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(12)

        grid.addWidget(QLabel("Hotkey"), 0, 0)
        self.hotkey = QLineEdit(pretty_hotkey(settings.hotkey))
        self.hotkey.setMinimumWidth(240)
        grid.addWidget(self.hotkey, 0, 1)
        grid.addWidget(_hint("For example Ctrl+Alt+R. Type off to wake Red by voice only."), 1, 1)

        grid.addWidget(QLabel("Overlay"), 2, 0)
        self.overlay = QComboBox()
        self.overlay.addItem("Glow around the screen edges", "glow")
        self.overlay.addItem("A small corner card", "card")
        self.overlay.addItem("Windows notifications", "notify")
        self.overlay.addItem("Off", "off")
        index = self.overlay.findData(settings.overlay)
        self.overlay.setCurrentIndex(index if index >= 0 else 0)
        grid.addWidget(self.overlay, 2, 1)

        grid.addWidget(QLabel("Chattiness"), 3, 0)
        self.chattiness = QComboBox()
        self.chattiness.addItem("Quiet: only answers", "quiet")
        self.chattiness.addItem("Friendly: says hello (default)", "friendly")
        self.chattiness.addItem("Chatty: hellos and the odd one-liner", "chatty")
        index = self.chattiness.findData(getattr(settings, "chattiness", "friendly"))
        self.chattiness.setCurrentIndex(index if index >= 0 else 1)
        grid.addWidget(self.chattiness, 3, 1)
        grid.addWidget(_hint("Never meetings, mail or to-dos unless you ask, and never over a "
                             "full-screen game or app."), 4, 1)

        grid.addWidget(QLabel("Personality"), 5, 0, Qt.AlignmentFlag.AlignTop)
        self.personality = QPlainTextEdit(read_personality(settings.home))
        self.personality.setPlaceholderText(
            "Optional. Tune how Red talks, in your own words: \"Fewer jokes\", "
            "\"Roast my code\", \"Talk like a calm coach\".")
        self.personality.setMaximumHeight(110)
        grid.addWidget(self.personality, 5, 1)
        grid.addWidget(_hint(f"Added to Red's own character. Up to {MAX_PERSONALITY} characters."), 6, 1)
        grid.setColumnStretch(1, 1)
        layout.addLayout(grid)
        layout.addStretch(1)

    def personality_text(self) -> str:
        return self.personality.toPlainText().strip()[:MAX_PERSONALITY]

    def values(self) -> dict[str, str]:
        return {"RED_HOTKEY": self.hotkey.text().strip() or "off",
                "RED_OVERLAY": self.overlay.currentData(),
                "RED_CHATTINESS": self.chattiness.currentData()}


class MemoryPage(QWidget):
    """Everything Red remembers about you: see it, edit it, delete it (plan.md A2)."""

    def __init__(self, settings: Settings, *, memory=None, parent=None):
        super().__init__(parent)
        from red.memory import Memory
        self.memory = memory or Memory(settings.home)
        layout = QVBoxLayout(self)
        layout.addWidget(_title("Memory"))
        layout.addWidget(_hint("What Red knows about you. It stays on this PC, in "
                               f"{self.memory.dir}. Double-click a fact to edit it."))

        layout.addWidget(QLabel("About you"))
        self.profile = QPlainTextEdit()
        self.profile.setMaximumHeight(130)
        layout.addWidget(self.profile)

        layout.addWidget(QLabel("Things Red remembers"))
        self.facts = QListWidget()
        self.facts.setWordWrap(True)
        self.facts.setSpacing(3)
        layout.addWidget(self.facts, 1)

        row = QHBoxLayout()
        self.new_fact = QLineEdit()
        self.new_fact.setPlaceholderText("Add something, in your words: \"My sister is Priya\"")
        row.addWidget(self.new_fact, 1)
        self.add_button = QPushButton("Add")
        self.add_button.clicked.connect(self.add_fact)
        row.addWidget(self.add_button)
        self.delete_button = QPushButton("Delete selected")
        self.delete_button.clicked.connect(self.delete_selected)
        row.addWidget(self.delete_button)
        layout.addLayout(row)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.refresh()

    def refresh(self) -> None:
        from red.memory import PROFILE_TEMPLATE
        self.profile.setPlainText(self.memory.profile() or PROFILE_TEMPLATE)
        self.facts.clear()
        for fact in self.memory.facts():
            item = QListWidgetItem(fact.text)
            item.setData(Qt.ItemDataRole.UserRole, fact.id)
            item.setToolTip(f"{fact.source}, {fact.when[:16].replace('T', ' ')}"
                            + (f"\nFrom: {fact.said}" if fact.said else ""))
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
            self.facts.addItem(item)

    def add_fact(self) -> None:
        text = self.new_fact.text().strip()
        if not text:
            return
        try:
            fact = self.memory.add(text, source="app")
        except OSError as e:
            self.status.setText(f"Couldn't save it: {e}")
            return
        self.status.setText("" if fact else "Red already knows that, or it looks like a password "
                                              "or a code, which Red never keeps.")
        self.new_fact.clear()
        self.refresh()

    def delete_selected(self) -> None:
        for item in self.facts.selectedItems():
            self.memory.delete(item.data(Qt.ItemDataRole.UserRole))
        self.refresh()

    def save(self) -> None:
        """Called by the window's Save: the profile and any edited facts."""
        from red.memory import PROFILE_TEMPLATE
        profile = self.profile.toPlainText().strip()
        if profile and profile != PROFILE_TEMPLATE.strip():
            self.memory.save_profile(profile)
        known = {f.id: f.text for f in self.memory.facts()}
        for i in range(self.facts.count()):
            item = self.facts.item(i)
            fact_id = item.data(Qt.ItemDataRole.UserRole)
            if fact_id in known and item.text().strip() != known[fact_id]:
                self.memory.update(fact_id, item.text())
        self.refresh()
