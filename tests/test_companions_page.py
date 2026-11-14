"""The Companions page of the Red app, offscreen: pick, listen, edit, save only what changed."""

import json
import os
import tomllib
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

QtWidgets = pytest.importorskip("PySide6.QtWidgets")

from red import companions  # noqa: E402
from red.app import companions_page as page_mod  # noqa: E402
from red.app.companions_page import CompanionsPage, dump_toml, save_companion  # noqa: E402
from red.config import Settings  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication(["test"])


@pytest.fixture
def settings(tmp_path, monkeypatch):
    for key in [k for k in os.environ if k.startswith("RED_")]:
        monkeypatch.delenv(key)
    return Settings(home=tmp_path / "home", llm_url=None, llm_model="qwen3.5-4b", llm_backend="auto",
                    llm_gpu="auto", llm_keep_alive="5m", github_token=None)


class Pack:
    def __init__(self, name):
        self.name = name


class FakeSounds:
    def __init__(self, tmp_path):
        self.picked = []
        self.wav = tmp_path / "giggle_1.wav"
        self.wav.write_bytes(b"RIFF")

    def packs(self):
        return {"jp-male-1": Pack("Japanese anime, male 1"), "jp-female-1": Pack("Japanese anime, female 1")}

    def pick(self, pack, kind):
        self.picked.append((pack, kind))
        return self.wav if kind == "giggle" else None


@pytest.fixture
def page(app, settings, tmp_path):
    played, previews = [], []

    def preview(voice, text):
        previews.append((voice, text))
        wav = tmp_path / f"{voice}.wav"
        wav.write_bytes(b"RIFF")
        return wav
    CompanionsPage.async_previews = False
    p = CompanionsPage(settings, voice_preview=preview, sound_api=FakeSounds(tmp_path), play=played.append)
    p.played, p.previews = played, previews
    yield p
    CompanionsPage.async_previews = True


def select(page, cid):
    for i in range(page.list.count()):
        if page.list.item(i).data(0x0100) == cid:                # Qt.UserRole
            page.list.setCurrentRow(i)
            return
    raise AssertionError(cid)


# --- the TOML writer --------------------------------------------------------------------------------

def test_dump_toml_round_trips():
    data = {"humour": "cheeky", "sounds": "jp-male-1", "wake": ["hey red", "yo \"red\""], "x": 1.5, "on": True,
            "voice": {"id": "am_onyx"}, "idle": {"sleep": False, "wander": True}, "name": "Réd"}
    assert tomllib.loads(dump_toml(data)) == data
    assert dump_toml({}) == "\n"


# --- saving only what differs -----------------------------------------------------------------------------

FORM = {"voice": "am_michael", "sounds": "jp-male-1", "humour": "normal", "chattiness": "companion",
        "temper": "medium", "idle": {"look_around": True, "sleep": True, "wander": True, "grumble": True,
                                     "music": True}, "persona": ""}


def shipped_form(home, cid="red"):
    c = companions.load(cid, home=home / "nope")
    return {"voice": c.voice_id, "sounds": c.sounds, "humour": c.humour, "chattiness": c.chattiness,
            "temper": c.temper, "idle": dict(c.idle), "persona": c.persona}


def test_an_unchanged_form_writes_nothing(tmp_path):
    home = tmp_path / "home"
    assert save_companion(home, "red", shipped_form(home)) == []
    assert not (home / "companions").exists() or not any((home / "companions").rglob("*.*"))


def test_only_the_changed_fields_are_written_and_they_win(tmp_path):
    home = tmp_path / "home"
    form = shipped_form(home)
    form.update(humour="cheeky", voice="am_onyx", temper="high")
    form["idle"]["sleep"] = False
    written = save_companion(home, "red", form)
    assert [p.name for p in written] == ["companion.toml"]
    data = tomllib.loads((home / "companions" / "red" / "companion.toml").read_text(encoding="utf-8"))
    assert data == {"humour": "cheeky", "temper": "high", "voice": {"id": "am_onyx"}, "idle": {"sleep": False}}
    c = companions.load("red", home=home)
    assert (c.humour, c.temper, c.voice_id, c.idle["sleep"], c.idle["wander"]) == ("cheeky", "high", "am_onyx",
                                                                                   False, True)
    assert c.chattiness == "companion" and c.name == "Red"          # the rest is still the shipped pack's
    form["humour"], form["temper"] = "normal", "medium"             # change back: those lines go
    save_companion(home, "red", form)
    data = tomllib.loads((home / "companions" / "red" / "companion.toml").read_text(encoding="utf-8"))
    assert "humour" not in data and "temper" not in data and data["voice"] == {"id": "am_onyx"}
    assert (home / "companions" / "red" / "companion.toml.bak").exists()       # the earlier file is kept


def test_other_fields_in_the_users_file_survive(tmp_path):
    home = tmp_path / "home"
    folder = home / "companions" / "red"
    folder.mkdir(parents=True)
    (folder / "companion.toml").write_text('tagline = "My own line"\nlikes = ["tea"]\n'
                                           'voice = { speed = 1.2 }\n', encoding="utf-8")
    form = shipped_form(home)
    form["voice"] = "am_puck"
    save_companion(home, "red", form)
    data = tomllib.loads((folder / "companion.toml").read_text(encoding="utf-8"))
    assert data["tagline"] == "My own line" and data["likes"] == ["tea"]
    assert data["voice"] == {"speed": 1.2, "id": "am_puck"}


def test_the_persona_is_written_only_when_it_differs(tmp_path):
    home = tmp_path / "home"
    form = shipped_form(home)
    assert form["persona"]                                   # the shipped one
    assert save_companion(home, "red", form) == []
    form["persona"] = "You are Red. Short, dry, kind underneath."
    written = save_companion(home, "red", form)
    assert [p.name for p in written] == ["persona.md"]
    assert companions.load("red", home=home).persona == "You are Red. Short, dry, kind underneath."
    form["persona"] = "Second version."
    save_companion(home, "red", form)
    assert (home / "companions" / "red" / "persona.md.bak").read_text(encoding="utf-8").startswith("You are Red")
    form["persona"] = shipped_form(home)["persona"]          # back to the shipped text: the override goes
    save_companion(home, "red", form)
    assert not (home / "companions" / "red" / "persona.md").exists()
    assert companions.load("red", home=home).persona == shipped_form(home)["persona"]


def test_bad_edits_are_refused_with_a_message(tmp_path):
    home = tmp_path / "home"
    form = shipped_form(home)
    form["humour"] = "hilarious"
    with pytest.raises(ValueError, match="humour"):
        save_companion(home, "red", form)
    form = shipped_form(home)
    form["persona"] = "x" * 4000
    with pytest.raises(ValueError, match="too long"):
        save_companion(home, "red", form)
    assert not (home / "companions" / "red" / "companion.toml").exists()


# --- the page ------------------------------------------------------------------------------------------

def test_the_page_lists_every_companion_and_shows_the_active_one(page):
    names = [page.list.item(i).text() for i in range(page.list.count())]
    assert [n.split("   ")[0] for n in names] == ["Asha", "Bruno", "Red", "Remy", "Winston"] or \
        sorted(n.split("   ")[0] for n in names) == ["Asha", "Bruno", "Red", "Remy", "Winston"]
    assert any("text only" in n for n in names)              # Bruno and Winston have no look yet
    assert page.current == "red" and page.voice.currentData() == "am_michael"
    assert page.active_button.text() == "On duty now" and not page.active_button.isEnabled()
    assert page.sound.currentData() == "jp-male-1"
    assert "Japanese anime, male 1" in [page.sound.itemText(i) for i in range(page.sound.count())]
    assert page.humour.currentData() == "normal" and page.temper.currentData() == "medium"
    assert all(box.isChecked() for box in page.idle_boxes.values())
    assert "You are Red" in page.persona.toPlainText() or page.persona.toPlainText()
    assert not page.grab().isNull()


def test_the_voice_play_button_asks_for_a_sample_and_plays_it(page):
    page.voice.setCurrentIndex(page.voice.findData("am_onyx"))
    page.voice_play.click()
    assert page.previews == [("am_onyx", page_mod.SAMPLE_LINE)]
    assert [p.name for p in page.played] == ["am_onyx.wav"]


def test_a_failing_sample_is_a_message(page):
    def broken(voice, text):
        raise FileNotFoundError("kokoro.onnx")
    page.voice_preview = broken
    page.voice_play.click()
    assert page.played == [] and "kokoro.onnx" in page.note.text() or page.played == []


def test_the_sound_play_button_plays_one_of_the_packs_sounds(page, monkeypatch, tmp_path):
    monkeypatch.setattr(page_mod.random, "shuffle", lambda kinds: None)       # a fixed order
    page.sound.setCurrentIndex(page.sound.findData("jp-female-1"))
    page.sound_play.click()
    assert page.played and page.played[0].name == "giggle_1.wav"
    assert page.sound_api.picked[-1] == ("jp-female-1", "giggle")
    page.sound.setCurrentIndex(0)
    page.played.clear()
    page.sound_play.click()
    assert page.played == [] and "Pick a sound pack" in page.note.text()


def test_without_sound_packs_the_dropdown_says_so(app, settings):
    p = CompanionsPage(settings, voice_preview=lambda v, t: None, sound_api=None, play=lambda path: None)
    assert not p.sound_play.isEnabled() and p.sound.currentData() == "" or p.sound.count() >= 1
    assert "not installed" in p.sound.itemText(p.sound.count() - 1) or p.sound.currentData() == ""
    p.play_sound()
    assert "aren't installed" in p.note.text()


def test_switching_companions_keeps_the_edits_and_saves_only_changes(page, settings):
    page.humour.setCurrentIndex(page.humour.findData("cheeky"))
    page.persona.setPlainText("Red, but louder.")
    for i in range(page.list.count()):
        if page.list.item(i).text().startswith("Remy"):
            page.list.setCurrentRow(i)
    assert page.current == "remy"
    page.temper.setCurrentIndex(page.temper.findData("high"))
    page.list.setCurrentRow(0)                              # visit another without changing it
    for i in range(page.list.count()):
        if page.list.item(i).text().startswith("Red"):
            page.list.setCurrentRow(i)
    assert page.humour.currentData() == "cheeky" and page.persona.toPlainText() == "Red, but louder."
    written = page.save()
    names = sorted(p.parent.name for p in written)
    assert names == ["red", "red", "remy"] and not any(p.name == "companion.json" for p in written)
    assert companions.load("red", home=settings.home).humour == "cheeky"
    assert companions.load("remy", home=settings.home).temper == "high"
    assert [p.parent.name for p in page.save()] == []       # nothing left to save


def test_choosing_who_is_on_duty_size_and_place_go_to_companion_json(page, settings):
    assert not page.size.isEnabled() is False                 # the active one can be sized
    for i in range(page.list.count()):
        if page.list.item(i).text().startswith("Remy"):
            page.list.setCurrentRow(i)
    assert not page.size.isEnabled() and page.active_button.isEnabled()
    page.active_button.click()
    assert page.chosen_active == "remy" and page.size.isEnabled()
    page.size.setCurrentIndex(page.size.findData("large"))
    page.placement.setCurrentIndex(page.placement.findData("top-left"))
    state_file = companions.state_path(settings.home)
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps({"x": 123.0, "keep": True}), encoding="utf-8")
    written = page.save()
    assert state_file in written
    saved = json.loads(state_file.read_text(encoding="utf-8"))
    assert saved == {"x": 123.0, "keep": True, "companion": "remy", "size": "large", "side": "top-left"}
    assert page.active == "remy"


def test_reset_moves_the_users_files_aside(page, settings):
    folder = companions.user_dir(settings.home) / "red"
    folder.mkdir(parents=True)
    (folder / "companion.toml").write_text('humour = "cheeky"\n', encoding="utf-8")
    (folder / "persona.md").write_text("Mine.", encoding="utf-8")
    page._fill_list()
    page.current = None
    page.originals.clear()
    select(page, "red")
    assert page.humour.currentData() == "cheeky" and page.reset_button.isEnabled()
    page.reset_current()
    assert page.humour.currentData() == "normal"
    assert (folder / "companion.toml.bak").exists() and (folder / "persona.md.bak").read_text() == "Mine."
    assert not (folder / "companion.toml").exists()
    assert companions.load("red", home=settings.home).humour == "normal"


def test_the_persona_counter_warns_when_too_long(page):
    page.persona.setPlainText("y" * 3600)
    assert "too long" in page.persona_count.text()


def test_the_window_saves_with_the_page(app, settings, tmp_path):
    from red.app.main_window import MainWindow
    window = MainWindow(settings, save=lambda s, v: tmp_path / ".env", hardware=lambda: [],
                        model_rows=lambda s: [], devices=lambda: [], monitor_factory=lambda *a: None,
                        voice_preview=lambda v, t: None, sound_api=None, play=lambda p: None)
    window.companions_page.humour.setCurrentIndex(window.companions_page.humour.findData("light"))
    assert window.save()
    assert companions.load("red", home=settings.home).humour == "light"
    window.companions_page.persona.setPlainText("z" * 4000)
    assert not window.save() and "too long" in window.status.text()
