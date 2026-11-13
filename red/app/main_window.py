"""The Red app: one window, six pages, one Save button."""

from __future__ import annotations

from PySide6.QtWidgets import (QHBoxLayout, QLabel, QMainWindow, QPushButton, QTabWidget,
                               QVBoxLayout, QWidget)

from red.chat import write_personality
from red.config import Settings
from red.listener import normalize_hotkey

from .env_file import save_values
from .pages import (AudioSetupPage, GeneralSettingsPage, HardwareCheckPage, MemoryPage,
                    ModelStatusPage, VoiceSettingsPage)

_OFF = {"", "off", "none", "0", "no", "false", "disabled"}
TITLES = ("Hardware Check", "Model Status", "Audio Setup", "Voice Settings", "General Settings",
          "Memory")


class MainWindow(QMainWindow):
    """Setup and settings without editing .env by hand."""

    def __init__(self, settings: Settings, *, save=save_values, hardware=None, model_rows=None,
                 devices=None, monitor_factory=None, memory=None, parent=None):
        super().__init__(parent)
        self.settings = settings
        self._save = save
        self.setWindowTitle("Red — Setup & Settings")
        self.resize(780, 600)
        self.setMinimumSize(640, 480)

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(18, 14, 18, 14)
        heading = QLabel("Red")
        heading.setStyleSheet("font-size: 22px; font-weight: 700;")
        layout.addWidget(heading)
        subtitle = QLabel("Everything Red needs to sound good and act right — no .env archaeology.")
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet("color: #6b6b6b;")
        layout.addWidget(subtitle)

        self.tabs = QTabWidget()
        self.hardware_page = HardwareCheckPage(hardware=hardware)
        self.models_page = ModelStatusPage(settings, model_rows=model_rows)
        self.audio_page = AudioSetupPage(settings, devices=devices, monitor_factory=monitor_factory)
        self.voice_page = VoiceSettingsPage(settings)
        self.general_page = GeneralSettingsPage(settings)
        self.memory_page = MemoryPage(settings, memory=memory)
        for page, title in zip((self.hardware_page, self.models_page, self.audio_page,
                                self.voice_page, self.general_page, self.memory_page), TITLES):
            self.tabs.addTab(page, title)
        layout.addWidget(self.tabs, 1)

        bottom = QHBoxLayout()
        self.status = QLabel("")
        self.status.setWordWrap(True)
        bottom.addWidget(self.status, 1)
        self.save_button = QPushButton("Save settings")
        self.save_button.setObjectName("save")
        self.save_button.clicked.connect(self.save)
        bottom.addWidget(self.save_button)
        layout.addLayout(bottom)
        self.setCentralWidget(central)

    @property
    def pages(self) -> dict[str, QWidget]:
        return {self.tabs.tabText(i): self.tabs.widget(i) for i in range(self.tabs.count())}

    def values(self) -> dict[str, str]:
        values: dict[str, str] = {}
        for page in (self.audio_page, self.voice_page, self.general_page):
            values.update(page.values())
        return values

    def save(self) -> bool:
        values = self.values()
        hotkey = values["RED_HOTKEY"].strip()
        if hotkey.lower() not in _OFF:
            try:
                values["RED_HOTKEY"] = normalize_hotkey(hotkey)
            except ValueError as e:
                self.status.setStyleSheet("color: #b3261e;")
                self.status.setText(str(e))
                return False
        try:
            path = self._save(self.settings, values)
            write_personality(self.settings.home, self.general_page.personality_text())
            self.memory_page.save()
        except OSError as e:
            self.status.setStyleSheet("color: #b3261e;")
            self.status.setText(f"Couldn't save your settings: {e}")
            return False
        self.status.setStyleSheet("color: #2e7d32;")
        self.status.setText(f"Saved to {path}. Restart Red and it'll use the new settings.")
        return True

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt's name
        self.audio_page.stop_test()
        super().closeEvent(event)
