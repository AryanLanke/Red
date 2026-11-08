"""The CLI with a fake LLM and tools whose side effects are fakes."""

import json

import pytest

from fakes import FakeRunner, FakeStartfile
from red import __main__ as cli
from red.allowlist import Allowlist
from red.tools.base import ToolRegistry
from red.tools.system import CancelShutdown, OpenFolder, Shutdown


class ScriptedLLM:
    """Returns a fixed tool call per command."""

    def __init__(self, replies):
        self.replies = replies

    def complete_json(self, system, user, schema):
        return json.dumps(self.replies[user])


@pytest.fixture
def env(monkeypatch, tmp_path):
    for name in ("RED_LLM_URL", "RED_LLM_MODEL", "RED_LLM_GPU", "RED_LLM_BACKEND",
                 "RED_LLM_KEEP_ALIVE", "GITHUB_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("RED_HOME", str(tmp_path))
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    runner, start = FakeRunner(codes={"/a": 1116}), FakeStartfile()
    registry = ToolRegistry([
        OpenFolder(allowlist=Allowlist(), startfile=start, known=lambda: {"downloads": downloads}),
        Shutdown(runner=runner), CancelShutdown(runner=runner)])
    monkeypatch.setattr(cli, "default_registry", lambda: registry)
    llm = ScriptedLLM({
        "open downloads": {"tool": "open_folder", "args": {"folder": "Downloads"}},
        "shut down in 1 hour": {"tool": "shutdown", "args": {"minutes": 60}},
        "banana": {"tool": "none", "args": {"reply": "What should I do?"}},
    })
    monkeypatch.setattr(cli, "connect", lambda settings: (llm, None))
    monkeypatch.setattr(cli, "attach_reminders", lambda on_due: None)
    return tmp_path, runner, start


def _type(monkeypatch, lines):
    it = iter(lines)

    def fake_input(prompt=""):
        try:
            return next(it)
        except StopIteration:
            raise EOFError
    monkeypatch.setattr("builtins.input", fake_input)


def test_loop_runs_actions_and_logs(env, monkeypatch, capsys):
    home, runner, start = env
    answers = iter(["no"])
    monkeypatch.setattr(cli, "typed_ask", lambda q, t: next(answers))
    _type(monkeypatch, ["open downloads", "shut down in 1 hour", "banana", "quit"])
    assert cli.main(["--typed"]) == 0
    out = capsys.readouterr().out
    assert "Red: Opening Downloads." in out
    assert "Red: Cancelled." in out
    assert "Red: What should I do?" in out
    assert len(start.calls) == 1 and runner.calls == []
    lines = (home / "logs" / "commands.jsonl").read_text(encoding="utf-8").splitlines()
    assert [json.loads(l)["status"] for l in lines] == ["ok", "cancelled", "none"]


def test_dry_run_never_runs(env, monkeypatch, capsys):
    home, runner, start = env
    _type(monkeypatch, ["open downloads", "shut down in 1 hour"])
    assert cli.main(["--dry-run"]) == 0
    out = capsys.readouterr().out
    assert '"open_folder"' in out and "will ask for confirmation" in out
    assert start.calls == [] and runner.calls == []
    assert not (home / "logs" / "commands.jsonl").exists()


def test_route_command_only_shows(env, capsys):
    home, runner, start = env
    assert cli.main(["route", "open", "downloads"]) == 0
    assert '"open_folder"' in capsys.readouterr().out
    assert start.calls == []


def test_run_command_executes(env, capsys):
    home, runner, start = env
    assert cli.main(["run", "open downloads"]) == 0
    assert "Opening Downloads." in capsys.readouterr().out
    assert len(start.calls) == 1


def test_bad_allowlist_warns_but_starts(env, capsys):
    home, _, _ = env
    (home / "config").mkdir(parents=True, exist_ok=True)
    (home / "config" / "allowlist.toml").write_text("[folders\n", encoding="utf-8")
    assert cli.main(["route", "banana"]) == 0
    assert "syntax error" in capsys.readouterr().err


def test_setup_installs_examples_and_voice_models(env, monkeypatch):
    home, _, _ = env
    fetched = []
    monkeypatch.setattr(cli, "_setup_voice", lambda settings: fetched.append(settings.home) or 0)
    assert cli.main(["setup"]) == 0
    assert fetched == [home]
    for name, example in (("allowlist.toml", cli.EXAMPLE_ALLOWLIST),
                          ("repos.toml", cli.EXAMPLE_REPOS),
                          ("contacts.toml", cli.EXAMPLE_CONTACTS)):
        assert (home / "config" / name).read_text(encoding="utf-8") == \
            example.read_text(encoding="utf-8")


def test_setup_voice_without_voice_packages(env, monkeypatch, capsys):
    def missing(settings):
        raise ImportError("No module named 'numpy'")
    monkeypatch.setattr(cli, "load_voice", missing)
    assert cli.main(["setup"]) == 1
    assert "pip install -r requirements.txt" in capsys.readouterr().out


def test_setup_voice_downloads_everything(env, monkeypatch):
    import sys
    import types

    from red.config import load_settings
    home, _, _ = env
    calls = []

    class Part:
        def __init__(self, name):
            self.name = name

        def download(self):
            calls.append(self.name)

    voice = cli.Voice(transcriber=Part("whisper"), speaker=Part("piper"), record=None,
                      chime=None, listener_factory=None, make_ask=None)
    monkeypatch.setattr(cli, "load_voice", lambda settings: voice)

    def download_wakeword(model_dir, wakeword):
        calls.append(("wakeword", wakeword, model_dir))
        raise ValueError("unknown wake word")   # not available yet: setup still succeeds
    fake_listener = types.ModuleType("red.listener")
    fake_listener.download_wakeword = download_wakeword
    monkeypatch.setitem(sys.modules, "red.listener", fake_listener)
    assert cli._setup_voice(load_settings(home)) == 0
    assert calls == ["whisper", "piper", ("wakeword", "hey_red", home / "models" / "wakeword")]
