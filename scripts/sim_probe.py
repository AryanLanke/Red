"""How fast is Red's Ollama right now? Three tiny chat calls and the loaded model, so a sim run's
speed numbers can be read against the load other sessions put on the GPU.

    python scripts\\sim_probe.py
"""

from __future__ import annotations

import json
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from red.chat import CHAT_SCHEMA  # noqa: E402
from red.sim import ollama  # noqa: E402


def loaded(port: int) -> str:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/ps", timeout=5) as r:
            models = json.load(r).get("models", [])
    except Exception as e:  # noqa: BLE001
        return f"unreadable ({e})"
    return ", ".join(f"{m['name']} ctx={m.get('context_length')}" for m in models) or "nothing loaded"


def warm(llm, calls: int = 3) -> list[float]:
    """Seconds for each tiny call; the first one pays for a load, the rest show the real speed."""
    times = []
    for _ in range(calls):
        start = time.perf_counter()
        llm.complete_json("Reply with a very short greeting.", "hi", CHAT_SCHEMA, temperature=0.0, max_tokens=12)
        times.append(time.perf_counter() - start)
    return times


def main() -> int:
    port = ollama.find_port()
    if port is None:
        print("Red's Ollama isn't running")
        return 2
    print(f"port {port}; loaded before: {loaded(port)}")
    llm = ollama.client(port)
    print("calls:", " ".join(f"{t:.2f}s" for t in warm(llm)))
    print(f"loaded after: {loaded(port)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
