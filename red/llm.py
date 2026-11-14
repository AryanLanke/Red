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
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator, Protocol

from .config import Settings
from .downloads import download, safe_extract
from .process import ManagedServer, ServerExited, child_env, free_port, http_ok

log = logging.getLogger(__name__)

SAC_BLOCKED = 0xC0E90002  # STATUS_SYSTEM_INTEGRITY_POLICY_VIOLATION
WARM_TIMEOUT_SECONDS = 90.0       # a model load takes 6-25 s on this PC; longer means stuck
RESTART_GAP_SECONDS = 180.0       # OllamaKeeper starts Ollama again at most this often


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
    # Qwen3.5 thinks before answering unless told not to. Red needs speed, so
    # it always turns thinking off (Ollama "think": false; llama-server
    # enable_thinking false).
    thinking: bool = False
    vision: bool = False      # Ollama can send it a screenshot (describe_screen)
    best_for: str = ""        # one line for setup and the settings app

    def url(self, filename: str) -> str:
        return f"https://huggingface.co/{self.repo}/resolve/{self.revision}/{filename}"


# Qwen publishes no GGUF repo of its own for Qwen3.5; Unsloth's is the usual
# one. Ollama's tags are its own builds (with the vision part), pulled by tag.
MODELS: dict[str, ModelSpec] = {
    "qwen3.5-4b": ModelSpec(
        ollama_tag="qwen3.5:4b-q4_K_M",
        repo="unsloth/Qwen3.5-4B-GGUF",
        revision="e87f176479d0855a907a41277aca2f8ee7a09523",
        files=(
            Asset("Qwen3.5-4B-Q4_K_M.gguf",
                  "00fe7986ff5f6b463e62455821146049db6f9313603938a70800d1fb69ef11a4"),
        ),
        thinking=True, vision=True,
        best_for="fast and smart: 4 to 6 GB GPUs, or no GPU with 16 GB of RAM",
    ),
    "qwen3.5-9b": ModelSpec(
        ollama_tag="qwen3.5:9b-q4_K_M",
        repo="unsloth/Qwen3.5-9B-GGUF",
        revision="3885219b6810b007914f3a7950a8d1b469d598a5",
        files=(
            Asset("Qwen3.5-9B-Q4_K_M.gguf",
                  "03b74727a860a56338e042c4420bb3f04b2fec5734175f4cb9fa853daf52b7e8"),
        ),
        thinking=True, vision=True,
        best_for="smartest: GPUs with 8 GB or more",
    ),
    "qwen3.5-2b": ModelSpec(
        ollama_tag="qwen3.5:2b-q4_K_M",
        repo="unsloth/Qwen3.5-2B-GGUF",
        revision="f6d5376be1edb4d416d56da11e5397a961aca8ae",
        files=(
            Asset("Qwen3.5-2B-Q4_K_M.gguf",
                  "aaf42c8b7c3cab2bf3d69c355048d4a0ee9973d48f16c731c0520ee914699223"),
        ),
        thinking=True, vision=True,
        best_for="lightest Qwen3.5, but slow on a CPU with Ollama 0.40 (3.3 s a command)",
    ),
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
        best_for="the previous default (2024), 6 GB GPUs",
    ),
    "qwen2.5-3b-instruct-q4_k_m": ModelSpec(
        ollama_tag="qwen2.5:3b-instruct-q4_K_M",
        repo="Qwen/Qwen2.5-3B-Instruct-GGUF",
        revision="7dabda4d13d513e3e842b20f0d435c732f172cbe",
        files=(
            Asset("qwen2.5-3b-instruct-q4_k_m.gguf",
                  "626b4a6678b86442240e33df819e00132d3ba7dddfe1cdc4fbb18e0a9615c62d"),
        ),
        best_for="fastest with no GPU: 1.4 s a command on a laptop CPU (2024)",
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

        Clients whose model can see (vision = True) also take images: a list
        of base64 pictures that go with the user's message.

        Routing uses temperature 0 (the same command, the same tool); chat
        uses a little more, so Red doesn't sound like a form letter.
        max_tokens (default DEFAULT_MAX_TOKENS) is raised for long answers.
        """
        ...


def complete(llm, system: str, user: str, schema: dict, *, temperature: float = 0.0,
             max_tokens: int | None = None, images: list[str] | None = None) -> str:
    """llm.complete_json with options, for clients (and test fakes) that may not take them."""
    options = {k: v for k, v in (("temperature", temperature), ("max_tokens", max_tokens),
                                 ("images", images))
               if v not in (None, 0.0, [])}
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


def _stream_lines(url: str, body: dict, headers: dict | None = None, *, sse: bool = False,
                  timeout: float = 120) -> Iterator[dict]:
    """POST and yield each JSON line of the reply as it arrives (Ollama NDJSON, or SSE)."""
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            for raw in r:
                line = raw.decode("utf-8", errors="replace").strip()
                if sse:
                    if not line.startswith("data:"):
                        continue
                    line = line[5:].strip()
                    if line == "[DONE]":
                        return
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue
    except urllib.error.HTTPError as e:
        raise LLMError(f"LLM server error {e.code}: {e.read().decode(errors='replace')[:500]}") from e
    except urllib.error.URLError as e:
        raise LLMError(f"Cannot reach LLM server at {url} ({e.reason})") from e
    except (TimeoutError, OSError) as e:
        raise LLMError(f"The LLM server stopped answering ({e})") from e


def is_stall(error: BaseException | None) -> bool:
    """True when a request was taken and never answered (a read or connect timeout).

    A refused connection or an HTTP error is not a stall: the server said something.
    """
    seen: set[int] = set()
    while error is not None and id(error) not in seen:
        seen.add(id(error))
        if isinstance(error, TimeoutError):             # socket.timeout is TimeoutError
            return True
        if isinstance(error, urllib.error.URLError) and isinstance(error.reason, TimeoutError):
            return True
        error = error.__cause__ or error.__context__
    return False


def _messages(system: str, user: str) -> list[dict]:
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


class OllamaClient:
    """Ollama's native /api/chat, with the JSON schema passed as `format`."""

    def __init__(self, base_url: str, model: str, keep_alive: str = "5m", *,
                 thinking: bool = False, vision: bool = False, options: dict | None = None):
        self.base_url = base_url.rstrip("/")
        self.model, self.keep_alive = model, keep_alive
        self.thinking = thinking          # a model that thinks unless told not to
        self.vision = vision              # it can look at images (describe_screen)
        self.options = dict(options or {})   # extra Ollama options, e.g. {"num_gpu": 0}
        # Called with the reason when a request times out (OllamaKeeper starts Ollama again).
        self.on_stall: Callable[[str], object] | None = None

    def _stalled(self, error: BaseException) -> None:
        if self.on_stall is not None and is_stall(error):
            try:
                self.on_stall(str(error) or type(error).__name__)
            except Exception:  # noqa: BLE001 - the caller's own error is the one to report
                log.exception("Ollama stall handler failed")

    def _body(self, system: str, user: str, schema: dict, temperature: float,
              max_tokens: int | None, images: list[str] | None, stream: bool) -> dict:
        messages = _messages(system, user)
        if images and self.vision:
            messages[-1]["images"] = list(images)
        body = {
            "model": self.model,
            "messages": messages,
            "format": schema,
            "stream": stream,
            "keep_alive": self.keep_alive,
            "options": {"temperature": temperature, "num_predict": max_tokens or DEFAULT_MAX_TOKENS,
                        "num_ctx": 4096, **self.options},
        }
        if self.thinking:
            body["think"] = False         # answer at once; thinking costs seconds
        return body

    def complete_json(self, system: str, user: str, schema: dict, temperature: float = 0.0,
                      max_tokens: int | None = None, images: list[str] | None = None) -> str:
        body = self._body(system, user, schema, temperature, max_tokens, images, stream=False)
        try:
            data = _post_json(f"{self.base_url}/api/chat", body)
        except Exception as e:
            self._stalled(e)
            raise
        try:
            return data["message"]["content"]
        except (KeyError, TypeError) as e:
            raise LLMError(f"Unexpected Ollama response: {str(data)[:500]}") from e

    def stream_json(self, system: str, user: str, schema: dict, temperature: float = 0.0,
                    max_tokens: int | None = None, images: list[str] | None = None) -> Iterator[str]:
        """The same call as complete_json, yielding the reply as the model writes it.

        Closing the generator early closes the connection, and Ollama stops writing.
        """
        body = self._body(system, user, schema, temperature, max_tokens, images, stream=True)
        try:
            for msg in _stream_lines(f"{self.base_url}/api/chat", body):
                if "error" in msg:
                    raise LLMError(f"Ollama error: {str(msg['error'])[:300]}")
                piece = (msg.get("message") or {}).get("content") or ""
                if piece:
                    yield piece
                if msg.get("done"):
                    return
        except Exception as e:
            self._stalled(e)
            raise

    def warm(self) -> None:
        """Load the model into memory now, and keep it there for keep_alive.

        Ollama loads a model when it gets a request with no prompt, and
        generates nothing. Loading takes several seconds the first time, so
        doing it ahead keeps the first command fast.

        It loads the model with the same options as every real call (the context
        size above all). Without them Ollama loaded it at 4,096 tokens, and the next
        command, at the router's 8,192, reloaded it and read the whole prompt again:
        that was the 4 to 32 s "route" on 2026-11-13 after the plugins made the
        prompt longer.

        It gives up after WARM_TIMEOUT_SECONDS: a load takes 6 to 25 s here, and a
        server that hasn't answered in 90 s is stuck (OllamaKeeper starts it again).
        """
        try:
            _post_json(f"{self.base_url}/api/generate",
                       {"model": self.model, "keep_alive": self.keep_alive,
                        "options": {"num_ctx": 4096, **self.options}}, timeout=WARM_TIMEOUT_SECONDS)
        except Exception as e:
            self._stalled(e)
            raise

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

    def __init__(self, base_url: str, model: str, api_key: str | None = None, *,
                 thinking: bool = False):
        self.base_url = base_url.rstrip("/")
        self.model, self.api_key = model, api_key
        self.thinking = thinking

    def _body(self, system: str, user: str, schema: dict, temperature: float,
              max_tokens: int | None, stream: bool) -> dict:
        return {
            "model": self.model,
            "messages": _messages(system, user),
            "temperature": temperature,
            "max_tokens": max_tokens or DEFAULT_MAX_TOKENS,
            "response_format": {"type": "json_schema",
                                "json_schema": {"name": "route", "strict": True, "schema": schema}},
            # llama-server reads this for Qwen3.5's chat template; others ignore it.
            **({"chat_template_kwargs": {"enable_thinking": False}} if self.thinking else {}),
            **({"stream": True} if stream else {}),
        }

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}

    def complete_json(self, system: str, user: str, schema: dict, temperature: float = 0.0,
                      max_tokens: int | None = None) -> str:
        data = _post_json(f"{self.base_url}/chat/completions",
                          self._body(system, user, schema, temperature, max_tokens, False),
                          self._headers())
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as e:
            raise LLMError(f"Unexpected LLM response: {str(data)[:500]}") from e

    def stream_json(self, system: str, user: str, schema: dict, temperature: float = 0.0,
                    max_tokens: int | None = None) -> Iterator[str]:
        """Server-sent events ("data: {...}" lines), yielding the reply as it's written."""
        body = self._body(system, user, schema, temperature, max_tokens, True)
        for msg in _stream_lines(f"{self.base_url}/chat/completions", body, self._headers(), sse=True):
            try:
                piece = msg["choices"][0].get("delta", {}).get("content") or ""
            except (KeyError, IndexError, TypeError, AttributeError):
                continue
            if piece:
                yield piece


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


OLLAMA_START_TIMEOUT = 120.0   # a cold boot's GPU discovery has taken up to 48 s
GPU_LIBRARY_FILE = "ollama-gpu-library.txt"


def ollama_gpu_env(library_file: Path | None = None, libs_dir: Path | None = None,
                   which=shutil.which, environ=os.environ) -> dict[str, str]:
    """Settings that make Ollama's start faster on this PC (plan.md task 2.1).

    Ollama 0.40 probes every GPU library it ships before it answers: Vulkan, cuda_v12 and
    cuda_v13. Measured on an RTX 4050 laptop with 15 GB of RAM, mostly in use:
    - The Vulkan probe of the AMD integrated GPU took 5-25 s, only for Ollama to drop it
      ("dropping integrated GPU"). With NVIDIA's driver present, CUDA runs the model, so
      Vulkan is turned off. A PC whose only GPU is AMD or Intel keeps Vulkan.
    - Probing both CUDA builds (2 GB of DLLs) took about 20 s on every start; pinned to the
      one this GPU uses (OLLAMA_LLM_LIBRARY=cuda_v13) Ollama answered in 4.6 s. Which one
      fits depends on the driver, so it is learned from Ollama's own choice on an unpinned
      start (`learn_gpu_library`) and pinned from then on.
    A user's own OLLAMA_VULKAN or OLLAMA_LLM_LIBRARY wins.
    """
    env: dict[str, str] = {}
    if "OLLAMA_VULKAN" not in environ and which("nvidia-smi"):
        env["OLLAMA_VULKAN"] = "0"
    if "OLLAMA_LLM_LIBRARY" not in environ and library_file is not None:
        try:
            library = library_file.read_text(encoding="utf-8").strip()
        except OSError:
            library = ""
        if re.fullmatch(r"[a-z0-9_]+", library) and (libs_dir is None or (libs_dir / library).is_dir()):
            env["OLLAMA_LLM_LIBRARY"] = library
    return env


def gpu_library_from_log(text: str) -> tuple[str, str] | None:
    """(library, folder) from the last 'inference compute' line Ollama wrote, e.g.
    ('CUDA', 'cuda_v13'), or ('cpu', '') when it found no GPU. None if there is no such line."""
    lines = [l for l in text.splitlines() if 'msg="inference compute"' in l]
    if not lines:
        return None
    line = lines[-1]
    library = re.search(r"\blibrary=(\S+)", line)
    dirs = re.search(r"\blibdirs=(\S+)", line)
    folders = [d for d in (dirs.group(1).split(",") if dirs else []) if d and d != "ollama"]
    return (library.group(1) if library else "cpu", folders[0] if folders else "")


def learn_gpu_library(library_file: Path, log_text: str, pinned: bool) -> bool:
    """Remember the GPU library Ollama chose, for the next start. Returns False when a pinned
    library found no GPU (the driver changed): the pin is dropped and Ollama must start again."""
    found = gpu_library_from_log(log_text)
    on_gpu = found is not None and found[0].lower() != "cpu" and found[1]
    if on_gpu:
        try:
            library_file.parent.mkdir(parents=True, exist_ok=True)
            library_file.write_text(found[1], encoding="utf-8")
        except OSError:
            pass
        return True
    if pinned:
        library_file.unlink(missing_ok=True)
        return False
    return True


def start_ollama(settings: Settings) -> tuple[str, ManagedServer | None]:
    """Use a running Ollama, or start Red's own. Returns (base_url, server or None)."""
    if http_ok(f"{OLLAMA_DEFAULT_URL}/api/version"):
        log.info("Using the Ollama already running at %s", OLLAMA_DEFAULT_URL)
        return OLLAMA_DEFAULT_URL, None

    exe = ensure_ollama(settings)
    library_file = settings.cache_dir / GPU_LIBRARY_FILE
    log_path = settings.logs_dir / "ollama.log"
    for attempt in range(2):
        port = free_port()
        base_url = f"http://127.0.0.1:{port}"
        home = settings.cache_dir / "ollama-home"
        home.mkdir(parents=True, exist_ok=True)
        gpu_env = ollama_gpu_env(library_file, exe.parent / "lib" / "ollama")
        env = child_env(
            OLLAMA_HOST=f"127.0.0.1:{port}",
            OLLAMA_MODELS=str(settings.models_dir / "ollama"),
            OLLAMA_KEEP_ALIVE=settings.llm_keep_alive,
            USERPROFILE=str(home),                         # Ollama's ~/.ollama goes to RED_HOME
            CUDA_CACHE_PATH=str(settings.cache_dir / "cuda"),
            **gpu_env,
        )
        server = ManagedServer("ollama", [str(exe), "serve"], f"{base_url}/api/version", log_path, env)
        offset = log_path.stat().st_size if log_path.exists() else 0
        started = time.perf_counter()
        server.start(timeout=OLLAMA_START_TIMEOUT)
        log.info("Startup: Ollama answered in %.1f s (%s)", time.perf_counter() - started,
                 ", ".join(f"{k}={v}" for k, v in gpu_env.items()) or "no GPU settings")
        try:
            with log_path.open("rb") as f:
                f.seek(offset)
                new_text = f.read().decode("utf-8", "replace")
        except OSError:
            break
        pinned = "OLLAMA_LLM_LIBRARY" in gpu_env
        if learn_gpu_library(library_file, new_text, pinned) or attempt:
            break
        # The pinned library found no GPU (a new driver?): start again and let Ollama choose.
        log.warning("Ollama found no GPU with %s; starting it again without the pin.",
                    gpu_env["OLLAMA_LLM_LIBRARY"])
        server.stop()
    return base_url, server


class OllamaKeeper:
    """Starts Red's own Ollama again when it stops answering.

    On 2026-11-14 Red's Ollama hung at 03:04: it still answered /api/tags, but no
    chat request reached the model again. Every warm-up waited 300 s and every
    reply 120 s ("Sorry, I lost my train of thought") for five hours, until Red was
    quit. Now the first timed-out request (a reply, a route or the keep-warm ping)
    calls `stalled()`: the old server is stopped (its Job Object ends the runner
    too), a fresh one starts, the client points at it and the model loads again,
    all on a background thread, at most once every RESTART_GAP_SECONDS.

    Only for the Ollama Red started. Someone else's Ollama is never restarted.
    It has a `stop()`, so it stands in for the server wherever Red stops that.
    """

    def __init__(self, settings: Settings, client: OllamaClient, server: ManagedServer, *,
                 start: Callable[[Settings], tuple[str, ManagedServer | None]] | None = None,
                 clock: Callable[[], float] = time.monotonic,
                 min_gap: float = RESTART_GAP_SECONDS):
        self.settings, self.client, self.server = settings, client, server
        self._start = start or start_ollama
        self._clock, self._min_gap = clock, min_gap
        self._lock = threading.Lock()
        self._last: float | None = None
        self._busy = self._stopped = False
        self.restarts = 0
        client.on_stall = self.stalled

    def stalled(self, reason: str) -> threading.Thread | None:
        """Start Ollama again in the background. Returns the thread, or None if not now."""
        with self._lock:
            now = self._clock()
            if self._stopped or self._busy or (
                    self._last is not None and now - self._last < self._min_gap):
                return None
            self._busy, self._last = True, now
        thread = threading.Thread(target=self._restart, args=(reason,), name="red-ollama-restart",
                                  daemon=True)
        thread.start()
        return thread

    def _restart(self, reason: str) -> None:
        began = time.perf_counter()
        try:
            log.warning("Ollama stopped answering (%s): starting it again", reason)
            with self._lock:
                old, self.server = self.server, None
            if old is not None:
                old.stop()
            base_url, server = self._start(self.settings)
            with self._lock:
                if self._stopped:              # Red is quitting
                    if server is not None:
                        server.stop()
                    return
                self.server = server
            self.client.base_url = base_url.rstrip("/")
            self.restarts += 1
            try:
                self.client.warm()
            except Exception as e:  # noqa: BLE001 - the next command loads it instead
                log.warning("Ollama started again but the model didn't load: %s", e)
            log.info("Ollama is back at %s, %.1f s after the restart began", base_url,
                     time.perf_counter() - began)
        except Exception:  # noqa: BLE001 - try again on the next stall
            log.exception("Couldn't start Ollama again")
        finally:
            with self._lock:
                self._busy = False

    def stop(self) -> None:
        with self._lock:
            self._stopped = True
            server, self.server = self.server, None
        if server is not None:
            server.stop()


def keep_ollama_alive(settings: Settings, client, server):
    """Wrap Red's own Ollama in an OllamaKeeper; anything else comes back as it was."""
    if server is None or not isinstance(client, OllamaClient):
        return server
    return OllamaKeeper(settings, client, server)


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
            spec = _model_spec(settings.llm_model)
            client = OllamaClient(base_url, spec.ollama_tag, settings.llm_keep_alive,
                                  thinking=spec.thinking, vision=spec.vision)
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
    spec = MODELS.get(settings.llm_model)
    return (OpenAICompatClient(base_url, settings.llm_model, api_key,
                               thinking=bool(spec and spec.thinking)), server)
