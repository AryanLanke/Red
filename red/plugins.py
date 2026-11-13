"""Plugins: Red grows by adding folders, not by editing Red (plan.md B1).

A plugin is a folder with two files:

    plugin.toml   name, version, description, author, and what it needs
    tools.py      plain Tool subclasses, the same format as red/tools/

Red's own plugins ship in red/plugins/ and always load from there (so an update
reaches them). The user's plugins live in RED_HOME\\plugins\\<name>\\ and win
over a built-in one of the same name. `python -m red setup` copies the
built-in ones to RED_HOME\\plugins\\_examples\\ to read and copy from; folders
starting with "_" or "." are never loaded.

Loading never stops Red: a plugin that's broken, has no tools, ships native
code (.pyd or .dll, which Smart App Control blocks anyway), or clashes with a
tool name that's already taken is skipped and logged, with the reason shown
on the Plugins page and in `python -m red plugins list`.

Safety is the same as for Red's own tools. A plugin is code the user chose to
install; the model only picks one of its tools and fills its schema-checked
arguments. Model text never reaches a shell. Turning a plugin off
(RED_HOME\\config\\plugins.json) means its tools.py isn't even imported.
"""

from __future__ import annotations

import importlib.util
import inspect
import json
import logging
import re
import shutil
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from .tools.base import Tool

log = logging.getLogger(__name__)

BUILTIN_DIR = Path(__file__).resolve().parent / "plugins"
NAME = re.compile(r"^[a-z][a-z0-9_-]{0,39}$")
NATIVE = ("*.pyd", "*.dll", "*.exe", "*.so")


def user_plugins_dir(home: Path) -> Path:
    return Path(home) / "plugins"


def state_path(home: Path) -> Path:
    return Path(home) / "config" / "plugins.json"


@dataclass
class Plugin:
    name: str
    folder: Path
    version: str = ""
    description: str = ""
    author: str = ""
    needs: list[str] = field(default_factory=list)
    builtin: bool = False
    enabled: bool = True
    default_on: bool = True
    tools: list[Tool] = field(default_factory=list)
    error: str = ""

    @property
    def status(self) -> str:
        if self.error:
            return f"skipped: {self.error}"
        if not self.enabled:
            return "off"
        return f"on, {len(self.tools)} tool{'s' if len(self.tools) != 1 else ''}"


# --- on and off -------------------------------------------------------------------------

def read_state(home: Path) -> dict:
    try:
        data = json.loads(state_path(home).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def set_enabled(home: Path, name: str, on: bool) -> None:
    """Turn one plugin on or off (picked up the next time Red starts)."""
    state = read_state(home)
    off = set(state.get("off", []))
    forced_on = set(state.get("on", []))
    (off.discard if on else off.add)(name)
    (forced_on.add if on else forced_on.discard)(name)
    state["off"], state["on"] = sorted(off), sorted(forced_on)
    path = state_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2), encoding="utf-8")


def is_enabled(state: dict, name: str, default_on: bool = True) -> bool:
    if name in state.get("off", []):
        return False
    if name in state.get("on", []):
        return True
    return default_on


# --- finding and loading ------------------------------------------------------------------

def read_manifest(folder: Path) -> Plugin:
    """plugin.toml -> a Plugin (no code is imported). Raises ValueError when it's not valid."""
    try:
        data = tomllib.loads((folder / "plugin.toml").read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ValueError("no plugin.toml") from None
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as e:
        raise ValueError(f"plugin.toml can't be read ({e})") from None
    name = str(data.get("name", "")).strip()
    if not NAME.match(name):
        raise ValueError("plugin.toml needs a name: lower case letters, digits, - or _")
    needs = data.get("needs", [])
    if isinstance(needs, str):
        needs = [needs]
    return Plugin(name=name, folder=folder, version=str(data.get("version", "")).strip(),
                  description=str(data.get("description", "")).strip()[:300],
                  author=str(data.get("author", "")).strip()[:100],
                  needs=[str(n) for n in needs if str(n).strip()][:10],
                  default_on=bool(data.get("default_on", True)))


def _folders(root: Path) -> list[Path]:
    try:
        return sorted(p for p in root.iterdir()
                      if p.is_dir() and not p.name.startswith(("_", ".")))
    except OSError:
        return []


def discover(home: Path | None, builtin_dir: Path = BUILTIN_DIR) -> list[Plugin]:
    """Every plugin folder, built-in first; a user's plugin replaces a built-in of the same name."""
    found: dict[str, Plugin] = {}
    roots = [(builtin_dir, True)] + ([(user_plugins_dir(home), False)] if home is not None else [])
    for root, builtin in roots:
        for folder in _folders(root):
            try:
                plugin = read_manifest(folder)
            except ValueError as e:
                plugin = Plugin(name=folder.name, folder=folder, error=str(e))
            plugin.builtin = builtin
            if plugin.name in found and not builtin:
                log.info("Plugin %s in %s replaces Red's own", plugin.name, folder)
            found[plugin.name] = plugin
    return list(found.values())


def _import_tools(plugin: Plugin) -> list[Tool]:
    path = plugin.folder / "tools.py"
    if not path.is_file():
        raise ValueError("no tools.py")
    native = [p.name for pattern in NATIVE for p in plugin.folder.rglob(pattern)]
    if native:
        raise ValueError(f"has native code ({', '.join(sorted(native)[:3])}); plugins are pure Python")
    module_name = f"red_plugin_{plugin.name.replace('-', '_')}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ValueError("tools.py can't be imported")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(module_name, None)
        raise
    factory = getattr(module, "tools", None)
    if callable(factory):
        tools = list(factory())
    else:
        tools = [cls() for _, cls in inspect.getmembers(module, inspect.isclass)
                 if issubclass(cls, Tool) and cls.__module__ == module_name
                 and not inspect.isabstract(cls) and not cls.__name__.startswith("_")]
    tools = [t for t in tools if isinstance(t, Tool)]
    if not tools:
        raise ValueError("tools.py has no tools")
    return tools


def load(home: Path | None, taken: set[str] = frozenset(), builtin_dir: Path = BUILTIN_DIR) -> list[Plugin]:
    """Discover and import every plugin that's on. Never raises.

    `taken` is the tool names already in use (Red's own); a plugin tool with
    one of those names is left out, and the plugin noted.
    """
    state = read_state(home) if home is not None else {}
    plugins = discover(home, builtin_dir)
    names = set(taken)
    for plugin in plugins:
        if plugin.error:
            log.warning("Plugin %s skipped: %s", plugin.name, plugin.error)
            continue
        plugin.enabled = is_enabled(state, plugin.name, plugin.default_on)
        if not plugin.enabled:
            continue
        try:
            tools = _import_tools(plugin)
        except (Exception, SystemExit) as e:  # noqa: BLE001 - a broken plugin never stops Red
            plugin.error = f"{type(e).__name__}: {e}" if not isinstance(e, ValueError) else str(e)
            log.warning("Plugin %s skipped: %s", plugin.name, plugin.error)
            continue
        kept = []
        for tool in tools:
            if not getattr(tool, "name", "") or tool.name in names or tool.name == "none":
                log.warning("Plugin %s: tool name %r is taken; left out", plugin.name,
                            getattr(tool, "name", ""))
                continue
            names.add(tool.name)
            kept.append(tool)
        plugin.tools = kept
        if not kept:
            plugin.error = "every tool name is already taken"
        else:
            log.info("Plugin %s %s: %s", plugin.name, plugin.version,
                     ", ".join(t.name for t in kept))
    return plugins


def install_examples(home: Path, builtin_dir: Path = BUILTIN_DIR) -> Path:
    """Copy Red's own plugins to RED_HOME\\plugins\\_examples (setup). Returns the folder."""
    target = user_plugins_dir(home) / "_examples"
    for folder in _folders(builtin_dir):
        dest = target / folder.name
        shutil.copytree(folder, dest, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    return target


def describe(plugins: list[Plugin]) -> str:
    """The text for `python -m red plugins list`."""
    if not plugins:
        return "No plugins yet. Add a folder with plugin.toml and tools.py to RED_HOME\\plugins."
    lines = []
    for p in plugins:
        where = "built in" if p.builtin else str(p.folder)
        head = f"{p.name} {p.version}".strip()
        lines.append(f"{head}  [{p.status}]  ({where})")
        if p.description:
            lines.append(f"    {p.description}")
        if p.tools:
            lines.append(f"    tools: {', '.join(t.name for t in p.tools)}")
        if p.needs:
            lines.append(f"    needs: {', '.join(p.needs)}")
    return "\n".join(lines)


def main(home: Path, args: list[str]) -> int:
    """python -m red plugins list | on NAME | off NAME"""
    action = args[0] if args else "list"
    if action == "list":
        from .tools import default_registry
        base = {t.name for t in default_registry(google=False, plugins=False)}
        print(describe(load(home, base)))
        return 0
    if action in ("on", "off") and len(args) == 2:
        names = {p.name for p in discover(home)}
        if args[1] not in names:
            print(f"No plugin called {args[1]}. Try: python -m red plugins list", file=sys.stderr)
            return 1
        set_enabled(home, args[1], action == "on")
        print(f"{args[1]} is {action}. Restart Red to pick it up.")
        return 0
    print("Usage: python -m red plugins list | on NAME | off NAME", file=sys.stderr)
    return 2
