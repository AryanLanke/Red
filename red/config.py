"""Settings and paths.

Every path Red uses comes from one root folder, RED_HOME. RED_HOME is read
from the environment (default: %LOCALAPPDATA%\\Red). Other settings are read
from the environment first, then from RED_HOME\\config\\.env.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

DEFAULT_MODEL = "qwen2.5-7b-instruct-q4_k_m"
GPU_CHOICES = ("auto", "cuda", "vulkan", "cpu")
BACKEND_CHOICES = ("auto", "ollama", "llama.cpp")
WHISPER_DEVICE_CHOICES = ("auto", "cuda", "cpu")

DEFAULT_HOTKEY = "<ctrl>+<alt>+r"
DEFAULT_WAKEWORD = "hey_red"
DEFAULT_WAKEWORD_THRESHOLD = 0.5
DEFAULT_WHISPER_MODEL = "small"
# CPU by default: on a 6 GB GPU, Whisper and the 7B model don't fit together.
DEFAULT_WHISPER_DEVICE = "cpu"
DEFAULT_PIPER_VOICE = "en_US-lessac-medium"
SEARCH_ENGINE_CHOICES = ("google", "bing", "duckduckgo")

# Values that turn the hotkey or the wake word off.
_OFF = {"0", "off", "none", "no", "false", "disabled"}


def red_home() -> Path:
    """Return the RED_HOME folder, without creating it."""
    explicit = os.environ.get("RED_HOME", "").strip()
    if explicit:
        return Path(explicit).expanduser()
    local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
    if local_app_data:
        return Path(local_app_data) / "Red"
    return Path.home() / ".red"


@dataclass(frozen=True)
class Settings:
    home: Path
    llm_url: str | None
    llm_model: str
    llm_backend: str
    llm_gpu: str
    llm_keep_alive: str
    github_token: str | None
    # Voice and UI. Defaults match the RED_* variables in .env.example.
    hotkey: str | None = DEFAULT_HOTKEY
    wakeword: str | None = DEFAULT_WAKEWORD
    wakeword_threshold: float = DEFAULT_WAKEWORD_THRESHOLD
    whisper_model: str = DEFAULT_WHISPER_MODEL
    whisper_device: str = DEFAULT_WHISPER_DEVICE
    piper_voice: str = DEFAULT_PIPER_VOICE
    mic_device: str | None = None
    music_dir: Path | None = None
    search_engine: str = "google"

    @property
    def bin_dir(self) -> Path:
        return self.home / "bin"

    @property
    def models_dir(self) -> Path:
        return self.home / "models"

    @property
    def cache_dir(self) -> Path:
        return self.home / "cache"

    @property
    def logs_dir(self) -> Path:
        return self.home / "logs"

    @property
    def config_dir(self) -> Path:
        return self.home / "config"

    @property
    def allowlist_path(self) -> Path:
        return self.config_dir / "allowlist.toml"

    @property
    def command_log_path(self) -> Path:
        return self.logs_dir / "commands.jsonl"

    @property
    def repos_path(self) -> Path:
        return self.config_dir / "repos.toml"

    @property
    def contacts_path(self) -> Path:
        return self.config_dir / "contacts.toml"

    def ensure_dirs(self) -> None:
        for d in (
            self.bin_dir / "llama.cpp",
            self.models_dir / "llm",
            self.models_dir / "whisper",
            self.models_dir / "piper",
            self.models_dir / "wakeword",
            self.cache_dir / "downloads",
            self.cache_dir / "huggingface",
            self.logs_dir,
            self.config_dir,
        ):
            d.mkdir(parents=True, exist_ok=True)


def _env(name: str) -> str | None:
    value = os.environ.get(name, "").strip()
    return value or None


def _switchable(name: str, default: str) -> str | None:
    """A setting that "off" (or "none", "0", ...) turns off. Unset means the default."""
    value = _env(name)
    if value is None:
        return default
    return None if value.lower() in _OFF else value


def load_settings(home: Path | None = None) -> Settings:
    """Load settings. Values already in the environment win over the .env file."""
    home = home or red_home()
    load_dotenv(home / "config" / ".env", override=False)

    gpu = (_env("RED_LLM_GPU") or "auto").lower()
    if gpu not in GPU_CHOICES:
        raise ValueError(f"RED_LLM_GPU must be one of {GPU_CHOICES}, got {gpu!r}")
    backend = (_env("RED_LLM_BACKEND") or "auto").lower()
    if backend not in BACKEND_CHOICES:
        raise ValueError(f"RED_LLM_BACKEND must be one of {BACKEND_CHOICES}, got {backend!r}")

    whisper_device = (_env("RED_WHISPER_DEVICE") or DEFAULT_WHISPER_DEVICE).lower()
    if whisper_device not in WHISPER_DEVICE_CHOICES:
        raise ValueError(f"RED_WHISPER_DEVICE must be one of {WHISPER_DEVICE_CHOICES}, "
                         f"got {whisper_device!r}")
    threshold_text = _env("RED_WAKEWORD_THRESHOLD") or str(DEFAULT_WAKEWORD_THRESHOLD)
    try:
        threshold = float(threshold_text)
    except ValueError:
        threshold = -1.0
    if not 0.0 < threshold < 1.0:
        raise ValueError(f"RED_WAKEWORD_THRESHOLD must be between 0 and 1, got {threshold_text!r}")
    music_dir = _env("RED_MUSIC_DIR")
    # Like web_search itself: an unknown engine means Google, not an error.
    engine = (_env("RED_SEARCH_ENGINE") or "google").lower()
    if engine not in SEARCH_ENGINE_CHOICES:
        engine = "google"

    # Keep model caches under RED_HOME for this process only.
    # This doesn't change any system or user environment variables.
    os.environ.setdefault("HF_HOME", str(home / "cache" / "huggingface"))

    return Settings(
        home=home,
        llm_url=_env("RED_LLM_URL"),
        llm_model=_env("RED_LLM_MODEL") or DEFAULT_MODEL,
        llm_backend=backend,
        llm_gpu=gpu,
        llm_keep_alive=_env("RED_LLM_KEEP_ALIVE") or "5m",
        github_token=_env("GITHUB_TOKEN"),
        hotkey=_switchable("RED_HOTKEY", DEFAULT_HOTKEY),
        wakeword=_switchable("RED_WAKEWORD", DEFAULT_WAKEWORD),
        wakeword_threshold=threshold,
        whisper_model=_env("RED_WHISPER_MODEL") or DEFAULT_WHISPER_MODEL,
        whisper_device=whisper_device,
        piper_voice=_env("RED_PIPER_VOICE") or DEFAULT_PIPER_VOICE,
        mic_device=_env("RED_MIC_DEVICE"),
        music_dir=Path(os.path.expandvars(music_dir)).expanduser() if music_dir else None,
        search_engine=engine,
    )
