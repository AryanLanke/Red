"""The coding plugin (plan.md B3.1): fake desk and git; no app opens, no key is pressed."""

import sys
from pathlib import Path

import pytest

from red import plugins as pl
from red.tools.base import ToolError


@pytest.fixture(scope="module")
def coding():
    loaded = {p.name: p for p in pl.load(None, builtin_dir=pl.BUILTIN_DIR)}
    assert not loaded["coding"].error, loaded["coding"].error
    return sys.modules["red_plugin_coding"]


class FakeDesk:
    def __init__(self, front=True, foreground="qoder.exe"):
        self.log = []
        self.front, self.foreground = front, foreground

    def launch(self, args, cwd=None):
        self.log.append(("launch", args))
        return 1

    def front_app(self, exes, wait=8.0, title=""):
        self.log.append(("front", sorted(exes)))
        return self.front

    def set_clipboard(self, text):
        self.log.append(("clipboard", text))

    def press(self, combo):
        self.log.append(("press", combo))

    def foreground_exe(self):
        return self.foreground


@pytest.fixture
def world(coding, tmp_path, monkeypatch):
    red = tmp_path / "red"
    (red / "docs").mkdir(parents=True)
    (red / "plan.md").write_text("x")
    (red / "docs" / "notes.md").write_text("x")
    exe = tmp_path / "Qoder.exe"
    exe.write_text("")
    code = tmp_path / "Code.exe"
    code.write_text("")
    coders = {
        "qoder": coding.Coder("qoder", "Qoder", exe, ["qoder"], True, True, "", {"qoder.exe"}),
        "vscode": coding.Coder("vscode", "VS Code", code, ["vs code", "vscode"], True, True,
                               "ctrl+alt+i", {"code.exe"}),
        "freebuff": coding.Coder("freebuff", "Freebuff", exe, ["freebuff"], False, False, "",
                                 {"freebuff.exe"}),
        "ghost": coding.Coder("ghost", "Ghost", None, ["ghost"]),
    }
    monkeypatch.setattr(coding._CodingTool, "coders", staticmethod(lambda: coders))
    monkeypatch.setattr(coding._CodingTool, "repos", staticmethod(lambda: {"red": red}))
    monkeypatch.setattr(coding, "handoffs_path", lambda: tmp_path / "handoffs.json")
    monkeypatch.setattr(coding, "_git", lambda folder, *a, **k: "abc123\n")
    return {"red": red, "qoder": exe, "code": code, "coders": coders}


def test_open_a_project_in_qoder(coding, world):
    desk = FakeDesk()
    tool = coding.OpenInCodingTool(desk)
    assert tool.run(tool="Qoder", project="Red") == "Opening red in Qoder."
    assert desk.log == [("launch", [str(world["qoder"]), str(world["red"])])]
    tool.take_later()()
    assert desk.log[-1] == ("front", ["qoder.exe"])


def test_open_a_file_at_a_line(coding, world):
    desk = FakeDesk()
    reply = coding.OpenInCodingTool(desk).run(tool="vs code", file="notes.md", line=40)
    assert reply == "Opening notes.md at line 40 in VS Code."
    assert desk.log[0] == ("launch", [str(world["code"]), "--goto",
                                      f"{world['red'] / 'docs' / 'notes.md'}:40"])


def test_a_tool_without_folders(coding, world):
    desk = FakeDesk()
    reply = coding.OpenInCodingTool(desk).run(tool="freebuff", project="red")
    assert "doesn't take a folder" in reply and desk.log[0] == ("launch", [str(world["qoder"])])


@pytest.mark.parametrize("args, error", [
    ({"tool": "notepad++"}, "don't know a coding tool"),
    ({"tool": "ghost"}, "doesn't seem to be installed"),
    ({"tool": "qoder", "project": "website"}, "The ones in repos.toml: red"),
    ({"tool": "qoder", "file": "missing.py"}, "couldn't find missing.py"),
    ({"tool": "qoder", "file": "..\\secret.txt"}, "inside one of your projects"),
    ({"tool": "qoder", "file": "C:\\Windows\\win.ini"}, "inside one of your projects"),
])
def test_only_known_tools_projects_and_files(coding, world, args, error):
    desk = FakeDesk()
    with pytest.raises(ToolError, match=error):
        coding.OpenInCodingTool(desk).run(**args)
    assert desk.log == []                                   # nothing launched


def test_hand_off_reads_back_and_pastes_without_a_shortcut(coding, world):
    from red.executor import Executor
    from red.router import Route
    from red.tools.base import ToolRegistry
    desk = FakeDesk()
    tool = coding.TellCodingAgent(desk)
    asked = []
    executor = Executor(ToolRegistry([tool]), ask=lambda q, t: asked.append(q) or "yes")
    reply = executor.execute("tell qoder to fix the tests in red",
                             Route("tell_coding_agent", {"tool": "qoder", "task": "fix the failing tests",
                                                         "project": "red"}, True))
    assert asked == ['Tell Qoder in red: "fix the failing tests"?']
    assert "on your clipboard" in reply
    assert ("clipboard", "fix the failing tests") in desk.log
    assert not any(kind == "press" for kind, _ in desk.log)      # no shortcut known: no keys


def test_the_project_is_found_in_the_task(coding, world):
    desk = FakeDesk()
    tool = coding.TellCodingAgent(desk)
    assert tool.describe(tool="qoder", task="fix the failing tests in Red") == \
        'Tell Qoder in red: "fix the failing tests in Red"'
    tool.run(tool="qoder", task="fix the failing tests in Red")
    assert desk.log[0] == ("launch", [str(world["qoder"]), str(world["red"])])
    assert tool.project_in("make it faster in general") == ""


def test_a_no_sends_nothing(coding, world):
    from red.executor import Executor
    from red.router import Route
    from red.tools.base import ToolRegistry
    desk = FakeDesk()
    executor = Executor(ToolRegistry([coding.TellCodingAgent(desk)]), ask=lambda q, t: "no")
    assert executor.execute("x", Route("tell_coding_agent", {"tool": "qoder", "task": "do it"}, True)) == "Cancelled."
    assert desk.log == []


def test_hand_off_with_a_chat_shortcut_presses_enter_only_in_front(coding, world):
    desk = FakeDesk(foreground="code.exe")
    reply = coding.TellCodingAgent(desk).run(tool="vs code", task="explain this repo", project="red")
    assert reply.startswith("Told VS Code.")
    assert [x for x in desk.log if x[0] == "press"] == [("press", "ctrl+alt+i"), ("press", "ctrl+v"),
                                                        ("press", "enter")]
    desk = FakeDesk(foreground="chrome.exe")
    reply = coding.TellCodingAgent(desk).run(tool="vs code", task="explain this repo")
    assert "didn't press Enter" in reply and ("press", "enter") not in desk.log


def test_hand_off_when_the_window_never_shows(coding, world):
    desk = FakeDesk(front=False)
    reply = coding.TellCodingAgent(desk).run(tool="qoder", task="fix it")
    assert "didn't come up" in reply and ("clipboard", "fix it") in desk.log


def test_what_did_it_change(coding, world, monkeypatch):
    calls = []

    def git(folder, *args, **kw):
        calls.append(args)
        if args[0] == "rev-parse":
            return "abc123\n"
        if args[0] == "status":
            return " M red/chat.py\n?? red/new.py\n"
        if args[0] == "diff":
            return " 2 files changed, 40 insertions(+), 3 deletions(-)\n"
        return "fix the failing tests\nadd a test\n"
    monkeypatch.setattr(coding, "_git", git)
    coding.remember_handoff("red", world["red"], git=git)
    tool = coding.WhatDidItChange(FakeDesk())
    monkeypatch.setattr(tool, "git", git)
    reply = tool.run()
    assert reply == ('In red since the hand-off: 2 files changed and not committed, 40 lines added and '
                     '3 removed. 2 new commits: "fix the failing tests"; "add a test".')
    assert ("log", "--format=%s", "abc123..HEAD") in calls
    assert all(c[0] in ("rev-parse", "status", "diff", "log") for c in calls)   # read-only git


def test_nothing_changed(coding, world, monkeypatch):
    tool = coding.WhatDidItChange(FakeDesk())
    monkeypatch.setattr(tool, "git", lambda folder, *a, **k: "")
    assert tool.run(project="red") == "Nothing's changed in red in the last few hours."


def test_allowlist_coding_table(coding, tmp_path):
    exe = tmp_path / "Cursor.exe"
    exe.write_text("")
    allow = tmp_path / "allowlist.toml"
    allow.write_text(f"[coding.cursor]\nlabel = 'Cursor'\nexe = '{exe}'\naliases = ['cursor']\n"
                     "[coding.qoder]\nchat_key = 'ctrl+l'\n", encoding="utf-8")
    coders = coding.load_coders(allow)
    assert coders["cursor"].exe == exe and coders["cursor"].exes == {"cursor.exe"}
    assert coders["qoder"].chat_key == "ctrl+l"
    allow.write_text("[coding.qoder]\nchat_key = 'ctrl+banana'\n", encoding="utf-8")
    with pytest.raises(ValueError):
        coding.load_coders(allow)


def test_this_pcs_tools_are_found(coding):
    found = {k: c.exe for k, c in coding.builtin_coders().items()}
    assert set(found) == {"vscode", "qoder", "antigravity", "antigravity-app", "freebuff"}
    for exe in found.values():
        assert exe is None or Path(exe).is_file()


def test_keys_parse():
    from red.desk import parse_keys
    assert parse_keys("ctrl+alt+i") == [0x11, 0x12, ord("I")]
    assert parse_keys("Enter") == [0x0D]
    with pytest.raises(ValueError):
        parse_keys("ctrl+banana")
