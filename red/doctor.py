"""python -m red doctor: check that everything Red needs is in place.

Every check only looks. It never starts Ollama, records sound, plays sound,
downloads anything or changes a file. Each result is OK, WARN or FAIL, with
a fix when something is wrong.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

OK, WARN, FAIL = "ok", "warn", "fail"
_ICONS = {OK: "✅", WARN: "⚠️ ", FAIL: "❌"}
_PLAIN = {OK: "[ok]  ", WARN: "[warn]", FAIL: "[FAIL]"}

PACKAGES = {
    "core": ("jsonschema", "dotenv"),
    "voice": ("numpy", "sounddevice", "faster_whisper", "ctranslate2", "piper", "onnxruntime",
              "openwakeword", "pynput"),
    "ui": ("PySide6",),
}
INSTALL_FIX = "pip install -r requirements.txt (in Red's venv)"


@dataclass
class Check:
    status: str
    title: str
    fix: str = ""


@dataclass
class System:
    """Everything the checks touch, so tests can replace it."""

    find_spec: Callable[[str], object] = importlib.util.find_spec
    http_json: Callable[[str, float], object] = None          # (url, timeout) -> parsed JSON
    run: Callable[..., subprocess.CompletedProcess] = subprocess.run
    sounddevice: Callable[[], object] = None                  # () -> the sounddevice module
    version: tuple = field(default_factory=lambda: tuple(sys.version_info[:3]))
    platform: str = sys.platform
    environ: dict = field(default_factory=lambda: os.environ)

    def __post_init__(self):
        if self.http_json is None:
            self.http_json = _http_json
        if self.sounddevice is None:
            self.sounddevice = _import_sounddevice


def _http_json(url: str, timeout: float):
    with urllib.request.urlopen(url, timeout=timeout) as r:  # noqa: S310 - fixed local URLs
        return json.loads(r.read().decode("utf-8") or "null")


def _import_sounddevice():
    import sounddevice
    return sounddevice


# --------------------------------------------------------------------------
# Checks
# --------------------------------------------------------------------------

def check_python(sys_: System) -> list[Check]:
    v = ".".join(map(str, sys_.version))
    out = [Check(OK, f"Python {v}") if sys_.version >= (3, 11)
           else Check(FAIL, f"Python {v} is too old", "Install Python 3.11 or newer")]
    if sys_.platform != "win32":
        out.append(Check(WARN, f"Running on {sys_.platform}", "Red is built for Windows 11"))
    return out


def check_packages(sys_: System) -> list[Check]:
    out = []
    for group, names in PACKAGES.items():
        missing = [n for n in names if _has(sys_, n) is False]
        label = {"core": "Core packages", "voice": "Voice packages", "ui": "Overlay packages"}[group]
        if not missing:
            out.append(Check(OK, label))
        else:
            status = FAIL if group == "core" else WARN
            what = {"core": "Red can't run",
                    "voice": "only typed mode works (python -m red --typed)",
                    "ui": "no status window (Windows notifications instead)"}[group]
            out.append(Check(status, f"{label} missing: {', '.join(missing)}; {what}", INSTALL_FIX))
    return out


def _has(sys_: System, name: str) -> bool:
    try:
        return sys_.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def check_home(settings, sys_: System) -> list[Check]:
    home = settings.home
    source = "from RED_HOME" if sys_.environ.get("RED_HOME", "").strip() else "default"
    if not home.exists():
        return [Check(FAIL, f"RED_HOME {home} ({source}) doesn't exist", "python -m red setup")]
    if not os.access(home, os.W_OK):
        return [Check(FAIL, f"RED_HOME {home} isn't writable", "Choose a folder you can write to")]
    out = [Check(OK, f"RED_HOME is {home} ({source})")]
    if not (settings.config_dir / ".env").is_file():
        out.append(Check(WARN, "No settings file, so the defaults are used",
                         f"Copy .env.example to {settings.config_dir / '.env'}"))
    return out


def check_llm(settings, sys_: System) -> list[Check]:
    from .llm import OLLAMA_DEFAULT_URL, OLLAMA_VERSION, _model_spec

    if settings.llm_url:
        url = settings.llm_url.rstrip("/") + "/models"
        try:
            sys_.http_json(url, 3.0)
            return [Check(OK, f"Your LLM server answers at {settings.llm_url}")]
        except Exception as e:  # noqa: BLE001
            return [Check(FAIL, f"Your LLM server at {settings.llm_url} doesn't answer ({e})",
                          "Start it, or clear RED_LLM_URL to use Red's own Ollama")]
    try:
        tag = _model_spec(settings.llm_model).ollama_tag
    except Exception as e:  # noqa: BLE001
        return [Check(FAIL, f"Unknown model {settings.llm_model!r} ({e})", "Fix RED_LLM_MODEL in .env")]

    try:
        tags = sys_.http_json(f"{OLLAMA_DEFAULT_URL}/api/tags", 3.0) or {}
    except Exception:  # noqa: BLE001 - nothing running is normal
        tags = None
    if tags is not None:
        names = {m.get("name") for m in tags.get("models", []) if isinstance(m, dict)}
        if tag in names:
            return [Check(OK, f"Ollama is running and has the model {tag}")]
        return [Check(FAIL, f"Ollama is running but doesn't have the model {tag}",
                      "python -m red setup")]

    installed = (settings.bin_dir / "ollama" / OLLAMA_VERSION / ".installed").is_file()
    name, _, version = tag.partition(":")
    manifest = (settings.models_dir / "ollama" / "manifests" / "registry.ollama.ai" / "library"
                / name / version)
    if installed and manifest.is_file():
        return [Check(OK, f"Ollama {OLLAMA_VERSION} and the model {tag} are installed "
                          "(Red starts Ollama when it runs)")]
    missing = [] if installed else [f"Ollama {OLLAMA_VERSION}"]
    if not manifest.is_file():
        missing.append(f"the model {tag}")
    return [Check(FAIL, f"Not downloaded yet: {' and '.join(missing)}", "python -m red setup")]


def check_gpu(settings, sys_: System) -> list[Check]:
    try:
        r = sys_.run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
                     capture_output=True, text=True, timeout=10,
                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        line = (r.stdout or "").strip().splitlines()[0] if r.returncode == 0 and r.stdout else ""
    except (OSError, subprocess.SubprocessError, IndexError):
        line = ""
    if line:
        return [Check(OK, f"NVIDIA GPU: {line}")]
    out = [Check(WARN, "No NVIDIA GPU found, so the language model runs on the CPU (slower)",
                 "On a PC without a GPU, set RED_LLM_MODEL=qwen2.5-3b-instruct-q4_k_m")]
    if settings.whisper_device == "cuda":
        out.append(Check(WARN, "RED_WHISPER_DEVICE is cuda, but there's no NVIDIA GPU",
                         "Set RED_WHISPER_DEVICE=cpu"))
    return out


def check_audio(settings, sys_: System) -> list[Check]:
    try:
        sd = sys_.sounddevice()
    except Exception:  # noqa: BLE001 - reported by check_packages
        return [Check(WARN, "Can't check the microphone or speakers without the voice packages",
                      INSTALL_FIX)]
    out = []
    mic = settings.mic_device
    device = int(mic) if mic and mic.isdigit() else mic
    try:
        info = sd.query_devices(device, kind="input")
        # Open the microphone and close it again. Nothing is recorded.
        stream = sd.InputStream(device=device, channels=1)
        stream.close()
        out.append(Check(OK, f"Microphone: {info['name']}"))
    except Exception as e:  # noqa: BLE001
        out.append(Check(FAIL, f"Can't open the microphone ({e})",
                         "Allow microphone access in Settings > Privacy & security > Microphone, "
                         "or set RED_MIC_DEVICE to part of your microphone's name"))
    try:
        info = sd.query_devices(None, kind="output")
        out.append(Check(OK, f"Speakers: {info['name']}"))
    except Exception as e:  # noqa: BLE001
        out.append(Check(FAIL, f"No speakers found ({e})", "Connect speakers or headphones"))
    return out


def check_voice_models(settings, sys_: System) -> list[Check]:
    if not all(_has(sys_, n) for n in ("numpy", "faster_whisper", "piper")):
        return []          # check_packages already said what's missing
    out = []
    try:
        from .stt import WHISPER_MODELS
        files = WHISPER_MODELS.get(settings.whisper_model)
        folder = settings.models_dir / "whisper" / settings.whisper_model
        if files is None:
            out.append(Check(FAIL, f"Unknown Whisper model {settings.whisper_model!r}",
                             "Set RED_WHISPER_MODEL=small"))
        elif files.present(folder):
            out.append(Check(OK, f"Whisper {settings.whisper_model} model "
                                 f"(runs on {settings.whisper_device})"))
        else:
            out.append(Check(FAIL, "The Whisper model isn't downloaded", "python -m red setup"))
    except Exception as e:  # noqa: BLE001
        out.append(Check(WARN, f"Couldn't check the Whisper model ({e})"))
    try:
        from .tts import Speaker
        path = Speaker(settings.models_dir / "piper", settings.piper_voice).model_path
        if path.is_file():
            out.append(Check(OK, f"Piper voice {settings.piper_voice}"))
        else:
            out.append(Check(FAIL, f"The Piper voice {settings.piper_voice} isn't downloaded",
                             "python -m red setup"))
    except Exception as e:  # noqa: BLE001
        out.append(Check(WARN, f"Couldn't check the Piper voice ({e})"))
    return out


def check_triggers(settings, sys_: System) -> list[Check]:
    if not _has(sys_, "numpy"):
        return []
    out = []
    try:
        from . import listener
    except Exception as e:  # noqa: BLE001
        return [Check(WARN, f"Couldn't check the hotkey and wake word ({e})", INSTALL_FIX)]
    if settings.hotkey:
        try:
            listener.normalize_hotkey(settings.hotkey)
            pretty = "+".join(k.strip("<>").capitalize() if len(k.strip("<>")) > 1 else k.upper()
                              for k in settings.hotkey.split("+"))
            out.append(Check(OK, f"Hotkey {pretty}"))
        except ValueError as e:
            out.append(Check(FAIL, str(e), "Fix RED_HOTKEY in .env, for example Ctrl+Alt+R"))
    else:
        out.append(Check(WARN, "The hotkey is off (RED_HOTKEY=off)"))
    if not settings.wakeword:
        out.append(Check(WARN if not settings.hotkey else OK, "The wake word is off (hotkey only)"))
        return out
    try:
        key = listener.resolve_wakeword(settings.wakeword)
    except Exception:  # noqa: BLE001 - the message can name other models; keep it out
        out.append(Check(WARN, f"The wake word {settings.wakeword!r} isn't available in this "
                               "version, so Red uses the hotkey only",
                         "Update Red, or set RED_WAKEWORD=off to hide this"))
        return out
    model_dir = settings.models_dir / "wakeword"
    if str(key).lower().endswith(".onnx"):
        ok = Path(key).is_file()
    else:
        asset = getattr(listener, "WAKEWORDS", {}).get(key)
        features = getattr(listener, "FEATURE_MODELS", None)
        ok = (asset is None or (model_dir / asset.filename).is_file()) and \
            (features is None or features.present(model_dir))
    out.append(Check(OK, f"Wake word {settings.wakeword}") if ok
               else Check(FAIL, f"The wake word model for {settings.wakeword} isn't downloaded",
                          "python -m red setup"))
    return out


def check_config_files(settings, sys_: System) -> list[Check]:
    from .allowlist import load_allowlist

    out = []
    files = (
        ("allowlist.toml", settings.allowlist_path, "only the built-in folders and apps",
         lambda p: load_allowlist(p)),
        ("repos.toml", settings.repos_path, "\"check my repos\" has no repos to check",
         _load_repos),
        ("contacts.toml", settings.contacts_path, "mail drafts need a full email address",
         _load_contacts),
    )
    for name, path, without, load in files:
        if not path.is_file():
            out.append(Check(WARN, f"{name} isn't set up, so {without}",
                             f"Run python -m red setup, then edit {path}"))
            continue
        try:
            load(path)
            out.append(Check(OK, f"{name}"))
        except Exception as e:  # noqa: BLE001 - each loader raises its own error type
            out.append(Check(FAIL, f"{name} has a problem: {e}", f"Fix {path}"))
    return out


def _load_repos(path: Path):
    from .tools.git_sync import load_repos
    return load_repos(path)


def _load_contacts(path: Path):
    from .tools.mail import load_contacts
    return load_contacts(path)


# --------------------------------------------------------------------------
# Running
# --------------------------------------------------------------------------

def check_web_search(settings, sys_: System) -> list[Check]:
    """Red's own SearXNG (red/searxng.py): installed, off, or someone else's."""
    if not settings.web_search:
        return [Check(OK, "Web search is off (RED_WEB_SEARCH=off): answers use Wikipedia only")]
    if settings.search_url:
        return [Check(OK, f"Web search uses your own SearXNG at {settings.search_url}")]
    from .searxng import installed
    if installed(settings):
        return [Check(OK, "Web search (SearXNG) is installed; Red starts it when it starts "
                          "(its log is logs\\searxng.log)")]
    return [Check(WARN, "Web search isn't installed, so answers use Wikipedia only",
                  "python -m red setup")]


def run_checks(sys_: System | None = None, settings=None) -> list[Check]:
    sys_ = sys_ or System()
    out = check_python(sys_) + check_packages(sys_)
    if settings is None:
        from .config import load_settings
        try:
            settings = load_settings()
        except ValueError as e:
            return out + [Check(FAIL, f"A setting is wrong: {e}", "Fix it in RED_HOME\\config\\.env")]
    for check in (check_home, check_llm, check_gpu, check_audio, check_voice_models,
                  check_triggers, check_config_files, check_web_search):
        try:
            out += check(settings, sys_)
        except Exception as e:  # noqa: BLE001 - one broken check must not hide the others
            out.append(Check(WARN, f"{check.__name__} couldn't run: {e}"))
    return out


def _can_print(text: str, stream) -> bool:
    try:
        text.encode(getattr(stream, "encoding", None) or "ascii")
        return True
    except (UnicodeEncodeError, LookupError):
        return False


def report(checks: list[Check], out=None) -> int:
    """Print the checks. Returns 1 if anything failed, else 0."""
    out = out or sys.stdout
    icons = _ICONS if _can_print("".join(_ICONS.values()), out) else _PLAIN
    for c in checks:
        print(f"{icons[c.status]} {c.title}", file=out)
        if c.fix and c.status != OK:
            print(f"     Fix: {c.fix}", file=out)
    fails = sum(c.status == FAIL for c in checks)
    warns = sum(c.status == WARN for c in checks)
    print(f"\n{fails} problem(s), {warns} warning(s).", file=out)
    return 1 if fails else 0


def main(sys_: System | None = None, settings=None, out=None) -> int:
    return report(run_checks(sys_, settings), out)
