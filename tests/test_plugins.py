"""Plugins (plan.md B1): a test plugin loads, a broken one is skipped, on/off works. No real RED_HOME."""

import os
import textwrap

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from red import plugins as pl  # noqa: E402
from red.router import Router  # noqa: E402
from red.tools import default_registry  # noqa: E402

GOOD_TOOLS = '''
from red.tools.base import Tool


class Coin(Tool):
    name = "flip_coin"
    description = "Flip a coin: 'flip a coin', 'heads or tails'."
    args_schema = {"type": "object", "properties": {}, "additionalProperties": False}

    def run(self):
        return "Heads."


class _Helper(Tool):          # private: never registered
    name = "helper"
    description = "x"
    args_schema = {"type": "object", "properties": {}}

    def run(self):
        return ""
'''


def make(root, folder, manifest=None, tools=None, extra=None):
    path = root / folder
    path.mkdir(parents=True, exist_ok=True)
    if manifest is not None:
        (path / "plugin.toml").write_text(textwrap.dedent(manifest), encoding="utf-8")
    if tools is not None:
        (path / "tools.py").write_text(textwrap.dedent(tools), encoding="utf-8")
    for name, data in (extra or {}).items():
        (path / name).write_bytes(data)
    return path


def manifest(name, **more):
    lines = [f'name = "{name}"', 'version = "1.0"', 'description = "A test plugin."',
             'author = "Tester"', 'needs = ["nothing"]']
    lines += [f"{k} = {v}" for k, v in more.items()]
    return "\n".join(lines) + "\n"


@pytest.fixture
def home(tmp_path):
    return tmp_path


@pytest.fixture
def no_builtins(tmp_path):
    empty = tmp_path / "no-builtins"
    empty.mkdir()
    return empty


def by_name(plugins):
    return {p.name: p for p in plugins}


def test_red_plugins_is_the_module_not_the_folder():
    assert pl.__file__.endswith("plugins.py")
    assert not (pl.BUILTIN_DIR / "__init__.py").exists()     # red/plugins/ must stay a plain folder


def test_a_plugin_loads(home, no_builtins):
    make(home / "plugins", "coin", manifest("coin"), GOOD_TOOLS)
    loaded = by_name(pl.load(home, builtin_dir=no_builtins))
    coin = loaded["coin"]
    assert not coin.error and coin.enabled and [t.name for t in coin.tools] == ["flip_coin"]
    assert coin.tools[0].run() == "Heads."
    assert (coin.version, coin.author, coin.needs) == ("1.0", "Tester", ["nothing"])


@pytest.mark.parametrize("folder, toml, tools, extra, error", [
    ("broken", manifest("broken"), "def oops(:\n", None, "SyntaxError"),
    ("raises", manifest("raises"), "raise RuntimeError('boom')\n", None, "RuntimeError: boom"),
    ("exits", manifest("exits"), "import sys\nsys.exit(3)\n", None, "SystemExit: 3"),
    ("nomanifest", None, GOOD_TOOLS, None, "no plugin.toml"),
    ("badname", 'name = "Bad Name!"\n', GOOD_TOOLS, None, "needs a name"),
    ("badtoml", "name = \n", GOOD_TOOLS, None, "can't be read"),
    ("notools", manifest("notools"), None, None, "no tools.py"),
    ("empty", manifest("empty"), "x = 1\n", None, "has no tools"),
    ("native", manifest("native"), GOOD_TOOLS, {"fast.pyd": b"MZ"}, "native code"),
])
def test_a_broken_plugin_is_skipped_and_red_carries_on(home, no_builtins, folder, toml, tools, extra, error):
    make(home / "plugins", "coin", manifest("coin"), GOOD_TOOLS)
    make(home / "plugins", folder, toml, tools, extra)
    loaded = pl.load(home, builtin_dir=no_builtins)
    bad = [p for p in loaded if p.name != "coin"]
    assert len(bad) == 1 and error in bad[0].error and not bad[0].tools
    assert by_name(loaded)["coin"].tools                       # the good one still loads


def test_on_and_off(home, no_builtins):
    make(home / "plugins", "coin", manifest("coin"), GOOD_TOOLS)
    pl.set_enabled(home, "coin", False)
    coin = by_name(pl.load(home, builtin_dir=no_builtins))["coin"]
    assert not coin.enabled and coin.tools == [] and coin.status == "off"
    pl.set_enabled(home, "coin", True)
    assert by_name(pl.load(home, builtin_dir=no_builtins))["coin"].tools


def test_an_off_plugin_is_never_imported(home, no_builtins):
    make(home / "plugins", "trap", manifest("trap"), "raise SystemExit('imported!')\n")
    pl.set_enabled(home, "trap", False)
    assert by_name(pl.load(home, builtin_dir=no_builtins))["trap"].error == ""


def test_default_off_plugins_wait_for_the_user(home, no_builtins):
    make(home / "plugins", "coin", manifest("coin", default_on="false"), GOOD_TOOLS)
    assert not by_name(pl.load(home, builtin_dir=no_builtins))["coin"].enabled
    pl.set_enabled(home, "coin", True)
    assert by_name(pl.load(home, builtin_dir=no_builtins))["coin"].enabled


def test_a_taken_tool_name_is_left_out(home, no_builtins):
    make(home / "plugins", "coin", manifest("coin"), GOOD_TOOLS)
    coin = by_name(pl.load(home, {"flip_coin"}, builtin_dir=no_builtins))["coin"]
    assert coin.tools == [] and "taken" in coin.error


def test_a_tools_factory(home, no_builtins):
    make(home / "plugins", "made", manifest("made"), GOOD_TOOLS + "\n\ndef tools():\n    return [Coin()]\n")
    assert [t.name for t in by_name(pl.load(home, builtin_dir=no_builtins))["made"].tools] == ["flip_coin"]


def test_folders_starting_with_underscore_are_examples_only(home, no_builtins):
    make(home / "plugins" / "_examples", "coin", manifest("coin"), GOOD_TOOLS)
    make(home / "plugins", ".hidden", manifest("hidden"), GOOD_TOOLS)
    assert pl.load(home, builtin_dir=no_builtins) == []


def test_the_users_plugin_replaces_a_builtin(home, tmp_path):
    builtins = tmp_path / "builtins"
    make(builtins, "coin", manifest("coin"), GOOD_TOOLS)
    make(home / "plugins", "coin", manifest("coin").replace("1.0", "2.0"), GOOD_TOOLS)
    coin = by_name(pl.load(home, builtin_dir=builtins))["coin"]
    assert coin.version == "2.0" and not coin.builtin


def test_install_examples(home, tmp_path):
    builtins = tmp_path / "builtins"
    make(builtins, "coin", manifest("coin"), GOOD_TOOLS)
    target = pl.install_examples(home, builtin_dir=builtins)
    assert (target / "coin" / "tools.py").is_file() and target.name == "_examples"


def test_registry_and_router_get_plugin_tools(home):
    make(home / "plugins", "coin", manifest("coin"), GOOD_TOOLS)
    registry = default_registry(google=False, home=home)
    assert "flip_coin" in registry and any(p.name == "coin" for p in registry.plugins)
    assert "- flip_coin: " in Router(registry).system_prompt
    route = Router(registry).parse('{"tool": "flip_coin", "args": {}}')
    assert route.tool == "flip_coin"
    assert "flip_coin" not in default_registry(google=False, plugins=False)


def test_a_plugin_tool_runs_through_the_executor(home):
    from red.executor import Executor
    from red.router import Route
    make(home / "plugins", "coin", manifest("coin"), GOOD_TOOLS)
    registry = default_registry(google=False, home=home)
    assert Executor(registry).execute("flip a coin", Route("flip_coin", {}, False)) == "Heads."


def test_plugins_list_on_off(home, capsys):
    make(home / "plugins", "coin", manifest("coin"), GOOD_TOOLS)
    make(home / "plugins", "broken", manifest("broken"), "def oops(:\n")
    assert pl.main(home, ["list"]) == 0
    out = capsys.readouterr().out
    assert "coin 1.0  [on, 1 tool]" in out and "tools: flip_coin" in out
    assert "broken 1.0  [skipped: SyntaxError" in out
    assert pl.main(home, ["off", "coin"]) == 0
    assert "coin is off" in capsys.readouterr().out
    pl.main(home, [])
    assert "coin 1.0  [off]" in capsys.readouterr().out
    assert pl.main(home, ["off", "nope"]) == 1
    assert pl.main(home, ["dance"]) == 2


def test_cli_plugins_command(home, monkeypatch, capsys):
    from red.__main__ import main
    for key in list(os.environ):
        if key.startswith("RED_"):
            monkeypatch.delenv(key, raising=False)
    make(home / "plugins", "coin", manifest("coin"), GOOD_TOOLS)
    assert main(["--home", str(home), "plugins", "list"]) == 0
    assert "coin 1.0" in capsys.readouterr().out


def test_the_plugins_page(home, no_builtins):
    from PySide6.QtWidgets import QApplication

    from red.app.pages import PluginsPage
    from red.config import load_settings
    QApplication.instance() or QApplication([])
    make(home / "plugins", "coin", manifest("coin"), GOOD_TOOLS)
    make(home / "plugins", "trap", manifest("trap"), "raise SystemExit('imported!')\n")
    make(home / "plugins", "nomanifest", None, GOOD_TOOLS)
    page = PluginsPage(load_settings(home), discover=lambda: pl.discover(home, no_builtins))
    assert set(page.boxes) == {"coin", "trap"}                 # the page never imports a plugin
    assert page.boxes["coin"].isChecked()
    page.boxes["coin"].setChecked(False)
    page.save()
    assert not pl.is_enabled(pl.read_state(home), "coin")
    assert pl.is_enabled(pl.read_state(home), "trap")
