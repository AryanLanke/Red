import os
from pathlib import Path

import pytest

from red.config import load_settings

VOICE_VARS = ("RED_HOTKEY", "RED_WAKEWORD", "RED_WAKEWORD_THRESHOLD", "RED_WHISPER_MODEL",
              "RED_WHISPER_DEVICE", "RED_PIPER_VOICE", "RED_MIC_DEVICE", "RED_MUSIC_DIR")


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in VOICE_VARS:
        monkeypatch.delenv(name, raising=False)
    yield
    for name in VOICE_VARS:  # load_dotenv puts .env values into os.environ
        os.environ.pop(name, None)


def test_voice_defaults(tmp_path):
    s = load_settings(tmp_path)
    assert s.hotkey == "<ctrl>+<alt>+r"
    assert s.wakeword == "hey_red"
    assert s.wakeword_threshold == 0.5
    assert s.whisper_model == "small" and s.whisper_device == "cpu"
    assert s.piper_voice == "en_US-lessac-medium"
    assert s.mic_device is None and s.music_dir is None
    assert s.repos_path == tmp_path / "config" / "repos.toml"
    assert s.allowlist_path == tmp_path / "config" / "allowlist.toml"
    assert s.command_log_path == tmp_path / "logs" / "commands.jsonl"


def test_voice_settings_from_env_file_and_env(tmp_path, monkeypatch):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / ".env").write_text(
        "RED_HOTKEY=Ctrl+Shift+Space\nRED_WAKEWORD=off\nRED_WHISPER_DEVICE=AUTO\n"
        "RED_MIC_DEVICE=USB\nRED_WAKEWORD_THRESHOLD=0.35\n", encoding="utf-8")
    monkeypatch.setenv("RED_MUSIC_DIR", str(tmp_path / "tunes"))
    s = load_settings(tmp_path)
    assert s.hotkey == "Ctrl+Shift+Space"
    assert s.wakeword is None
    assert s.whisper_device == "auto"
    assert s.mic_device == "USB"
    assert s.wakeword_threshold == 0.35
    assert s.music_dir == tmp_path / "tunes"


def test_empty_values_mean_defaults(tmp_path, monkeypatch):
    monkeypatch.setenv("RED_HOTKEY", "")
    monkeypatch.setenv("RED_WAKEWORD", " ")
    s = load_settings(tmp_path)
    assert s.hotkey == "<ctrl>+<alt>+r" and s.wakeword == "hey_red"


@pytest.mark.parametrize("name, value", [("RED_WHISPER_DEVICE", "tpu"),
                                         ("RED_WAKEWORD_THRESHOLD", "loud"),
                                         ("RED_WAKEWORD_THRESHOLD", "1.5")])
def test_bad_voice_values(tmp_path, monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    with pytest.raises(ValueError, match=name):
        load_settings(tmp_path)


def test_music_dir_uses_settings_then_known_folder(tmp_path, monkeypatch):
    from red.tools import music
    monkeypatch.setenv("RED_HOME", str(tmp_path))
    monkeypatch.setenv("RED_MUSIC_DIR", str(tmp_path / "tunes"))
    assert music.music_dir() == tmp_path / "tunes"
    monkeypatch.delenv("RED_MUSIC_DIR")
    monkeypatch.setattr("red.known_folders.known_folder",
                        lambda name: Path("X:/OneDrive/Music") if name == "music" else None)
    assert music.music_dir() == Path("X:/OneDrive/Music")
    monkeypatch.setattr("red.known_folders.known_folder", lambda name: None)
    assert music.music_dir() == Path.home() / "Music"


def test_repos_file_uses_settings(tmp_path, monkeypatch):
    from red.tools import git_sync
    monkeypatch.setenv("RED_HOME", str(tmp_path))
    assert git_sync.repos_file() == tmp_path / "config" / "repos.toml"


def test_search_engine_and_contacts_settings(tmp_path, monkeypatch):
    monkeypatch.delenv("RED_SEARCH_ENGINE", raising=False)
    s = load_settings(tmp_path)
    assert s.search_engine == "google"
    assert s.contacts_path == tmp_path / "config" / "contacts.toml"
    monkeypatch.setenv("RED_SEARCH_ENGINE", "DuckDuckGo")
    assert load_settings(tmp_path).search_engine == "duckduckgo"
    monkeypatch.setenv("RED_SEARCH_ENGINE", "altavista")
    assert load_settings(tmp_path).search_engine == "google"


def test_contacts_example_parses():
    from red.tools.mail import load_contacts
    example = Path(__file__).resolve().parent.parent / "contacts.example.toml"
    assert load_contacts(example) == {"mom": "mom@example.com"}


def test_tools_with_details_expose_last_details():
    from red.tools import default_registry
    registry = default_registry()
    for name in ("find_file", "check_repos"):
        assert getattr(registry.get(name), "last_details", None) == ""
