"""The first-run wizard and the Start menu launcher, offscreen and with fakes."""

import json
import os
import sys
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

QtWidgets = pytest.importorskip("PySide6.QtWidgets")

from red import companions  # noqa: E402
from red.app import launch  # noqa: E402
from red.app.first_run import FirstRunWizard  # noqa: E402
from red.config import Settings  # noqa: E402
from red.memory import Memory  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication(["test"])


@pytest.fixture
def settings(tmp_path, monkeypatch):
    for key in [k for k in os.environ if k.startswith("RED_")]:
        monkeypatch.delenv(key)
    return Settings(home=tmp_path / "home", llm_url=None, llm_model="qwen3.5-4b", llm_backend="auto",
                    llm_gpu="auto", llm_keep_alive="5m", github_token=None)


class Monitor:
    def __init__(self, on_level, device):
        pass

    def start(self):
        pass

    def stop(self):
        pass


def make_wizard(settings, tmp_path, **kw):
    played = []
    wav = tmp_path / "sample.wav"
    wav.write_bytes(b"RIFF")
    wizard = FirstRunWizard(settings, hardware=lambda: [("CPU", "Test CPU"), ("GPU", "Test GPU"), ("VRAM", "6 GB"),
                                                        ("RAM", "16 GB"), ("Red's pick", "qwen3.5-4b")],
                            devices=lambda: [(0, "Built-in Mic"), (2, "USB Mic")], monitor_factory=Monitor,
                            voice_preview=lambda v, t: wav, play=played.append, **kw)
    wizard.played = played
    return wizard


def test_the_wizard_has_its_pages_in_order(app, settings, tmp_path):
    w = make_wizard(settings, tmp_path)
    titles = [w.page(i).title() for i in w.pageIds()]
    assert titles == ["Hello", "Your PC", "Microphone", "Who is Red for you?", "Download Red's brain and voice",
                      "All set"]
    assert w.character.companion.count() == 5
    assert not w.grab().isNull()


def test_finishing_saves_name_companion_voice_and_personality(app, settings, tmp_path):
    w = make_wizard(settings, tmp_path)
    w.intro.name.setText("Aryan")
    w.intro.about.setPlainText("I build robots\n\nI like tea")
    page = w.character
    page.companion.setCurrentIndex(page.companion.findData("remy"))
    page.voice.setCurrentIndex(page.voice.findData("af_nicole") if page.voice.findData("af_nicole") >= 0 else 1)
    chosen_voice = page.voice.currentData()
    page.humour.setCurrentIndex(page.humour.findData("cheeky"))
    page.temper.setCurrentIndex(page.temper.findData("high"))
    page.persona.setPlainText("Remy, but she teases more.")
    w.mic.page.device_combo.setCurrentIndex(w.mic.page.device_combo.findData(2))
    said = w.apply()
    assert "name: Aryan" in said and "companion: remy" in said
    assert Memory(settings.home).name() == "Aryan"
    assert sorted(f.text for f in Memory(settings.home).facts()) == ["I build robots", "I like tea"] or \
        len(Memory(settings.home).facts()) == 2
    remy = companions.load("remy", home=settings.home)
    assert (remy.humour, remy.temper, remy.voice_id) == ("cheeky", "high", chosen_voice)
    assert remy.persona == "Remy, but she teases more."
    assert companions.active_id(settings.home) == "remy"
    assert "RED_MIC_DEVICE=2" in (settings.home / "config" / ".env").read_text(encoding="utf-8")
    assert launch.first_run_done(settings.home)
    marker = json.loads(launch.marker_path(settings.home).read_text(encoding="utf-8"))
    assert marker["companion"] == "remy"


def test_an_untouched_wizard_writes_almost_nothing(app, settings, tmp_path):
    w = make_wizard(settings, tmp_path)
    w.apply()
    assert not (settings.home / "companions").exists() or not any((settings.home / "companions").rglob("*.toml"))
    assert Memory(settings.home).name() in (None, "")
    assert companions.active_id(settings.home) == "red"


def test_the_voice_sample_button_plays_what_the_helper_makes(app, settings, tmp_path):
    w = make_wizard(settings, tmp_path)
    w.character.sample.click()
    assert [p.name for p in w.played] == ["sample.wav"]

    def missing(voice, text):
        raise FileNotFoundError("kokoro.onnx")
    w.character.voice_preview = missing
    w.character.sample.click()
    assert "kokoro.onnx" in w.character.note.text() and len(w.played) == 1


def wait_for(app, condition, seconds=20):
    end = time.time() + seconds
    while time.time() < end and not condition():
        app.processEvents()
        time.sleep(0.02)
    assert condition()


def test_the_download_page_runs_setup_and_shows_its_output(app, settings, tmp_path):
    w = make_wizard(settings, tmp_path,
                    download_command=[sys.executable, "-c", "print('Downloading model 1 of 2'); print('done')"])
    page = w.downloads
    page.start()
    wait_for(app, lambda: not page.running())
    app.processEvents()
    assert page.finished_ok and "Downloading model 1 of 2" in page.log.toPlainText()
    assert "Everything Red needs is here" in page.status.text()
    failing = make_wizard(settings, tmp_path, download_command=[sys.executable, "-c", "raise SystemExit(3)"])
    failing.downloads.start()
    wait_for(app, lambda: not failing.downloads.running())
    app.processEvents()
    assert not failing.downloads.finished_ok and "later" in failing.downloads.status.text()


# --- the launcher ---------------------------------------------------------------------------------------

def test_install_root_is_found_from_the_embedded_python(tmp_path):
    (tmp_path / "python").mkdir()
    (tmp_path / "app" / "red").mkdir(parents=True)
    exe = tmp_path / "python" / "pythonw.exe"
    exe.write_bytes(b"")
    assert launch.install_root(str(exe)) == tmp_path.resolve()
    other = tmp_path / "somewhere" / "python.exe"
    other.parent.mkdir()
    other.write_bytes(b"")
    assert launch.install_root(str(other)) is None


def test_first_launch_runs_the_wizard_then_starts_red(tmp_path, monkeypatch):
    for key in [k for k in os.environ if k.startswith("RED_")]:
        monkeypatch.delenv(key)
    monkeypatch.setenv("RED_HOME", str(tmp_path))
    calls = []
    code = launch.main(wizard=lambda s: calls.append("wizard") or True, start=lambda: calls.append("start"),
                       running=lambda: False)
    assert code == 0 and calls == ["wizard", "start"]
    launch.mark_first_run_done(tmp_path)
    calls.clear()
    launch.main(wizard=lambda s: calls.append("wizard") or True, start=lambda: calls.append("start"),
                running=lambda: False)
    assert calls == ["start"]                                # done once: no wizard again


def test_closing_the_wizard_starts_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv("RED_HOME", str(tmp_path))
    calls = []
    launch.main(wizard=lambda s: False, start=lambda: calls.append("start"), running=lambda: False)
    assert calls == [] and not launch.first_run_done(tmp_path)


def test_when_red_is_running_the_start_menu_opens_the_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("RED_HOME", str(tmp_path))
    launch.mark_first_run_done(tmp_path)
    calls = []
    code = launch.main(start=lambda: calls.append("start"), running=lambda: True,
                       open_settings=lambda s: calls.append("settings") or 0)
    assert code == 0 and calls == ["settings"]
