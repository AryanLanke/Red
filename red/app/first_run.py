"""The first-run wizard: the first time Red starts from the installer.

Seven pages: hello (your name and a few things about you) · your PC · microphone · who is Red for you
(companion pick, voice with a ▶ sample, humour, chattiness, temper and a persona) · downloads · done.
Nothing is written until Finish. The companion and personality go through the same code as the app's
Companions page (red/app/companions_page.py), so the files are the same and can be changed there later.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from PySide6.QtCore import QProcess, Qt
from PySide6.QtWidgets import (QComboBox, QLabel, QLineEdit, QPlainTextEdit, QProgressBar, QPushButton,
                               QVBoxLayout, QWizard, QWizardPage, QHBoxLayout, QFormLayout)

from red import companions
from red.memory import Memory

from . import env_file
from .companions_page import (CHATTINESS_LABELS, HUMOUR_LABELS, SAMPLE_LINE, TEMPER_LABELS,
                              default_play, default_voice_preview, save_companion, shipped_companion)
from .launch import mark_first_run_done
from .pages import AudioSetupPage, HardwareCheckPage, _hint, _title, voice_label

log = logging.getLogger(__name__)


class IntroPage(QWizardPage):
    def __init__(self):
        super().__init__()
        self.setTitle("Hello")
        layout = QVBoxLayout(self)
        layout.addWidget(_hint("Red is a friend that lives on this PC: it hears you, remembers you and does your "
                               "work. Everything stays on this computer. A few questions first."))
        form = QFormLayout()
        self.name = QLineEdit()
        self.name.setPlaceholderText("What should I call you?")
        self.about = QPlainTextEdit()
        self.about.setPlaceholderText("Anything you'd like me to know from the start: what you do, what you like. "
                                      "One thing per line. Skip it if you like.")
        self.about.setFixedHeight(110)
        form.addRow("Your name", self.name)
        form.addRow("About you", self.about)
        layout.addLayout(form)


class PcPage(QWizardPage):
    def __init__(self, hardware):
        super().__init__()
        self.setTitle("Your PC")
        layout = QVBoxLayout(self)
        layout.addWidget(_hint("This is what Red found, and what it will run on."))
        self.page = HardwareCheckPage(hardware=hardware)
        layout.addWidget(self.page)


class MicPage(QWizardPage):
    def __init__(self, settings, devices, monitor_factory):
        super().__init__()
        self.setTitle("Microphone")
        layout = QVBoxLayout(self)
        layout.addWidget(_hint("Speak and watch the bar move. If it doesn't, pick another microphone."))
        self.page = AudioSetupPage(settings, devices=devices, monitor_factory=monitor_factory)
        layout.addWidget(self.page)

    def cleanupPage(self):  # noqa: N802
        self.page.stop_test()

    def validatePage(self):  # noqa: N802
        self.page.stop_test()
        return True


class CharacterPage(QWizardPage):
    """Who Red is for you: the companion, its voice, and a little personality."""

    def __init__(self, settings, voice_preview, play):
        super().__init__()
        self.settings = settings
        self.voice_preview = voice_preview
        self.play = play
        self.setTitle("Who is Red for you?")
        self.packs = companions.load_all(settings.home)
        self.picture_ids: set[str] = set()
        try:
            from red.avatar import available_companions
            self.picture_ids = set(available_companions(settings.models_dir))
        except Exception:  # noqa: BLE001
            pass
        layout = QVBoxLayout(self)
        layout.addWidget(_hint("Pick who is on duty, how they sound and how they talk. You can change all of it later "
                               "in Red's settings, on the Companions tab."))
        form = QFormLayout()
        self.companion = QComboBox()
        for cid, comp in self.packs.items():
            note = "" if comp.avatar in self.picture_ids or cid in self.picture_ids else "  (no picture yet)"
            self.companion.addItem(f"{comp.name}: {comp.tagline}{note}" if comp.tagline else f"{comp.name}{note}", cid)
        self.companion.setMinimumWidth(380)
        form.addRow("Companion", self.companion)
        self.voice = QComboBox()
        self.sample = QPushButton("▶")
        self.sample.setFixedWidth(40)
        self.sample.clicked.connect(self.play_voice)
        row = QHBoxLayout()
        row.addWidget(self.voice, 1)
        row.addWidget(self.sample)
        form.addRow("Voice", row)
        self.humour = self._combo(HUMOUR_LABELS)
        self.chattiness = self._combo(CHATTINESS_LABELS)
        self.temper = self._combo(TEMPER_LABELS)
        form.addRow("Humour", self.humour)
        form.addRow("Chattiness", self.chattiness)
        form.addRow("Temper", self.temper)
        layout.addLayout(form)
        layout.addWidget(QLabel("Persona: who they are and how they talk"))
        self.persona = QPlainTextEdit()
        self.persona.setFixedHeight(130)
        layout.addWidget(self.persona)
        self.note = _hint("")
        layout.addWidget(self.note)
        self.companion.currentIndexChanged.connect(lambda *_: self.show_companion())
        index = self.companion.findData(companions.active_id(settings.home))
        self.companion.setCurrentIndex(max(0, index))
        self.show_companion()

    @staticmethod
    def _combo(labels):
        box = QComboBox()
        for value, label in labels.items():
            box.addItem(label, value)
        return box

    def show_companion(self) -> None:
        comp = self.packs[self.companion.currentData()]
        self.voice.clear()
        for v in dict.fromkeys([*comp.voices, comp.voice_id]):
            self.voice.addItem(voice_label(v), v)
        for box, value in ((self.voice, comp.voice_id), (self.humour, comp.humour),
                           (self.chattiness, comp.chattiness), (self.temper, comp.temper)):
            box.setCurrentIndex(max(0, box.findData(value)))
        self.persona.setPlainText(comp.persona)

    def play_voice(self) -> None:
        voice = self.voice.currentData()
        if not voice:
            return
        self.note.setText("Getting the sample ready…")
        try:
            path = self.voice_preview(voice, SAMPLE_LINE)
        except Exception as e:  # noqa: BLE001 - the voice models may not be downloaded yet
            self.note.setText(f"I can't play a sample yet ({e}). The voices download on the next page.")
            return
        self.note.setText("")
        if path is not None:
            self.play(Path(path))

    def form(self) -> dict:
        comp = self.packs[self.companion.currentData()]
        return {"voice": self.voice.currentData() or "", "sounds": comp.sounds,
                "humour": self.humour.currentData(), "chattiness": self.chattiness.currentData(),
                "temper": self.temper.currentData(), "idle": dict(comp.idle),
                "persona": self.persona.toPlainText().strip()}


class DownloadPage(QWizardPage):
    """Runs `red setup` (the models: language model, speech, voice, wake word) and shows its output."""

    def __init__(self, settings, command=None):
        super().__init__()
        self.settings = settings
        self.setTitle("Download Red's brain and voice")
        self.command = command or [sys.executable, "-m", "red", "--home", str(settings.home), "setup"]
        self.process: QProcess | None = None
        self.finished_ok = False
        layout = QVBoxLayout(self)
        layout.addWidget(_hint("Red downloads its language model, speech recognition, voice and wake word once: "
                               "about 3.5 to 6 GB depending on your PC, checked against known checksums. "
                               "It can stop and resume. You can also do it later from the settings."))
        self.button = QPushButton("Download now")
        self.button.clicked.connect(self.start)
        layout.addWidget(self.button, 0, Qt.AlignmentFlag.AlignLeft)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1)
        layout.addWidget(self.bar)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(500)
        layout.addWidget(self.log)
        self.status = _hint("")
        layout.addWidget(self.status)

    def running(self) -> bool:
        return self.process is not None and self.process.state() != QProcess.ProcessState.NotRunning

    def start(self) -> None:
        if self.running():
            return
        self.log.clear()
        self.finished_ok = False
        self.process = QProcess(self)
        self.process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.process.readyReadStandardOutput.connect(self._read)
        self.process.finished.connect(self._done)
        self.process.errorOccurred.connect(lambda *_: self._done(-1, None))
        self.bar.setRange(0, 0)
        self.button.setEnabled(False)
        self.status.setText("Downloading…")
        self.process.start(self.command[0], self.command[1:])

    def _read(self) -> None:
        text = bytes(self.process.readAllStandardOutput()).decode("utf-8", errors="replace")
        for line in text.replace("\r", "\n").splitlines():
            if line.strip():
                self.log.appendPlainText(line.rstrip())

    def _done(self, code, _status) -> None:
        self.bar.setRange(0, 1)
        self.bar.setValue(1 if code == 0 else 0)
        self.finished_ok = code == 0
        self.button.setEnabled(True)
        self.button.setText("Download again" if code == 0 else "Try again")
        self.status.setText("Everything Red needs is here." if code == 0 else
                            "That didn't finish. You can try again, or carry on and do it later from the settings.")
        self.completeChanged.emit()

    def cleanupPage(self):  # noqa: N802
        pass


class DonePage(QWizardPage):
    def __init__(self):
        super().__init__()
        self.setTitle("All set")
        self.setFinalPage(True)
        layout = QVBoxLayout(self)
        self.text = QLabel("")
        self.text.setWordWrap(True)
        layout.addWidget(self.text)

    def initializePage(self):  # noqa: N802
        self.setFinalPage(True)
        self.text.setText("Press Finish and Red starts. It takes about ten seconds to load; then say \"Hey Red\" or "
                          "press Ctrl+Alt+R. Right-click the companion for everything else, and Ctrl+Alt+H shows or "
                          "hides it. To make it recognise your voice, run \"python -m red voice-setup\" later from "
                          "the settings.")


class FirstRunWizard(QWizard):
    def __init__(self, settings, *, hardware=None, devices=None, monitor_factory=None, voice_preview=None,
                 play=None, download_command=None, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("Welcome to Red")
        self.setWizardStyle(QWizard.WizardStyle.ModernStyle)
        self.setOption(QWizard.WizardOption.NoCancelButtonOnLastPage, False)
        self.setMinimumSize(720, 560)
        self.intro = IntroPage()
        self.pc = PcPage(hardware)
        self.mic = MicPage(settings, devices, monitor_factory)
        self.character = CharacterPage(settings, voice_preview or default_voice_preview(settings),
                                       play or default_play)
        self.downloads = DownloadPage(settings, download_command)
        self.done = DonePage()
        for page in (self.intro, self.pc, self.mic, self.character, self.downloads, self.done):
            self.addPage(page)
        self.applied = False

    def apply(self) -> list[str]:
        """Write everything the pages collected. Returns what was written, in words."""
        said: list[str] = []
        memory = Memory(self.settings.home)
        name = self.intro.name.text().strip()
        if name:
            memory.set_name(name)
            said.append(f"name: {name}")
        for line in self.intro.about.toPlainText().splitlines():
            if line.strip():
                memory.add(line.strip(), source="told")
                said.append("a fact about you")
        values = self.mic.page.values()
        if values:
            env_file.save_values(self.settings, values)
            said.append("microphone")
        cid = self.character.companion.currentData()
        form = self.character.form()
        save_companion(self.settings.home, cid, form)
        companions.set_active(cid, self.settings.home)
        said.append(f"companion: {cid}")
        mark_first_run_done(self.settings.home, companion=cid)
        self.applied = True
        return said

    def accept(self) -> None:
        try:
            self.apply()
        except (OSError, ValueError) as e:
            log.exception("First run couldn't save")
            self.done.text.setText(f"Couldn't save your choices: {e}")
            return
        super().accept()


def run_wizard(settings, **kwargs) -> bool:
    """Show the wizard and wait. True when it was finished."""
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv[:1])
    wizard = FirstRunWizard(settings, **kwargs)
    wizard.show()
    app.exec()
    return wizard.applied
