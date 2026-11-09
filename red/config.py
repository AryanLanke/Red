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
# How Red shows what it's doing: a glow around the screen edges, the small
# corner card, Windows notifications, or nothing.
OVERLAY_CHOICES = ("glow", "card", "notify", "off")
DEFAULT_OVERLAY = "glow"
# Natural pauses mid-sentence run up to about a second, so wait longer than
# that before deciding you've finished.
DEFAULT_END_SILENCE = 1.5      # seconds of quiet that end a command
DEFAULT_MAX_COMMAND = 20.0     # seconds; a command is cut off after this
# After an answer, Red asks if you want anything else and listens this long
# for a reply. 0 turns follow-ups off.
DEFAULT_FOLLOW_UP = 7.0

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
    overlay: str = DEFAULT_OVERLAY
    end_silence_seconds: float = DEFAULT_END_SILENCE
    max_command_seconds: float = DEFAULT_MAX_COMMAND
    follow_up_seconds: float = DEFAULT_FOLLOW_UP

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
    overlay = (_env("RED_OVERLAY") or DEFAULT_OVERLAY).lower()
    if overlay not in OVERLAY_CHOICES:
        raise ValueError(f"RED_OVERLAY must be one of {OVERLAY_CHOICES}, got {overlay!r}")
    end_silence = _seconds("RED_END_SILENCE", DEFAULT_END_SILENCE, 0.3, 5.0)
    max_command = _seconds("RED_MAX_COMMAND_SECONDS", DEFAULT_MAX_COMMAND, 3.0, 120.0)
    follow_up = _seconds("RED_FOLLOW_UP_SECONDS", DEFAULT_FOLLOW_UP, 0.0, 30.0)

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
        overlay=overlay,
        end_silence_seconds=end_silence,
        max_command_seconds=max_command,
        follow_up_seconds=follow_up,
    )


def _seconds(name: str, default: float, low: float, high: float) -> float:
    """A number of seconds between low and high. Unset means the default."""
    text = _env(name)
    if text is None:
        return default
    try:
        value = float(text)
    except ValueError:
        value = float("nan")
    if not low <= value <= high:
        raise ValueError(f"{name} must be a number of seconds from {low:g} to {high:g}, got {text!r}")
    return value
