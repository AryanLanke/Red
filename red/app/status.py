"""What the Red app shows: this PC's hardware and which models are on disk.

Everything here only reads. Nothing is installed, downloaded or started, so
the app is safe to open at any time. Model checks are plain file checks (the
same pinned file names Red downloads), plus one short question to Ollama when
Red uses it.
"""

from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from red import hardware as _hardware
from red.config import Settings
from red.listener import FEATURE_MODELS, HEY_RED, WAKEWORDS, resolve_wakeword
from red.llm import MODELS
from red.stt import WHISPER_MODELS
from red.tts import PIPER_VOICES
from red.tts_kokoro import KOKORO_FILES
from red.wakeword import WAKE_WHISPER_MODEL

READY = "ready"
MISSING = "missing"
UNKNOWN = "unknown"
OFF = "off"

OLLAMA_URL = "http://127.0.0.1:11434"
SETUP_HINT = "run python -m red setup and it'll fetch it"


@dataclass(frozen=True)
class ModelRow:
    """One line on the Model Status page."""

    name: str
    state: str
    detail: str


def ollama_tags(url: str = OLLAMA_URL, timeout: float = 2.0) -> list[str]:
    """The model tags Ollama has, or raises when it isn't answering."""
    with urllib.request.urlopen(f"{url}/api/tags", timeout=timeout) as response:
        tags = json.load(response)
    return [str(model.get("name", "")) for model in tags.get("models", [])]


def hardware_rows(mod=_hardware) -> list[tuple[str, str]]:
    """(label, value) rows for the Hardware Check page."""
    gpu = mod.gpu_gb()
    ram = mod.ram_gb()
    choice = mod.detect()
    name = mod.gpu_name()
    if gpu is None:
        gpu_text = "None found: Red runs on the CPU" if not name else name
    else:
        gpu_text = name or "A GPU Red can use"
    return [
        ("CPU", mod.cpu_name()),
        ("GPU", gpu_text),
        ("VRAM", f"{gpu:.1f} GB" if gpu else "None detected"),
        ("RAM", f"{ram:.0f} GB" if ram else "Couldn't read it"),
        ("Red's pick", f"{choice.model} with Whisper {choice.whisper_model} ({choice.why})"),
    ]


def llm_row(settings: Settings, tags: Callable[[], list[str]] = ollama_tags) -> ModelRow:
    name = f"Language model ({settings.llm_model})"
    if settings.llm_url:
        return ModelRow(name, UNKNOWN, f"Using your own server at {settings.llm_url}.")
    try:
        installed = tags()
    except Exception:  # noqa: BLE001 - any failure means it isn't answering
        return ModelRow(name, MISSING, "Ollama isn't answering. Red starts it when it needs it.")
    spec = MODELS.get(settings.llm_model)
    wanted = {settings.llm_model} | ({spec.ollama_tag} if spec else set())
    if wanted & set(installed):
        return ModelRow(name, READY, f"{spec.ollama_tag if spec else settings.llm_model} is installed.")
    return ModelRow(name, MISSING, f"Not downloaded yet: {SETUP_HINT}.")


def whisper_row(settings: Settings) -> ModelRow:
    folder = settings.models_dir / "whisper" / settings.whisper_model
    pinned = WHISPER_MODELS.get(settings.whisper_model)
    ready = pinned.present(folder) if pinned else any(folder.glob("*.bin"))
    name = f"Whisper ({settings.whisper_model}, {settings.whisper_device})"
    detail = "Here, ready to hear you." if ready else f"Not here yet: {SETUP_HINT}."
    return ModelRow(name, READY if ready else MISSING, detail)


def kokoro_row(settings: Settings) -> ModelRow:
    ready = KOKORO_FILES.present(settings.models_dir / "kokoro")
    role = ("Red's default voice." if settings.tts == "kokoro"
            else "The fallback if Kokoro's files go missing.")
    detail = f"{role} Installed." if ready else f"{role} Not here yet: {SETUP_HINT}."
    return ModelRow("Kokoro voice (natural)", READY if ready else MISSING, detail)


def piper_row(settings: Settings) -> ModelRow:
    folder = settings.models_dir / "piper"
    pinned = PIPER_VOICES.get(settings.piper_voice)
    ready = pinned.present(folder) if pinned else (folder / f"{settings.piper_voice}.onnx").is_file()
    name = f"Piper voice ({settings.piper_voice})"
    detail = "Here as a backup voice." if ready else f"Not here yet: {SETUP_HINT}."
    return ModelRow(name, READY if ready else MISSING, detail)


def wakeword_row(settings: Settings) -> ModelRow:
    wake = settings.wakeword
    if not wake:
        return ModelRow("Wake word", OFF, "Off: the hotkey still starts Red.")
    try:
        key = resolve_wakeword(wake)
    except ValueError as e:
        return ModelRow(f"Wake word ({wake})", MISSING, str(e))
    if key.lower().endswith(".onnx"):
        ready = Path(key).is_file()
    elif key == HEY_RED:
        ready = WHISPER_MODELS[WAKE_WHISPER_MODEL].present(
            settings.models_dir / "whisper" / WAKE_WHISPER_MODEL)
    else:
        ready = (FEATURE_MODELS.present(settings.models_dir / "wakeword")
                 and (settings.models_dir / "wakeword" / WAKEWORDS[key].filename).is_file())
    name = f'Wake word ("{key.replace("_", " ").title()}")'
    detail = "Say it and Red listens." if ready else f"Not here yet: {SETUP_HINT}."
    return ModelRow(name, READY if ready else MISSING, detail)


def model_rows(settings: Settings,
               tags: Callable[[], list[str]] = ollama_tags) -> list[ModelRow]:
    """Every model Red uses, in the order the Model Status page lists them."""
    return [llm_row(settings, tags), whisper_row(settings), kokoro_row(settings),
            piper_row(settings), wakeword_row(settings)]
