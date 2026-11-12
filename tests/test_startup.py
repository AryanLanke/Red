"""The sign-in shortcut helper, with a fake Startup folder and a fake PowerShell. Never real."""

import base64
import subprocess
from pathlib import Path

import pytest

from red import __main__ as cli
from red import startup as st


class FakePowerShell:
    """Records the call and writes the .lnk the real script would write."""

    def __init__(self, code=0, write=True):
        self.code, self.write, self.calls = code, write, []

    def __call__(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        if self.write and self.code == 0:
            Path(kwargs["env"]["RED_LNK_PATH"]).write_bytes(b"lnk")
        return subprocess.CompletedProcess(argv, self.code, stdout="", stderr="boom" if self.code else "")


@pytest.fixture
def folder(tmp_path):
    return tmp_path / "Startup"


def make(folder, runner, home=Path("D:/RED")):
    return st.Startup(home, folder=lambda: folder, runner=runner,
                      python=lambda: "D:\\RED\\.venv\\Scripts\\pythonw.exe",
                      workdir=Path("D:/RED/red"))


def test_on_creates_shortcut_through_fixed_script(folder):
    ps = FakePowerShell()
    s = make(folder, ps)
    assert not s.is_on()
    reply = s.on()
    assert s.is_on() and "start when you sign in" in reply
    assert len(ps.calls) == 2                       # Red + the hotkey watcher
    argv, kwargs = ps.calls[0]
    assert argv[0].lower().endswith("powershell.exe") and "-EncodedCommand" in argv
    script = base64.b64decode(argv[-1]).decode("utf-16-le")
    assert "CreateShortcut($env:RED_LNK_PATH)" in script
    assert "D:\\RED" not in script                # paths only travel in environment variables
    env = kwargs["env"]
    assert env["RED_LNK_PATH"] == str(folder / "Red.lnk")
    assert env["RED_LNK_TARGET"].endswith("pythonw.exe")
    assert env["RED_LNK_ARGS"] == f"-m red --home {Path('D:/RED')} background"
    assert env["RED_LNK_CWD"] == str(Path("D:/RED/red"))
    assert env["RED_LNK_STYLE"] == "7"
    assert "shell" not in kwargs
    hotkey_env = ps.calls[1][1]["env"]
    assert hotkey_env["RED_LNK_PATH"] == str(folder / "Red Hotkey.lnk")
    assert hotkey_env["RED_LNK_ARGS"] == f"-m red --home {Path('D:/RED')} hotkey"


def test_home_with_spaces_is_quoted(folder):
    ps = FakePowerShell()
    make(folder, ps, home=Path("C:/Users/A B/Red")).on()
    assert ps.calls[0][1]["env"]["RED_LNK_ARGS"] == f'-m red --home "{Path("C:/Users/A B/Red")}" background'
    assert ps.calls[1][1]["env"]["RED_LNK_ARGS"] == f'-m red --home "{Path("C:/Users/A B/Red")}" hotkey'


def test_on_failure_is_reported(folder):
    with pytest.raises(st.StartupError, match="boom"):
        make(folder, FakePowerShell(code=1)).on()
    with pytest.raises(st.StartupError):
        make(folder, FakePowerShell(write=False)).on()     # said OK, but no file


def test_off_and_status(folder):
    s = make(folder, FakePowerShell())
    assert "doesn't start" in s.status()
    assert "wasn't set" in s.off()
    s.on()
    assert "starts when you sign in" in s.status()
    assert s.hotkey_shortcut.is_file()
    assert "won't start" in s.off()
    assert not s.is_on() and not s.hotkey_shortcut.is_file()


def test_main_reports_errors(folder, capsys):
    assert st.main("on", Path("x"), make(folder, FakePowerShell(code=1))) == 1
    assert "error:" in capsys.readouterr().err
    assert st.main(None, Path("x"), make(folder, FakePowerShell())) == 0


def test_cli_startup_and_home_flag(monkeypatch, tmp_path):
    seen = []
    monkeypatch.setattr(st, "main", lambda action, home: seen.append((action, home)) or 0)
    monkeypatch.setenv("RED_HOME", "placeholder")   # restored by monkeypatch afterwards
    monkeypatch.setattr(cli, "connect", lambda s: (_ for _ in ()).throw(AssertionError("no LLM")))
    assert cli.main(["--home", str(tmp_path), "startup", "off"]) == 0
    assert seen == [("off", tmp_path)]
    import os
    assert os.environ["RED_HOME"] == str(tmp_path)


def test_startup_folder_is_known(monkeypatch):
    monkeypatch.setattr("red.known_folders._shell_folder_path", lambda guid: None)
    monkeypatch.setenv("APPDATA", "C:\\Users\\me\\AppData\\Roaming")
    assert st.startup_folder() == Path(
        "C:/Users/me/AppData/Roaming/Microsoft/Windows/Start Menu/Programs/Startup")
