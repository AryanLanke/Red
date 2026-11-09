"""Local LLM backends and clients.

Backends, in the order Red tries them (RED_LLM_BACKEND=auto):

1. RED_LLM_URL, if set: any OpenAI-compatible server you run yourself.
2. Ollama. If one is already running on 127.0.0.1:11434, Red uses it.
   Otherwise Red starts its own pinned, code-signed Ollama build from
   RED_HOME\\bin, keeps models in RED_HOME\\models\\ollama, and stops it on exit.
3. Bundled llama.cpp llama-server. Unsigned, so Windows Smart App Control
   blocks it on PCs where that's turned on.

All downloads are pinned to exact versions and verified by SHA-256.
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .config import Settings
from .downloads import download, safe_extract
from .process import ManagedServer, ServerExited, child_env, free_port, http_ok

log = logging.getLogger(__name__)

SAC_BLOCKED = 0xC0E90002  # STATUS_SYSTEM_INTEGRITY_POLICY_VIOLATION


class LLMError(RuntimeError):
    pass


@dataclass(frozen=True)
class Asset:
    filename: str
    sha256: str


# --- Pinned assets -----------------------------------------------------------

OLLAMA_VERSION = "v0.40.11"
OLLAMA_ZIP = Asset("ollama-windows-amd64.zip",
                   "bda4a493ba8a7c24d57263cd843cd68cee84f44aed4299eeed532acad7eda12a")

LLAMA_CPP_BUILD = "b12040"
_LLAMA_GH = f"https://github.com/ggml-org/llama.cpp/releases/download/{LLAMA_CPP_BUILD}/"
LLAMA_SERVER_ASSETS: dict[str, list[Asset]] = {
    "cuda": [
        Asset(f"llama-{LLAMA_CPP_BUILD}-bin-win-cuda-12.4-x64.zip",
              "71472d2206a8e1618e3902f598dec77fe7aee74c5b75159e3d46cbb749361a62"),
        Asset("cudart-llama-bin-win-cuda-12.4-x64.zip",
              "8c79a9b226de4b3cacfd1f83d24f962d0773be79f1e7b75c6af4ded7e32ae1d6"),
    ],
    "vulkan": [
        Asset(f"llama-{LLAMA_CPP_BUILD}-bin-win-vulkan-x64.zip",
              "1198da0b60ab53e9a92940e00d12b9d1baebdcf9b42e31ef3298d6dc590b6bc8"),
    ],
    "cpu": [
        Asset(f"llama-{LLAMA_CPP_BUILD}-bin-win-cpu-x64.zip",
              "e21d19fe2a8160a26ca5a6f0c9cf573d0202e233c735fe22439813c2776d0706"),
    ],
}


@dataclass(frozen=True)
class ModelSpec:
    ollama_tag: str
    repo: str                 # Hugging Face GGUF, for llama-server
    revision: str
    files: tuple[Asset, ...]  # split GGUFs: first file is the one to load

    def url(self, filename: str) -> str:
        return f"https://huggingface.co/{self.repo}/resolve/{self.revision}/{filename}"


MODELS: dict[str, ModelSpec] = {
    "qwen2.5-7b-instruct-q4_k_m": ModelSpec(
        ollama_tag="qwen2.5:7b-instruct-q4_K_M",
        repo="Qwen/Qwen2.5-7B-Instruct-GGUF",
        revision="bb5d59e06d9551d752d08b292a50eb208b07ab1f",
        files=(
            Asset("qwen2.5-7b-instruct-q4_k_m-00001-of-00002.gguf",
                  "dfce12e3862a5283ccfb88221b48480e58745165de856439950d0f22590580db"),
            Asset("qwen2.5-7b-instruct-q4_k_m-00002-of-00002.gguf",
                  "539cf93f78e887edea1c04e2d7d8cdaca9d01dae9c9025bcb8accbe29df3d72a"),
        ),
    ),
    "qwen2.5-3b-instruct-q4_k_m": ModelSpec(
        ollama_tag="qwen2.5:3b-instruct-q4_K_M",
        repo="Qwen/Qwen2.5-3B-Instruct-GGUF",
        revision="7dabda4d13d513e3e842b20f0d435c732f172cbe",
        files=(
            Asset("qwen2.5-3b-instruct-q4_k_m.gguf",
                  "626b4a6678b86442240e33df819e00132d3ba7dddfe1cdc4fbb18e0a9615c62d"),
        ),
    ),
}


def _model_spec(name: str) -> ModelSpec:
    spec = MODELS.get(name)
    if spec is None:
        raise LLMError(f"Unknown model {name!r}. Options: {', '.join(MODELS)}")
    return spec


# --- Clients -----------------------------------------------------------------

DEFAULT_MAX_TOKENS = 256     # a tool call or a few sentences


class LLM(Protocol):
    def complete_json(self, system: str, user: str, schema: dict, temperature: float = 0.0,
                      max_tokens: int | None = None) -> str:
        """Return the model's reply, constrained to the JSON schema.

        Routing uses temperature 0 (the same command, the same tool); chat
        uses a little more, so Red doesn't sound like a form letter.
        max_tokens (default DEFAULT_MAX_TOKENS) is raised for long answers.
        """
        ...


def complete(llm, system: str, user: str, schema: dict, *, temperature: float = 0.0,
             max_tokens: int | None = None) -> str:
    """llm.complete_json with options, for clients (and test fakes) that may not take them."""
    options = {k: v for k, v in (("temperature", temperature), ("max_tokens", max_tokens))
               if v not in (None, 0.0)}
    if not options:
        return llm.complete_json(system, user, schema)
    try:
        return llm.complete_json(system, user, schema, **options)
    except TypeError as e:
        if "unexpected keyword" not in str(e):
            raise
        return llm.complete_json(system, user, schema)


def _post_json(url: str, body: dict, headers: dict | None = None, timeout: float = 120) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        raise LLMError(f"LLM server error {e.code}: {e.read().decode(errors='replace')[:500]}") from e
    except urllib.error.URLError as e:
        raise LLMError(f"Cannot reach LLM server at {url} ({e.reason})") from e


def _messages(system: str, user: str) -> list[dict]:
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


class OllamaClient:
    """Ollama's native /api/chat, with the JSON schema passed as `format`."""

    def __init__(self, base_url: str, model: str, keep_alive: str = "5m"):
        self.base_url = base_url.rstrip("/")
        self.model, self.keep_alive = model, keep_alive

    def complete_json(self, system: str, user: str, schema: dict, temperature: float = 0.0,
                      max_tokens: int | None = None) -> str:
        data = _post_json(f"{self.base_url}/api/chat", {
            "model": self.model,
            "messages": _messages(system, user),
            "format": schema,
            "stream": False,
            "keep_alive": self.keep_alive,
            "options": {"temperature": temperature, "num_predict": max_tokens or DEFAULT_MAX_TOKENS,
                        "num_ctx": 4096},
        })
        try:
            return data["message"]["content"]
        except (KeyError, TypeError) as e:
            raise LLMError(f"Unexpected Ollama response: {str(data)[:500]}") from e

    def warm(self) -> None:
        """Load the model into memory now, and keep it there for keep_alive.

        Ollama loads a model when it gets a request with no prompt, and
        generates nothing. Loading takes several seconds the first time, so
        doing it ahead keeps the first command fast.
        """
        _post_json(f"{self.base_url}/api/generate",
                   {"model": self.model, "keep_alive": self.keep_alive}, timeout=300)

    def has_model(self) -> bool:
        try:
            with urllib.request.urlopen(f"{self.base_url}/api/tags", timeout=10) as r:
                tags = json.load(r)
        except (urllib.error.URLError, OSError) as e:
            raise LLMError(f"Cannot reach Ollama at {self.base_url} ({e})") from e
        return any(m.get("name") == self.model for m in tags.get("models", []))

    def pull(self) -> None:
        """Download the model through Ollama, showing progress."""
        req = urllib.request.Request(
            f"{self.base_url}/api/pull", data=json.dumps({"model": self.model}).encode(),
            headers={"Content-Type": "application/json"})
        last = ""
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                for line in r:
                    msg = json.loads(line)
                    if "error" in msg:
                        raise LLMError(f"Ollama pull failed: {msg['error']}")
                    status = msg.get("status", "")
                    if msg.get("total"):
                        pct = msg.get("completed", 0) * 100 // msg["total"]
                        status = f"{status} {pct}% of {msg['total'] / 1e9:.2f} GB"
                    if status != last:
                        print(f"\r  {self.model}: {status:<60}", end="", file=sys.stderr, flush=True)
                        last = status
        except urllib.error.URLError as e:
            raise LLMError(f"Ollama pull failed ({e})") from e
        print(file=sys.stderr)


class OpenAICompatClient:
    """/v1/chat/completions with JSON-schema output (llama-server, LM Studio, ...)."""

    def __init__(self, base_url: str, model: str, api_key: str | None = None):
        self.base_url = base_url.rstrip("/")
        self.model, self.api_key = model, api_key

    def complete_json(self, system: str, user: str, schema: dict, temperature: float = 0.0,
                      max_tokens: int | None = None) -> str:
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        data = _post_json(f"{self.base_url}/chat/completions", {
            "model": self.model,
            "messages": _messages(system, user),
            "temperature": temperature,
            "max_tokens": max_tokens or DEFAULT_MAX_TOKENS,
            "response_format": {"type": "json_schema",
                                "json_schema": {"name": "route", "strict": True, "schema": schema}},
        }, headers)
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as e:
            raise LLMError(f"Unexpected LLM response: {str(data)[:500]}") from e


# --- Ollama backend ----------------------------------------------------------

OLLAMA_DEFAULT_URL = "http://127.0.0.1:11434"


def ensure_ollama(settings: Settings) -> Path:
    target = settings.bin_dir / "ollama" / OLLAMA_VERSION
    marker = target / ".installed"
    if not marker.exists():
        url = f"https://github.com/ollama/ollama/releases/download/{OLLAMA_VERSION}/{OLLAMA_ZIP.filename}"
        z = download(url, settings.cache_dir / "downloads" / f"ollama-{OLLAMA_VERSION}.zip",
                     OLLAMA_ZIP.sha256)
        if target.exists():
            shutil.rmtree(target)
        target.mkdir(parents=True)
        safe_extract(z, target)
        marker.write_text(OLLAMA_VERSION)
        z.unlink(missing_ok=True)
    exe = target / "ollama.exe"
    if not exe.exists():
        raise LLMError(f"ollama.exe not found in {target}")
    return exe


def start_ollama(settings: Settings) -> tuple[str, ManagedServer | None]:
    """Use a running Ollama, or start Red's own. Returns (base_url, server or None)."""
    if http_ok(f"{OLLAMA_DEFAULT_URL}/api/version"):
        log.info("Using the Ollama already running at %s", OLLAMA_DEFAULT_URL)
        return OLLAMA_DEFAULT_URL, None

    exe = ensure_ollama(settings)
    port = free_port()
    base_url = f"http://127.0.0.1:{port}"
    home = settings.cache_dir / "ollama-home"
    home.mkdir(parents=True, exist_ok=True)
    env = child_env(
        OLLAMA_HOST=f"127.0.0.1:{port}",
        OLLAMA_MODELS=str(settings.models_dir / "ollama"),
        OLLAMA_KEEP_ALIVE=settings.llm_keep_alive,
        USERPROFILE=str(home),                         # Ollama's ~/.ollama goes to RED_HOME
        CUDA_CACHE_PATH=str(settings.cache_dir / "cuda"),
    )
    server = ManagedServer("ollama", [str(exe), "serve"], f"{base_url}/api/version",
                           settings.logs_dir / "ollama.log", env)
    server.start(timeout=60)
    return base_url, server


# --- llama.cpp backend -------------------------------------------------------

def detect_gpu(preference: str = "auto") -> str:
    """Pick cuda, vulkan, or cpu for llama-server."""
    if preference != "auto":
        return preference
    smi = shutil.which("nvidia-smi")
    if smi:
        try:
            out = subprocess.run([smi, "-L"], capture_output=True, text=True, timeout=10)
            if out.returncode == 0 and "GPU" in out.stdout:
                return "cuda"
        except (OSError, subprocess.SubprocessError):
            pass
    if (Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "vulkan-1.dll").exists():
        return "vulkan"
    return "cpu"


def ensure_llama_server(settings: Settings, gpu: str) -> Path:
    target = settings.bin_dir / "llama.cpp" / f"{LLAMA_CPP_BUILD}-{gpu}"
    marker = target / ".installed"
    if not marker.exists():
        downloads = settings.cache_dir / "downloads"
        zips = [download(_LLAMA_GH + a.filename, downloads / a.filename, a.sha256)
                for a in LLAMA_SERVER_ASSETS[gpu]]
        if target.exists():
            shutil.rmtree(target)
        target.mkdir(parents=True)
        safe_extract(zips[0], target)
        exe = _find(target, "llama-server.exe")
        for extra in zips[1:]:  # CUDA runtime DLLs go next to the exe
            safe_extract(extra, exe.parent)
        marker.write_text(LLAMA_CPP_BUILD)
        for z in zips:
            z.unlink(missing_ok=True)
    return _find(target, "llama-server.exe")


def _find(target: Path, name: str) -> Path:
    found = next(target.rglob(name), None)
    if not found:
        raise LLMError(f"{name} not found under {target}")
    return found


def ensure_gguf(settings: Settings, name: str) -> Path:
    spec = _model_spec(name)
    llm_dir = settings.models_dir / "llm"
    return [download(spec.url(a.filename), llm_dir / a.filename, a.sha256) for a in spec.files][0]


def start_llama_server(settings: Settings) -> tuple[str, str, ManagedServer]:
    """Returns (base_url, api_key, server)."""
    gpu = detect_gpu(settings.llm_gpu)
    exe = ensure_llama_server(settings, gpu)
    model = ensure_gguf(settings, settings.llm_model)
    port, api_key = free_port(), secrets.token_urlsafe(24)
    cmd = [str(exe), "-m", str(model), "--host", "127.0.0.1", "--port", str(port),
           "-ngl", "0" if gpu == "cpu" else "99", "-c", "4096", "--api-key", api_key]
    server = ManagedServer("llama-server", cmd, f"http://127.0.0.1:{port}/health",
                           settings.logs_dir / "llama-server.log")
    try:
        server.start(timeout=180)
    except ServerExited as e:
        if e.code == SAC_BLOCKED:
            raise LLMError(
                "Windows Smart App Control blocked llama-server because it isn't code-signed. "
                "Use the Ollama backend instead (RED_LLM_BACKEND=ollama).") from e
        raise LLMError(str(e)) from e
    return f"http://127.0.0.1:{port}/v1", api_key, server


# --- Entry point -------------------------------------------------------------

def connect(settings: Settings) -> tuple[LLM, ManagedServer | None]:
    """Return a ready client, downloading and starting a backend if needed.

    The caller owns the returned server (if any) and should stop it when done.
    """
    if settings.llm_url:
        return OpenAICompatClient(settings.llm_url, settings.llm_model), None

    errors = []
    if settings.llm_backend in ("auto", "ollama"):
        server = None
        try:
            base_url, server = start_ollama(settings)
            client = OllamaClient(base_url, _model_spec(settings.llm_model).ollama_tag,
                                  settings.llm_keep_alive)
            if not client.has_model():
                client.pull()
            return client, server
        except (LLMError, ServerExited, TimeoutError, OSError) as e:
            if server:
                server.stop()
            if settings.llm_backend == "ollama":
                raise LLMError(f"Ollama backend failed: {e}") from e
            log.warning("Ollama backend failed, trying llama.cpp: %s", e)
            errors.append(f"Ollama: {e}")

    try:
        base_url, api_key, server = start_llama_server(settings)
    except (LLMError, TimeoutError, OSError) as e:
        errors.append(f"llama.cpp: {e}")
        raise LLMError("No LLM backend could start.\n  " + "\n  ".join(errors)) from e
    return OpenAICompatClient(base_url, settings.llm_model, api_key), server
