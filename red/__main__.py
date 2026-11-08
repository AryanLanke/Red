"""Entry point.

    python -m red setup               download the LLM backend and the model
    python -m red route "open Downloads"   show the tool call for one command
    python -m red                     type commands interactively

Day 1: commands are routed and shown, never executed.
"""

from __future__ import annotations

import argparse
import logging
import sys

from .config import load_settings
from .llm import LLMError, connect
from .router import RouteError, Router
from .tools import default_registry


def _show(router: Router, command: str) -> None:
    try:
        route = router.route(command)
    except (RouteError, LLMError) as e:
        print(f"  error: {e}")
        return
    print(f"  {route.to_json()}")
    if route.destructive:
        print("  (destructive: will ask for confirmation)")
    logging.getLogger("red.commands").info("%r -> %s", command, route.to_json())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="red")
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("setup", help="download the LLM backend and the model")
    p_route = sub.add_parser("route", help="show the tool call for one command")
    p_route.add_argument("text", nargs="+")
    args = parser.parse_args(argv)

    settings = load_settings()
    settings.ensure_dirs()
    logging.basicConfig(filename=settings.logs_dir / "red.log", level=logging.INFO,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")

    print("Starting the local model...", file=sys.stderr)
    try:
        llm, server = connect(settings)
    except LLMError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    if args.cmd == "setup":
        print(f"Ready: {type(llm).__name__} with model {settings.llm_model}")
        if server:
            server.stop()
        return 0
    router = Router(default_registry(), llm)
    try:
        if args.cmd == "route":
            _show(router, " ".join(args.text))
            return 0
        print("Red (dry run). Type a command, or 'quit'.")
        while True:
            try:
                command = input("> ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if command.lower() in {"quit", "exit"}:
                break
            if command:
                _show(router, command)
        return 0
    finally:
        if server:
            server.stop()


if __name__ == "__main__":
    raise SystemExit(main())
