"""Entry point.

    python -m red setup                    download the LLM backend and the model
    python -m red route "open Downloads"   show the tool call for one command (never runs it)
    python -m red run "open Downloads"     run one command
    python -m red                          type commands interactively and run them
    python -m red --dry-run                type commands, only show the tool calls

Destructive actions (shutdown, restart) always ask first.
"""

from __future__ import annotations

import argparse
import logging
import shutil
import sys
from pathlib import Path

from .allowlist import AllowlistError, load_allowlist
from .config import Settings, load_settings
from .executor import Executor
from .llm import LLMError, connect
from .router import RouteError, Router
from .tools import default_registry

EXAMPLE_ALLOWLIST = Path(__file__).resolve().parent.parent / "allowlist.example.toml"


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


def _run(router: Router, executor: Executor, command: str) -> None:
    try:
        route = router.route(command)
    except (RouteError, LLMError) as e:
        print(f"  Sorry, I didn't get that. ({e})")
        return
    logging.getLogger("red.commands").info("%r -> %s", command, route.to_json())
    if not route.is_none:
        print(f"  -> {route.to_json()}")
    print(f"  Red: {executor.execute(command, route)}")


def _install_example_allowlist(settings: Settings) -> None:
    if not settings.allowlist_path.exists() and EXAMPLE_ALLOWLIST.is_file():
        shutil.copyfile(EXAMPLE_ALLOWLIST, settings.allowlist_path)
        print(f"Created {settings.allowlist_path}; add your folders and apps there.")


def _check_allowlist(settings: Settings) -> None:
    try:
        load_allowlist(settings.allowlist_path)
    except AllowlistError as e:
        print(f"warning: {e}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="red")
    parser.add_argument("--dry-run", action="store_true",
                        help="only show the tool call for each command, never run it")
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("setup", help="download the LLM backend and the model")
    p_route = sub.add_parser("route", help="show the tool call for one command")
    p_route.add_argument("text", nargs="+")
    p_run = sub.add_parser("run", help="run one command")
    p_run.add_argument("text", nargs="+")
    args = parser.parse_args(argv)

    settings = load_settings()
    settings.ensure_dirs()
    logging.basicConfig(filename=settings.logs_dir / "red.log", level=logging.INFO,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")
    if args.cmd == "setup":
        _install_example_allowlist(settings)
    _check_allowlist(settings)

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
    registry = default_registry()
    router = Router(registry, llm)
    executor = Executor(registry, log_path=settings.command_log_path)
    handle = (lambda c: _show(router, c)) if args.dry_run else (lambda c: _run(router, executor, c))
    try:
        if args.cmd == "route":
            _show(router, " ".join(args.text))
            return 0
        if args.cmd == "run":
            handle(" ".join(args.text))
            return 0
        print("Red (dry run). Type a command, or 'quit'." if args.dry_run
              else "Red. Type a command, or 'quit'.")
        while True:
            try:
                command = input("> ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if command.lower() in {"quit", "exit"}:
                break
            if command:
                handle(command)
        return 0
    finally:
        if server:
            server.stop()


if __name__ == "__main__":
    raise SystemExit(main())
