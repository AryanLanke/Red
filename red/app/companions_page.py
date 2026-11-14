"""The Companions page of the Red app: pick who is on duty, change how they sound and behave.

- the list of companions (shipped and your own), with their picture
- a voice dropdown with a ▶ sample, and a sound-pack dropdown with a ▶ sample
- who they are: persona text, humour, chattiness, temper and the idle switches (look around, sleep,
  wander, grumble, play music)
- the size and placement of the companion on screen

Saving writes only what differs from the shipped pack, to RED_HOME\\companions\\<id>\\companion.toml and
persona.md (red/companions.py reads them, your fields winning one by one). A persona or file you replace
is moved to a .bak, not deleted. The size, the placement and the active companion go to cache\\companion.json,
which the running companion window notices within a couple of seconds.
"""

from __future__ import annotations

import json
import logging
import random
import threading
import tomllib
from pathlib import Path
from typing import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFormLayout, QHBoxLayout, QLabel, QListWidget,
                               QListWidgetItem, QPlainTextEdit, QPushButton, QScrollArea, QVBoxLayout,
                               QWidget)

from red import companions
from red.avatar import SIDES, SIZES

from .pages import _hint, _title, voice_label

log = logging.getLogger(__name__)

HUMOUR_LABELS = {"off": "Off: serious", "light": "Light: now and then", "normal": "Normal", "cheeky": "Cheeky"}
CHATTINESS_LABELS = {"quiet": "Quiet: only answers", "friendly": "Friendly: says hello",
                     "chatty": "Chatty: hellos and one-liners", "companion": "Companion: starts things"}
TEMPER_LABELS = {"low": "Low: patient", "medium": "Medium", "high": "High: gets annoyed fast"}
IDLE_LABELS = {"look_around": "Look around, yawn, stretch", "sleep": "Doze off when left alone",
               "wander": "Walk along the edge and change corner", "grumble": "Grumble when ignored for long",
               "music": "Pick a song of their own now and then"}
PLACEMENT_LABELS = {"edge": "Bottom edge", "left": "Bottom-left corner", "right": "Bottom-right corner",
                    "top": "Top edge (hanging)", "top-left": "Top-left corner (hanging)",
                    "top-right": "Top-right corner (hanging)"}
SIZE_LABELS = {"small": "Small", "medium": "Medium", "large": "Large"}
SAMPLE_LINE = "Hey, it's me. This is how I sound. What do you need?"
SOUND_SAMPLE_KINDS = ("hover", "happy", "giggle", "surprised", "hmm", "pickup")
EDITED_HEADER = ("# Edited in the Red app. Only what differs from the shipped pack is here; these fields win,\n"
                 "# one by one. Delete a line to go back to the shipped value.\n")


# --------------------------------------------------------------------------
# A small TOML writer (the pack's files hold text, numbers, switches, lists and two tables)
# --------------------------------------------------------------------------

def _value(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(_value(x) for x in v) + "]"
    return json.dumps(str(v), ensure_ascii=False)


def dump_toml(data: dict) -> str:
    """`data` as TOML: plain keys first, then one `[table]` per dict value (one level deep)."""
    lines = [f"{k} = {_value(v)}" for k, v in data.items() if not isinstance(v, dict)]
    for name, table in data.items():
        if isinstance(table, dict) and table:
            lines += ["", f"[{name}]"] + [f"{k} = {_value(v)}" for k, v in table.items()]
    return "\n".join(lines) + "\n"


def _read_toml(path: Path) -> dict:
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        return {}


def _backup(path: Path) -> None:
    """Move a file aside to .bak (an earlier .bak is replaced)."""
    if path.exists():
        path.replace(path.with_name(path.name + ".bak"))


def shipped_companion(companion_id: str, home: Path):
    """The pack as shipped, without the user's edits (a home with no companions folder)."""
    return companions.load(companion_id, home=Path(home) / "cache" / "no-user-edits")


def save_companion(home: Path, companion_id: str, form: dict) -> list[Path]:
    """Write what differs from the shipped pack. `form` has voice, sounds, humour, chattiness, temper, idle
    (a dict of switches) and persona. Raises ValueError with a message fit to show. Returns the files written."""
    shipped = shipped_companion(companion_id, home)
    folder = companions.user_dir(home) / companion_id
    path = folder / "companion.toml"
    override = _read_toml(path)
    override.pop("id", None)
    wanted = {"humour": form["humour"], "chattiness": form["chattiness"], "temper": form["temper"],
              "sounds": form["sounds"]}
    for key, value in wanted.items():
        if value == getattr(shipped, key):
            override.pop(key, None)
        else:
            override[key] = value
    voice = dict(override.get("voice", {}))
    if form["voice"] and form["voice"] != shipped.voice_id:
        voice["id"] = form["voice"]
    else:
        voice.pop("id", None)
    if voice:
        override["voice"] = voice
    else:
        override.pop("voice", None)
    idle = {k: bool(v) for k, v in form["idle"].items() if bool(v) != bool(shipped.idle.get(k, True))}
    if idle:
        override["idle"] = idle
    else:
        override.pop("idle", None)
    bad = companions.problems({"id": companion_id, "name": shipped.name, **override})
    if bad:
        raise ValueError("; ".join(bad))
    persona = (form["persona"] or "").strip()
    if len(persona) > companions.MAX_PERSONA:
        raise ValueError(f"The persona is too long: {len(persona)} of {companions.MAX_PERSONA} characters.")
    written: list[Path] = []
    folder.mkdir(parents=True, exist_ok=True)
    text = dump_toml(override)
    if override or path.exists():
        if path.exists() and path.read_text(encoding="utf-8") != EDITED_HEADER + text:
            _backup(path)
        path.write_text(EDITED_HEADER + text, encoding="utf-8")
        written.append(path)
    persona_path = folder / "persona.md"
    if persona and persona != shipped.persona.strip():
        if persona_path.exists() and persona_path.read_text(encoding="utf-8").strip() != persona:
            _backup(persona_path)
        persona_path.write_text(persona + "\n", encoding="utf-8")
        written.append(persona_path)
    elif persona_path.exists():
        _backup(persona_path)                    # back to the shipped persona
        written.append(persona_path)
    return written


# --------------------------------------------------------------------------
# Samples
# --------------------------------------------------------------------------

def default_voice_preview(settings) -> Callable[[str, str], Path | None]:
    """voice id, text -> a WAV of that voice (lane 1's red.sounds.preview_voice when it exists, else Kokoro
    directly, cached under cache\\voice-preview)."""
    def preview(voice_id: str, text: str) -> Path | None:
        try:
            from red import sounds
            fn = getattr(sounds, "preview_voice", None)
            if fn is not None:
                return fn(voice_id, text)
        except ImportError:
            pass
        from red.avatar import write_wav
        from red.tts_kokoro import KokoroSpeaker
        path = Path(settings.home) / "cache" / "voice-preview" / f"{voice_id}.wav"
        if path.exists():
            return path
        speaker = KokoroSpeaker(Path(settings.models_dir) / "kokoro", voice_id)
        speaker.load()
        audio, rate = speaker.synthesize(text)
        write_wav(path, audio, rate)
        return path
    return preview


def default_sound_api():
    """red.sounds (packs, pick) or None until the sound packs exist."""
    try:
        from red import sounds
        return sounds if hasattr(sounds, "packs") and hasattr(sounds, "pick") else None
    except ImportError:
        return None


def default_play(path: Path) -> None:
    from red.avatar import play_clip
    play_clip(Path(path))


# --------------------------------------------------------------------------
# The page
# --------------------------------------------------------------------------

class CompanionsPage(QWidget):
    preview_ready = Signal(object)         # a WAV path from a worker thread -> played on the Qt thread
    preview_failed = Signal(str)

    async_previews = True

    def __init__(self, settings, *, voice_preview=None, sound_api="default", play=None, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.voice_preview = voice_preview or default_voice_preview(settings)
        self.sound_api = default_sound_api() if sound_api == "default" else sound_api
        self.play = play or default_play
        self.state_path = companions.state_path(settings.home)
        self.edits: dict[str, dict] = {}
        self.originals: dict[str, dict] = {}          # each companion's form as first shown
        self.screen_loaded: tuple = ()
        self.current: str | None = None
        self.active = companions.active_id(settings.home)
        self.chosen_active = self.active
        self._filling = False
        self.preview_ready.connect(self._play_path, Qt.ConnectionType.QueuedConnection)
        self.preview_failed.connect(self._note, Qt.ConnectionType.QueuedConnection)

        outer = QHBoxLayout(self)
        left = QVBoxLayout()
        left.addWidget(_title("Companions"))
        self.list = QListWidget()
        self.list.setMinimumWidth(190)
        self.list.setMaximumWidth(230)
        left.addWidget(self.list, 1)
        self.portrait = QLabel()
        self.portrait.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.portrait.setMinimumHeight(150)
        left.addWidget(self.portrait)
        outer.addLayout(left)

        body = QWidget()
        form = QVBoxLayout(body)
        self.tagline = _hint("")
        form.addWidget(self.tagline)
        self.active_button = QPushButton("Use this companion")
        self.active_button.clicked.connect(self._make_active)
        form.addWidget(self.active_button, 0, Qt.AlignmentFlag.AlignLeft)

        grid = QFormLayout()
        grid.setHorizontalSpacing(16)
        self.voice = QComboBox()
        self.voice.setMinimumWidth(230)
        self.voice_play = QPushButton("▶")
        self.voice_play.setToolTip("Hear this voice")
        self.voice_play.setFixedWidth(40)
        self.voice_play.clicked.connect(self.play_voice)
        row = QHBoxLayout()
        row.addWidget(self.voice, 1)
        row.addWidget(self.voice_play)
        grid.addRow("Voice", row)

        self.sound = QComboBox()
        self.sound_play = QPushButton("▶")
        self.sound_play.setToolTip("Hear a reaction sound from this pack")
        self.sound_play.setFixedWidth(40)
        self.sound_play.clicked.connect(self.play_sound)
        row = QHBoxLayout()
        row.addWidget(self.sound, 1)
        row.addWidget(self.sound_play)
        grid.addRow("Reaction sounds", row)

        self.humour = self._combo(HUMOUR_LABELS)
        self.chattiness = self._combo(CHATTINESS_LABELS)
        self.temper = self._combo(TEMPER_LABELS)
        grid.addRow("Humour", self.humour)
        grid.addRow("Chattiness", self.chattiness)
        grid.addRow("Temper", self.temper)
        self.idle_boxes = {key: QCheckBox(label) for key, label in IDLE_LABELS.items()}
        idle = QVBoxLayout()
        for box in self.idle_boxes.values():
            idle.addWidget(box)
        grid.addRow("When left alone", idle)
        form.addLayout(grid)

        form.addWidget(QLabel("Persona: who they are and how they talk"))
        self.persona = QPlainTextEdit()
        self.persona.setMinimumHeight(130)
        self.persona.setPlaceholderText("Who they are, how they talk, a couple of example exchanges.")
        form.addWidget(self.persona)
        self.persona_count = _hint("")
        form.addWidget(self.persona_count)

        screen = QFormLayout()
        self.size = self._combo(SIZE_LABELS)
        self.placement = self._combo(PLACEMENT_LABELS)
        screen.addRow("Size", self.size)
        screen.addRow("Where it sits", self.placement)
        self.screen_hint = _hint("Size and place apply to the companion on duty, and Red picks them up within a "
                                 "couple of seconds.")
        form.addLayout(screen)
        form.addWidget(self.screen_hint)
        self.reset_button = QPushButton("Back to the shipped version")
        self.reset_button.clicked.connect(self.reset_current)
        form.addWidget(self.reset_button, 0, Qt.AlignmentFlag.AlignLeft)
        self.note = _hint("")
        form.addWidget(self.note)
        form.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(body)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        outer.addWidget(scroll, 1)

        self._fill_list()
        self.list.currentRowChanged.connect(lambda *_: self._select())
        self.persona.textChanged.connect(self._count)
        index = next((i for i in range(self.list.count()) if self.list.item(i).data(Qt.ItemDataRole.UserRole)
                      == self.active), 0)
        self.list.setCurrentRow(index)
        self._select()

    # --- building ------------------------------------------------------------

    @staticmethod
    def _combo(labels: dict) -> QComboBox:
        box = QComboBox()
        for value, label in labels.items():
            box.addItem(label, value)
        return box

    def _fill_list(self) -> None:
        looks = set()
        try:
            from red.avatar import available_companions
            looks = set(available_companions(self.settings.models_dir))
        except Exception:  # noqa: BLE001
            pass
        self.looks = looks
        self.packs = companions.load_all(self.settings.home)
        self.list.clear()
        for cid, comp in self.packs.items():
            suffix = "" if cid in looks or comp.avatar in looks else "   (text only)"
            item = QListWidgetItem(f"{comp.name}{suffix}")
            item.setData(Qt.ItemDataRole.UserRole, cid)
            self.list.addItem(item)

    def _count(self) -> None:
        n = len(self.persona.toPlainText().strip())
        over = n > companions.MAX_PERSONA
        self.persona_count.setText(f"{n} of {companions.MAX_PERSONA} characters" + ("  (too long)" if over else ""))
        self.persona_count.setStyleSheet("color: #b3261e;" if over else "color: #6b6b6b;")

    # --- showing one companion -------------------------------------------------

    def _remember(self) -> None:
        if self.current:
            form = self.form()
            if form != self.originals.get(self.current):
                self.edits[self.current] = form          # only real changes are kept
            else:
                self.edits.pop(self.current, None)

    def _select(self) -> None:
        item = self.list.currentItem()
        if item is None:
            return
        self._remember()
        cid = item.data(Qt.ItemDataRole.UserRole)
        self.current = cid
        comp = self.packs[cid]
        edit = self.edits.get(cid)
        self._filling = True
        try:
            self.tagline.setText(comp.tagline or "")
            voices = list(dict.fromkeys([*comp.voices, comp.voice_id]))
            self.voice.clear()
            for v in voices:
                self.voice.addItem(voice_label(v), v)
            self._set(self.voice, edit["voice"] if edit else comp.voice_id)
            self._fill_sounds(comp, edit)
            self._set(self.humour, edit["humour"] if edit else comp.humour)
            self._set(self.chattiness, edit["chattiness"] if edit else comp.chattiness)
            self._set(self.temper, edit["temper"] if edit else comp.temper)
            for key, box in self.idle_boxes.items():
                box.setChecked(bool(edit["idle"][key]) if edit else bool(comp.idle.get(key, True)))
            self.persona.setPlainText(edit["persona"] if edit else comp.persona)
            self._show_portrait(comp)
            on_duty = self.chosen_active == cid
            self.active_button.setText("On duty now" if on_duty else "Use this companion")
            self.active_button.setEnabled(not on_duty)
            self.size.setEnabled(on_duty)
            self.placement.setEnabled(on_duty)
            saved = self._state()
            self._set(self.size, saved.get("size") or self.settings.companion_size)
            self._set(self.placement, next((k for k in SIDES if k == saved.get("side")), "right"))
            self.reset_button.setEnabled(self._has_user_files(cid))
            self.screen_loaded = (self.size.currentData(), self.placement.currentData())
        finally:
            self._filling = False
        self._count()
        self.originals.setdefault(cid, self.form())

    @staticmethod
    def _set(box: QComboBox, value) -> None:
        index = box.findData(value)
        if index >= 0:
            box.setCurrentIndex(index)

    def _fill_sounds(self, comp, edit) -> None:
        self.sound.clear()
        self.sound.addItem("No reaction sounds", "")
        packs = {}
        if self.sound_api is not None:
            try:
                packs = dict(self.sound_api.packs())
            except Exception:  # noqa: BLE001
                log.exception("Couldn't list the sound packs")
        wanted = edit["sounds"] if edit else comp.sounds
        for pid, pack in packs.items():
            self.sound.addItem(getattr(pack, "name", pid), pid)
        if wanted and self.sound.findData(wanted) < 0:
            self.sound.addItem(f"{wanted} (not installed)", wanted)
        self._set(self.sound, wanted or "")
        self.sound_play.setEnabled(self.sound_api is not None)
        if self.sound_api is None:
            self.sound.setToolTip("The sound packs aren't installed yet.")

    def _show_portrait(self, comp) -> None:
        folder = Path(self.settings.models_dir) / "companion" / (comp.avatar or comp.id)
        for name in ("cornerR_idle.png", "peek_idle.png"):
            if (folder / name).is_file():
                pm = QPixmap(str(folder / name))
                self.portrait.setPixmap(pm.scaledToHeight(150, Qt.TransformationMode.SmoothTransformation))
                return
        self.portrait.setPixmap(QPixmap())
        self.portrait.setText("No picture yet")

    def _state(self) -> dict:
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _has_user_files(self, cid: str) -> bool:
        folder = companions.user_dir(self.settings.home) / cid
        return any((folder / n).is_file() for n in ("companion.toml", "persona.md"))

    # --- reading the form ----------------------------------------------------------

    def form(self) -> dict:
        return {"voice": self.voice.currentData() or "", "sounds": self.sound.currentData() or "",
                "humour": self.humour.currentData(), "chattiness": self.chattiness.currentData(),
                "temper": self.temper.currentData(),
                "idle": {k: box.isChecked() for k, box in self.idle_boxes.items()},
                "persona": self.persona.toPlainText().strip()}

    # --- samples --------------------------------------------------------------------

    def _run(self, work: Callable[[], Path | None]) -> None:
        if not self.async_previews:
            self._finish(work)
            return
        self.note.setText("Getting the sample ready…")
        threading.Thread(target=self._finish, args=(work,), name="red-sample", daemon=True).start()

    def _finish(self, work) -> None:
        try:
            path = work()
        except Exception as e:  # noqa: BLE001 - a missing model is a message, not a crash
            log.exception("Sample failed")
            self._deliver(None, f"Couldn't make that sample: {e}")
            return
        self._deliver(path, "There is nothing to play for that choice.")

    def _deliver(self, path, problem: str) -> None:
        """From a worker thread, through the queued signals; in a test (no thread), straight away."""
        if self.async_previews:
            (self.preview_ready.emit(path) if path is not None else self.preview_failed.emit(problem))
        elif path is not None:
            self._play_path(path)
        else:
            self._note(problem)

    def _play_path(self, path) -> None:
        self.note.setText("")
        self.play(Path(path))

    def _note(self, text: str) -> None:
        self.note.setText(text)

    def play_voice(self) -> None:
        voice = self.voice.currentData()
        if not voice:
            return
        self._run(lambda: self.voice_preview(voice, SAMPLE_LINE))

    def play_sound(self) -> None:
        pack = self.sound.currentData()
        api = self.sound_api
        if not pack or api is None:
            self.note.setText("Pick a sound pack first." if api is not None else "The sound packs aren't installed yet.")
            return

        def pick() -> Path | None:
            kinds = list(SOUND_SAMPLE_KINDS)
            random.shuffle(kinds)
            for kind in kinds:
                path = api.pick(pack, kind)
                if path is not None:
                    return Path(path)
            return None
        self._run(pick)

    # --- actions -----------------------------------------------------------------------

    def _make_active(self) -> None:
        if self.current:
            self.chosen_active = self.current
            self.active_button.setText("On duty now")
            self.active_button.setEnabled(False)
            self.size.setEnabled(True)
            self.placement.setEnabled(True)

    def reset_current(self) -> None:
        """Back to the shipped pack: the user's files for this companion are moved to .bak."""
        cid = self.current
        if not cid:
            return
        folder = companions.user_dir(self.settings.home) / cid
        for name in ("companion.toml", "persona.md"):
            _backup(folder / name)
        self.edits.pop(cid, None)
        self._fill_list()
        for i in range(self.list.count()):
            if self.list.item(i).data(Qt.ItemDataRole.UserRole) == cid:
                self.list.setCurrentRow(i)
        self.current = None
        self._select()
        self.note.setText("Back to the shipped version. Your old files are kept as .bak.")

    def save(self) -> list[Path]:
        """Write every edited companion, the choice of who is on duty, and the size and place."""
        self._remember()
        written: list[Path] = []
        for cid, form in self.edits.items():
            if form != self.originals.get(cid):
                written += save_companion(self.settings.home, cid, form)
        state = self._state()
        changed = False
        if self.chosen_active != self.active:
            state["companion"] = self.chosen_active
            changed = True
        screen = (self.size.currentData(), self.placement.currentData())
        if self.size.isEnabled() and screen != self.screen_loaded:
            state["size"], state["side"] = screen
            changed = True
        if changed:                    # only what you changed, so a stale value never undoes Red's own
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            self.state_path.write_text(json.dumps(state), encoding="utf-8")
            written.append(self.state_path)
            self.active = self.chosen_active
            self.screen_loaded = screen
        for cid, form in self.edits.items():
            self.originals[cid] = form              # what is on disk now
        self.edits.clear()
        self.note.setText("")
        return written
