import hashlib
import zipfile

import pytest

from red.config import load_settings, red_home
from red.downloads import DownloadError, download, safe_extract


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in ("RED_HOME", "RED_LLM_URL", "RED_LLM_MODEL", "RED_LLM_GPU",
                 "RED_LLM_BACKEND", "RED_LLM_KEEP_ALIVE", "GITHUB_TOKEN"):
        monkeypatch.delenv(name, raising=False)


def test_red_home_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("RED_HOME", str(tmp_path))
    assert red_home() == tmp_path


def test_red_home_default_under_localappdata(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert red_home() == tmp_path / "Red"


def test_env_file_loaded_but_environment_wins(monkeypatch, tmp_path):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / ".env").write_text(
        "RED_LLM_MODEL=from-file\nRED_LLM_GPU=cpu\n")
    monkeypatch.setenv("RED_LLM_GPU", "vulkan")
    s = load_settings(tmp_path)
    assert s.llm_model == "from-file"
    assert s.llm_gpu == "vulkan"
    assert s.llm_url is None


def test_bad_gpu_value(monkeypatch, tmp_path):
    monkeypatch.setenv("RED_LLM_GPU", "tpu")
    with pytest.raises(ValueError):
        load_settings(tmp_path)


def test_backend_defaults_and_validation(monkeypatch, tmp_path):
    s = load_settings(tmp_path)
    assert s.llm_backend == "auto" and s.llm_keep_alive == "5m"
    monkeypatch.setenv("RED_LLM_BACKEND", "magic")
    with pytest.raises(ValueError):
        load_settings(tmp_path)


def test_download_verifies_checksum(tmp_path):
    src = tmp_path / "src.bin"
    src.write_bytes(b"hello red")
    good = hashlib.sha256(b"hello red").hexdigest()

    dest = download(src.as_uri(), tmp_path / "out" / "a.bin", good)
    assert dest.read_bytes() == b"hello red"

    bad_dest = tmp_path / "out" / "b.bin"
    with pytest.raises(DownloadError):
        download(src.as_uri(), bad_dest, "0" * 64)
    assert not bad_dest.exists()
    assert not bad_dest.with_name("b.bin.part").exists()


def test_safe_extract_blocks_path_traversal(tmp_path):
    z = tmp_path / "evil.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("../escape.txt", "x")
    with pytest.raises(DownloadError):
        safe_extract(z, tmp_path / "target")
    assert not (tmp_path / "escape.txt").exists()
