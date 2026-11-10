"""red.hardware and the setup step that picks a model. Nothing real is queried or written outside tmp."""

import subprocess

import pytest

from red import __main__ as cli
from red import hardware as h
from red.config import load_settings
from red.llm import MODELS


@pytest.mark.parametrize("gpu, ram, model, whisper, device", [
    (None, 8.0, "qwen2.5-3b-instruct-q4_k_m", "base.en", "cpu"),     # no GPU, 8 GB RAM
    (None, 15.3, "qwen2.5-3b-instruct-q4_k_m", "base.en", "cpu"),    # no GPU, "16 GB"
    (0.5, 15.3, "qwen2.5-3b-instruct-q4_k_m", "base.en", "cpu"),     # integrated graphics
    (4.0, 16.0, "qwen3.5-4b", "base.en", "cpu"),          # RTX 3050 laptop
    (6.0, 15.2, "qwen3.5-4b", "base.en", "cpu"),          # this PC: RTX 4050 6 GB
    (7.99, 32.0, "qwen3.5-9b", "small.en", "cuda"),       # "8 GB"
    (12.0, 32.0, "qwen3.5-9b", "small.en", "cuda"),
    (None, None, "qwen3.5-4b", "base.en", "cpu"),          # unknown: the middle choice
])
def test_recommend(gpu, ram, model, whisper, device):
    choice = h.recommend(gpu, ram)
    assert (choice.model, choice.whisper_model, choice.whisper_device) == (model, whisper, device)
    assert choice.model in MODELS


def test_nvidia_smi_is_read_in_gigabytes():
    def run(argv, **kw):
        assert argv[1:] == ["--query-gpu=memory.total", "--format=csv,noheader,nounits"]
        return subprocess.CompletedProcess(argv, 0, stdout="6141\n2048\n", stderr="")
    assert h.nvidia_gpu_gb(run=run, which=lambda name: "C:\\nvidia-smi.exe") == pytest.approx(5.997, 0.01)


def test_no_nvidia_smi():
    assert h.nvidia_gpu_gb(run=None, which=lambda name: None) is None

    def broken(argv, **kw):
        return subprocess.CompletedProcess(argv, 9, stdout="", stderr="no devices")
    assert h.nvidia_gpu_gb(run=broken, which=lambda name: "nvidia-smi") is None


def test_with_settings_changes_only_those_lines():
    text = "# RED_LLM_MODEL=old\nRED_LLM_MODEL=qwen2.5-7b\nRED_WHISPER_MODEL=small\nOTHER=1\n"
    assert cli.with_settings(text, {"RED_LLM_MODEL": "qwen3.5-4b", "RED_WHISPER_MODEL": "base.en"}) == (
        "# RED_LLM_MODEL=old\nRED_LLM_MODEL=qwen3.5-4b\nRED_WHISPER_MODEL=base.en\nOTHER=1\n")


@pytest.fixture
def clean_env(monkeypatch):
    for name in ("RED_LLM_MODEL", "RED_WHISPER_MODEL", "RED_WHISPER_DEVICE"):
        monkeypatch.delenv(name, raising=False)
    yield
    import os
    for name in ("RED_LLM_MODEL", "RED_WHISPER_MODEL", "RED_WHISPER_DEVICE"):
        os.environ.pop(name, None)      # load_dotenv puts .env values into os.environ


def test_setup_writes_a_new_env_with_the_pick(tmp_path, clean_env, capsys):
    settings = load_settings(tmp_path)
    settings.ensure_dirs()
    pick = h.Choice("qwen3.5-9b", "small.en", "cuda", "a 12 GB GPU")
    after = cli._setup_model(settings, detect=lambda: pick)
    env = (tmp_path / "config" / ".env").read_text(encoding="utf-8")
    assert "RED_LLM_MODEL=qwen3.5-9b" in env and "RED_WHISPER_DEVICE=cuda" in env
    assert after.llm_model == "qwen3.5-9b" and after.whisper_model == "small.en"
    assert "a 12 GB GPU" in capsys.readouterr().out


def test_setup_never_changes_an_existing_env(tmp_path, clean_env, capsys):
    (tmp_path / "config").mkdir()
    env = tmp_path / "config" / ".env"
    env.write_text("RED_LLM_MODEL=qwen2.5-7b-instruct-q4_k_m\n", encoding="utf-8")
    settings = load_settings(tmp_path)
    pick = h.Choice("qwen3.5-4b", "base.en", "cpu", "a 6 GB GPU")
    assert cli._setup_model(settings, detect=lambda: pick) is settings
    assert env.read_text(encoding="utf-8") == "RED_LLM_MODEL=qwen2.5-7b-instruct-q4_k_m\n"
    assert "RED_LLM_MODEL=qwen3.5-4b" in capsys.readouterr().out


# --- names for the settings app ----------------------------------------------------

def test_cpu_name_comes_from_windows():
    assert h.cpu_name({"PROCESSOR_IDENTIFIER": "AMD64 Family 25 Model 68, AuthenticAMD"}) == \
        "AMD64 Family 25 Model 68, AuthenticAMD"
    assert h.cpu_name({})                      # the platform's answer, never empty


def test_gpu_name_reads_nvidia_smi():
    def run(argv, **kw):
        assert argv[1:] == ["--query-gpu=name", "--format=csv,noheader"]
        return subprocess.CompletedProcess(argv, 0, stdout="NVIDIA GeForce RTX 4050\n", stderr="")
    assert h.gpu_name(run=run, which=lambda name: "nvidia-smi",
                      names=lambda: pytest.fail("the driver is only a backup")) == \
        "NVIDIA GeForce RTX 4050"


def test_gpu_name_falls_back_to_the_display_driver():
    assert h.gpu_name(run=None, which=lambda name: None,
                      names=lambda: ["Intel(R) UHD Graphics", "Intel(R) UHD Graphics"]) == \
        "Intel(R) UHD Graphics"
    assert h.gpu_name(run=None, which=lambda name: None, names=lambda: []) is None
