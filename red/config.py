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
    )
