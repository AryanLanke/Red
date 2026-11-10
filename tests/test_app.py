"""The Red app, offscreen: every page works, and saving never wrecks the .env."""

import os
from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from red import hardware as hardware_mod  # noqa: E402
from red.config import Settings  # noqa: E402

QtWidgets = pytest.importorskip("PySide6.QtWidgets")

from red.app import env_file, status  # noqa: E402
from red.app import pages  # noqa: E402
from red.app.main_window import MainWindow, TITLES  # noqa: E402
from red.stt import WHISPER_MODELS  # noqa: E402
from red.tts import PIPER_VOICES  # noqa: E402
from red.tts_kokoro import KOKORO_FILES, VOICES  # noqa: E402
from red.wakeword import WAKE_WHISPER_MODEL  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication(["test"])


@pytest.fixture
def settings(tmp_path):
    return Settings(home=tmp_path / "home", llm_url=None, llm_model="qwen3.5-4b",
                    llm_backend="auto", llm_gpu="auto", llm_keep_alive="5m",
                    github_token=None)


HARDWARE = [("CPU", "Test CPU"), ("GPU", "Test GPU"), ("VRAM", "6.0 GB"), ("RAM", "16 GB"),
            ("Red's pick", "qwen3.5-4b with Whisper base.en (a 6 GB GPU)")]


def fake_model_rows(_settings):
    return [status.ModelRow("Language model", status.READY, "Here."),
            status.ModelRow("Kokoro voice", status.MISSING, "Not here yet.")]


class FakeMonitor:
    instances: list["FakeMonitor"] = []

    def __init__(self, on_level, device):
        self.on_level, self.device = on_level, device
        self.started = self.stopped = False
        FakeMonitor.instances.append(self)

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True


def make_window(settings, *, save=None, hardware=None, models=None, devices=None,
                monitor_factory=FakeMonitor):
    return MainWindow(
        settings,
        save=save or env_file.save_values,
        hardware=hardware or (lambda: list(HARDWARE)),
        model_rows=models or fake_model_rows,
        devices=devices or (lambda: [(0, "Built-in Mic"), (2, "USB Mic")]),
        monitor_factory=monitor_factory,
    )


# --- the window ---------------------------------------------------------------------

def test_the_window_has_the_five_pages(app, settings):
    window = make_window(settings)
    assert window.tabs.count() == 5
    assert list(window.pages) == list(TITLES)


def test_hardware_page_shows_what_it_is_given(app, settings):
    window = make_window(settings)
    assert window.hardware_page.values["CPU"].text() == "Test CPU"
    assert window.hardware_page.values["GPU"].text() == "Test GPU"
    assert window.hardware_page.values["VRAM"].text() == "6.0 GB"
    assert window.hardware_page.values["RAM"].text() == "16 GB"
    assert "qwen3.5-4b" in window.hardware_page.values["Red's pick"].text()


def test_hardware_refresh_picks_up_new_values(app, settings):
    rows = {"now": list(HARDWARE)}
    window = make_window(settings, hardware=lambda: rows["now"])
    rows["now"] = [("CPU", "A newer CPU"), *HARDWARE[1:]]
    window.hardware_page.refresh_button.click()
    assert window.hardware_page.values["CPU"].text() == "A newer CPU"


def test_hardware_that_cannot_be_read_is_explained(app, settings):
    def broken():
        raise OSError("no registry")
    window = make_window(settings, hardware=broken)
    assert "no registry" in window.hardware_page.values["CPU"].text()


def test_model_page_shows_each_state(app, settings):
    window = make_window(settings)
    assert [state.text() for _, state, _ in window.models_page.rows] == ["Ready", "Missing"]
    details = [detail.text() for _, _, detail in window.models_page.rows]
    assert details == ["Here.", "Not here yet."]


def test_model_refresh_asks_again(app, settings):
    calls = []

    def rows(_settings):
        calls.append(1)
        return [status.ModelRow(f"Row {len(calls)}", status.READY, "x")]
    window = make_window(settings, models=rows)
    window.models_page.refresh_button.click()
    assert [name.text() for name, _, _ in window.models_page.rows] == ["Row 2"]


def test_a_failing_model_check_does_not_close_the_app(app, settings):
    def broken(_settings):
        raise OSError("no disk")
    window = make_window(settings, models=broken)
    assert window.models_page.rows == []


# --- status: models ----------------------------------------------------------------

def write_pinned(folder, files):
    folder.mkdir(parents=True, exist_ok=True)
    for asset in files:
        (folder / asset.filename).write_bytes(b"x")


def test_model_rows_are_missing_before_setup(tmp_path):
    settings = Settings(home=tmp_path / "empty", llm_url=None, llm_model="qwen3.5-4b",
                        llm_backend="auto", llm_gpu="auto", llm_keep_alive="5m",
                        github_token=None)
    rows = status.model_rows(settings, tags=lambda: [])
    assert [row.state for row in rows] == [status.MISSING] * 5
    assert all("python -m red setup" in row.detail for row in rows)


def test_model_rows_see_every_installed_file(settings):
    settings.ensure_dirs()
    write_pinned(settings.models_dir / "whisper" / "small", WHISPER_MODELS["small"].files)
    write_pinned(settings.models_dir / "whisper" / WAKE_WHISPER_MODEL,
                 WHISPER_MODELS[WAKE_WHISPER_MODEL].files)
    write_pinned(settings.models_dir / "kokoro", KOKORO_FILES.files)
    write_pinned(settings.models_dir / "piper", PIPER_VOICES["en_US-lessac-medium"].files)
    rows = status.model_rows(settings, tags=lambda: ["qwen3.5:4b-q4_K_M"])
    assert [row.state for row in rows] == [status.READY] * 5


def test_llm_row_says_when_ollama_is_not_answering(settings):
    def tags():
        raise OSError("connection refused")
    row = status.llm_row(settings, tags=tags)
    assert row.state == status.MISSING
    assert "Ollama isn't answering" in row.detail


def test_llm_row_with_your_own_server(settings):
    row = status.llm_row(replace(settings, llm_url="http://127.0.0.1:1234/v1"),
                         tags=lambda: pytest.fail("a custom server is never probed"))
    assert row.state == status.UNKNOWN
    assert "127.0.0.1:1234" in row.detail


def test_llm_row_reports_a_downloaded_model(settings):
    row = status.llm_row(settings, tags=lambda: ["qwen3.5:4b-q4_K_M"])
    assert row.state == status.READY and "qwen3.5:4b-q4_K_M" in row.detail


def test_a_custom_wake_word_must_exist(settings, tmp_path):
    model = tmp_path / "my_wake.onnx"
    row = status.wakeword_row(replace(settings, wakeword=str(model)))
    assert row.state == status.MISSING
    model.write_bytes(b"x")
    assert status.wakeword_row(replace(settings, wakeword=str(model))).state == status.READY


# --- status: hardware --------------------------------------------------------------

def test_hardware_rows_use_the_hardware_module():
    fake = SimpleNamespace(
        gpu_gb=lambda: 6.0, ram_gb=lambda: 15.2, cpu_name=lambda: "Ryzen 7 7735HS",
        gpu_name=lambda: "NVIDIA GeForce RTX 4050",
        detect=lambda: hardware_mod.Choice("qwen3.5-4b", "base.en", "cpu", "a 6 GB GPU"))
    rows = dict(status.hardware_rows(fake))
    assert rows["CPU"] == "Ryzen 7 7735HS"
    assert rows["GPU"] == "NVIDIA GeForce RTX 4050"
    assert rows["VRAM"] == "6.0 GB"
    assert rows["RAM"] == "15 GB"
    assert "qwen3.5-4b" in rows["Red's pick"] and "base.en" in rows["Red's pick"]


def test_hardware_rows_on_a_cpu_only_pc():
    fake = SimpleNamespace(gpu_gb=lambda: None, ram_gb=lambda: 8.0, cpu_name=lambda: "CPU",
                           gpu_name=lambda: None,
                           detect=lambda: hardware_mod.Choice("qwen2.5-3b", "base.en", "cpu",
                                                              "no GPU and 8 GB of RAM"))
    rows = dict(status.hardware_rows(fake))
    assert rows["GPU"] == "None found: Red runs on the CPU"
    assert rows["VRAM"] == "None detected"


# --- audio -------------------------------------------------------------------------

def test_audio_page_lists_microphones_and_keeps_the_saved_one(app, settings):
    window = make_window(replace(settings, mic_device="2"))
    combo = window.audio_page.device_combo
    assert combo.itemText(0) == "System default"
    assert combo.currentData() == "2"
    assert combo.itemText(combo.findData("0")) == "Built-in Mic"


def test_audio_page_keeps_a_microphone_name_from_the_env(app, settings):
    window = make_window(replace(settings, mic_device="Blue Yeti"))
    combo = window.audio_page.device_combo
    assert combo.currentData() == "Blue Yeti"
    assert "from .env" in combo.currentText()


def test_the_meter_follows_the_microphone(app, settings):
    window = make_window(settings)
    page = window.audio_page
    page.audio_test.click()
    monitor = FakeMonitor.instances[-1]
    assert monitor.started and page.audio_test.text() == "Stop"
    monitor.on_level(0.42)
    assert page.meter.level == pytest.approx(0.42)
    assert page.level_label.text() == "Level: 42%"
    page.audio_test.click()
    assert monitor.stopped and page.audio_test.text() == "Test microphone"
    assert page.meter.level == 0.0


def test_a_busy_microphone_is_explained(app, settings):
    def busy(on_level, device):
        raise OSError("device busy")
    window = make_window(settings, monitor_factory=busy)
    window.audio_page.audio_test.click()
    assert "device busy" in window.audio_page.error.text()
    assert window.audio_page.audio_test.text() == "Test microphone"


def test_audio_values_save_the_selected_device(app, settings):
    window = make_window(settings)
    page = window.audio_page
    assert page.values() == {"RED_MIC_DEVICE": ""}
    page.device_combo.setCurrentIndex(page.device_combo.findData("2"))
    assert page.values() == {"RED_MIC_DEVICE": "2"}


def test_the_real_monitor_scales_and_closes_the_stream():
    levels, calls = [], []
    stream = SimpleNamespace(stop=lambda: calls.append("stop"),
                             close=lambda: calls.append("close"))
    monitor = pages.MicLevelMonitor(
        levels.append, stream_factory=lambda cb, device, rate, block: stream)
    monitor.start()
    monitor._callback(np.full((1600, 1), 0.1, dtype=np.float32), 1600, None, None)
    assert levels[0] == pytest.approx(0.8)
    monitor.stop()
    assert calls == ["stop", "close"]


# --- voice -------------------------------------------------------------------------

def test_voice_page_starts_on_kokoro_af_heart(app, settings):
    page = pages.VoiceSettingsPage(settings)
    assert page.engine.currentData() == "kokoro"
    assert page.voice.currentData() == "af_heart"
    assert page.voice.count() == len(VOICES)
    assert page.speed.value() == 100
    assert page.speed_label.text() == "1.00×"


def test_each_engine_remembers_its_own_voice(app, settings):
    page = pages.VoiceSettingsPage(settings)
    page.voice.setCurrentIndex(page.voice.findData("af_bella"))
    page.engine.setCurrentIndex(page.engine.findData("piper"))
    assert {page.voice.itemData(i) for i in range(page.voice.count())} == set(PIPER_VOICES)
    page.voice.setCurrentIndex(page.voice.findData("en_US-amy-medium"))
    page.engine.setCurrentIndex(page.engine.findData("kokoro"))
    assert page.voice.currentData() == "af_bella"
    values = page.values()
    assert values["RED_VOICE"] == "af_bella"
    assert values["RED_PIPER_VOICE"] == "en_US-amy-medium"
    page.engine.setCurrentIndex(page.engine.findData("piper"))
    assert page.voice.currentData() == "en_US-amy-medium"


def test_piper_is_remembered_as_the_engine_and_voice(app, settings):
    page = pages.VoiceSettingsPage(settings)
    page.engine.setCurrentIndex(page.engine.findData("piper"))
    page.voice.setCurrentIndex(page.voice.findData("en_US-lessac-medium"))
    assert page.values()["RED_TTS"] == "piper"
    assert page.values()["RED_VOICE_SPEED"] == "1.00"


def test_speed_slider_covers_its_whole_range(app, settings):
    page = pages.VoiceSettingsPage(replace(settings, voice_speed=1.2))
    assert page.speed.value() == 120 and page.speed_label.text() == "1.20×"
    page.speed.setValue(70)
    assert page.values()["RED_VOICE_SPEED"] == "0.70"
    page.speed.setValue(150)
    assert page.values()["RED_VOICE_SPEED"] == "1.50"


# --- general -----------------------------------------------------------------------

def test_general_page_shows_the_hotkey_and_overlay(app, settings):
    page = pages.GeneralSettingsPage(settings)
    assert page.hotkey.text() == "Ctrl+Alt+R"
    assert page.overlay.currentData() == "glow"
    page.hotkey.setText("Ctrl+Shift+R")
    page.overlay.setCurrentIndex(page.overlay.findData("card"))
    assert page.values() == {"RED_HOTKEY": "Ctrl+Shift+R", "RED_OVERLAY": "card"}


def test_no_hotkey_shows_as_off(app, settings):
    page = pages.GeneralSettingsPage(replace(settings, hotkey=None))
    assert page.hotkey.text() == "off"
    assert page.values()["RED_HOTKEY"] == "off"


# --- saving ------------------------------------------------------------------------

ENV = """# My own notes
RED_LLM_MODEL=my-model

# Voice
RED_HOTKEY=<ctrl>+<alt>+r
RED_OVERLAY=glow
RED_TTS=kokoro
RED_VOICE=af_heart
RED_PIPER_VOICE=en_US-lessac-medium
RED_VOICE_SPEED=1.0
RED_MIC_DEVICE=
"""


def test_save_changes_only_what_the_app_owns(app, settings):
    settings.config_dir.mkdir(parents=True)
    env = settings.config_dir / ".env"
    env.write_text(ENV, encoding="utf-8")
    window = make_window(settings)
    window.voice_page.engine.setCurrentIndex(window.voice_page.engine.findData("piper"))
    window.voice_page.voice.setCurrentIndex(
        window.voice_page.voice.findData("en_US-amy-medium"))
    window.voice_page.speed.setValue(125)
    window.general_page.hotkey.setText("Ctrl+Shift+R")
    window.general_page.overlay.setCurrentIndex(window.general_page.overlay.findData("card"))
    window.audio_page.device_combo.setCurrentIndex(window.audio_page.device_combo.findData("2"))

    assert window.save() is True
    assert window.status.text().startswith("Saved to")
    text = env.read_text(encoding="utf-8")
    assert "# My own notes" in text and "RED_LLM_MODEL=my-model" in text
    assert "RED_HOTKEY=<ctrl>+<shift>+r" in text            # pynput's form, as Red reads it
    assert "RED_OVERLAY=card" in text
    assert "RED_TTS=piper" in text
    assert "RED_VOICE=af_bella" not in text
    assert "RED_VOICE=af_heart" in text
    assert "RED_PIPER_VOICE=en_US-amy-medium" in text
    assert "RED_VOICE_SPEED=1.25" in text
    assert "RED_MIC_DEVICE=2" in text
    assert count_key(text, "RED_TTS") == 1                 # in place, everything else untouched


def count_key(text, key):
    return sum(1 for line in text.splitlines() if line.strip().startswith(f"{key}="))


def test_saving_twice_does_not_duplicate_keys(app, settings):
    settings.config_dir.mkdir(parents=True)
    env = settings.config_dir / ".env"
    window = make_window(settings)
    assert window.save() and window.save()
    text = env.read_text(encoding="utf-8")
    for key in ("RED_TTS", "RED_VOICE", "RED_PIPER_VOICE", "RED_VOICE_SPEED",
                "RED_HOTKEY", "RED_OVERLAY", "RED_MIC_DEVICE"):
        assert count_key(text, key) == 1, key


def test_a_typo_in_the_hotkey_is_caught_before_saving(app, settings):
    saved = []
    window = make_window(settings, save=lambda s, v: saved.append(v) or s.config_dir / ".env")
    window.general_page.hotkey.setText("banana")
    assert window.save() is False
    assert saved == []
    assert "Invalid hotkey" in window.status.text()


def test_a_save_failure_is_explained(app, settings):
    def broken(_settings, _values):
        raise OSError("the disk is full")
    window = make_window(settings, save=broken)
    assert window.save() is False
    assert "the disk is full" in window.status.text()


def test_saving_the_first_time_starts_from_the_example(settings):
    path = env_file.save_values(settings, {"RED_TTS": "piper", "RED_VOICE": "af_heart"})
    text = path.read_text(encoding="utf-8")
    assert "Copy this file" in text
    assert "RED_TTS=piper" in text and count_key(text, "RED_TTS") == 1


# --- the .env writer ---------------------------------------------------------------

def test_update_env_keeps_comments_unmanaged_keys_and_line_endings():
    text = "A=1  # keep me\r\n# my note\r\nB=2\r\n"
    new = env_file.update_env(text, {"A": "x y", "C": "z"})
    assert new == ('A="x y"  # keep me\r\n# my note\r\nB=2\r\n\r\n'
                   "# --- Saved by the Red app ---\r\nC=z\r\n")


def test_a_value_with_a_hash_or_quote_is_quoted():
    updated = env_file.update_env("A=1\n", {"A": 'say "hi" # now'})
    assert updated.splitlines()[0] == 'A="say \\"hi\\" # now"'


def test_read_env_without_a_file(tmp_path):
    assert env_file.read_env(tmp_path / "nope.env") == ""


# --- the command line --------------------------------------------------------------

def test_python_m_red_app_opens_the_window(monkeypatch, tmp_path):
    from red import __main__ as cli
    from red import app as app_mod
    seen = []
    monkeypatch.setenv("RED_HOME", str(tmp_path))
    monkeypatch.setattr(app_mod, "main", lambda settings: seen.append(settings) or 0)
    assert cli.main(["app"]) == 0
    assert len(seen) == 1 and seen[0].home == tmp_path


def test_main_hands_the_window_to_run(app, settings, monkeypatch):
    from red import app as app_mod
    import red.app.main_window as main_window_mod
    created, shown = [], []

    class FakeWindow:
        def __init__(self, s):
            created.append(s)

        def show(self):
            shown.append(True)

    monkeypatch.setattr(main_window_mod, "MainWindow", FakeWindow)
    got = []
    assert app_mod.main(settings, run=lambda window: got.append(window) or 0) == 0
    assert created == [settings] and isinstance(got[0], FakeWindow) and shown == []
