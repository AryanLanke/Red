"""Finding the hidden Red's Ollama and making a client for it. The sim never starts a second Ollama."""

from __future__ import annotations

import json
import re
import subprocess
import urllib.request

from ..llm import OllamaClient

DEFAULT_MODEL = "qwen3.5:4b-q4_K_M"
DEFAULT_CTX = 8192


def find_port() -> int | None:
    """The port the running Ollama listens on (netstat + tasklist), or None."""
    try:
        tasks = subprocess.run(["tasklist", "/FI", "IMAGENAME eq ollama.exe", "/FO", "CSV", "/NH"],
                               capture_output=True, text=True, timeout=15).stdout
        pids = set(re.findall(r'"ollama\.exe","(\d+)"', tasks))
        net = subprocess.run(["netstat", "-ano", "-p", "tcp"], capture_output=True, text=True, timeout=15).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    for line in net.splitlines():
        m = re.search(r"127\.0\.0\.1:(\d+)\s+0\.0\.0\.0:0\s+LISTENING\s+(\d+)\s*$", line.strip())
        if m and m.group(2) in pids:
            return int(m.group(1))
    return None


def loaded_context(port: int, model: str) -> int | None:
    """The context size the model is loaded with now (asking for another one forces a reload)."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/ps", timeout=5) as r:
            data = json.load(r)
    except Exception:  # noqa: BLE001
        return None
    for m in data.get("models", []):
        if m.get("name") == model or m.get("model") == model:
            return int(m.get("context_length") or 0) or None
    return None


def client(port: int | None = None, model: str = DEFAULT_MODEL, num_ctx: int | None = None) -> OllamaClient:
    port = port or find_port()
    if port is None:
        raise RuntimeError("Red's Ollama isn't running (the sim never starts a second one)")
    # 8192 is what common.md tells every session to send. A different size makes Ollama reload the
    # model (10 to 40 s on this GPU, for the user's Red too), so sessions must agree on one.
    ctx = num_ctx or DEFAULT_CTX
    return OllamaClient(f"http://127.0.0.1:{port}", model, "5m", thinking=True, options={"num_ctx": ctx})
