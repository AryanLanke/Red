"""The code plugin (plan.md B2): write, fix and explain code. Fake model and window; nothing is ever run."""

import json
import os
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from red import plugins as pl  # noqa: E402
from red.tools.base import ToolError  # noqa: E402

TRAP = "import pathlib\npathlib.Path(r'{marker}').write_text('ran')\nprint('hi')\n"


@pytest.fixture(scope="module")
def code():
    loaded = {p.name: p for p in pl.load(None, builtin_dir=pl.BUILTIN_DIR)}
    assert not loaded["code"].error, loaded["code"].error
    return sys.modules["red_plugin_code"]


@pytest.fixture
def folder(tmp_path, monkeypatch, code):
    out = tmp_path / "Red Code"
    monkeypatch.setattr(code, "red_code_folder", lambda: out)
    monkeypatch.setattr(code._CodeTool, "folders", staticmethod(lambda: [out, tmp_path / "Documents"]))
    return out


class CodeLLM:
    def __init__(self, code, language="python", summary="It prints hi.", answer="It prints hi."):
        self.data = {"language": language, "summary": summary, "code": code}
        self.answer = answer
        self.calls = []

    def complete_json(self, system, user, schema, **kw):
        self.calls.append((system, user))
        if "answer" in schema["properties"]:
            return json.dumps({"answer": self.answer})
        return json.dumps(self.data)


class StreamCodeLLM(CodeLLM):
    def stream_json(self, system, user, schema, **kw):
        self.calls.append((system, user))
        raw = json.dumps(self.data)
        for i in range(0, len(raw), 7):
            yield raw[i:i + 7]


class FakeStream:
    def __init__(self):
        self.updates, self.final = [], None

    def set(self, text):
        self.updates.append(text)

    def done(self, text=None):
        self.final = text


class FakeUI:
    def __init__(self):
        self.shown = 0
        self.streams = []

    def show(self):
        self.shown += 1

    def stream(self):
        self.streams.append(FakeStream())
        return self.streams[-1]


def tool(code, name, llm, ui=None):
    cls = {"write_code": code.WriteCode, "fix_code": code.FixCode, "explain_code": code.ExplainCode}[name]
    t = cls(llm)
    if ui is not None:
        t.bind_chat(ui)
    return t


def test_the_code_plugin_ships_with_red():
    plugin = {p.name: p for p in pl.discover(None)}["code"]
    assert plugin.builtin and plugin.version


def test_write_code_streams_into_the_window_and_says_one_line(code, folder, tmp_path):
    marker = tmp_path / "ran.txt"
    llm = StreamCodeLLM(TRAP.format(marker=marker))
    ui = FakeUI()
    write = tool(code, "write_code", llm, ui)
    write.set_command("write me a script that says hi")
    reply = write.run(request="a script that says hi")
    # Where it is, what it does, what to do next (plan.md 1, Act).
    assert reply == ("Done, it's in the chat window and saved as says-hi.py in Documents, Red Code. "
                     "It prints hi. Run it with Python, or tell me what to change.")
    assert "```" not in reply and "pathlib" not in reply                 # never read aloud
    stream = ui.streams[0]
    assert ui.shown == 1 and stream.updates[0] == "Writing it..."
    assert any(u.startswith("```python\nimport pathlib") for u in stream.updates[1:])   # it grew live
    assert stream.final.startswith("It prints hi.\n```python\nimport pathlib")
    assert stream.final.endswith(f"Saved as {folder / 'says-hi.py'}")
    assert (folder / "says-hi.py").read_text(encoding="utf-8").startswith("import pathlib")
    assert not marker.exists()                                             # Red never runs it
    assert "write me a script that says hi" in llm.calls[0][1]             # the user's own words


def test_write_code_without_a_window_saves_a_new_file(code, folder):
    folder.mkdir(parents=True)
    (folder / "print-hi.py").write_text("old", encoding="utf-8")
    write = tool(code, "write_code", CodeLLM("print('hi')"))
    reply = write.run(request="print hi")
    assert reply == ("Done, I saved it as print-hi-2.py in Documents, Red Code. It prints hi. "
                     "Run it with Python, or tell me what to change.")
    assert (folder / "print-hi.py").read_text(encoding="utf-8") == "old"     # never replaced
    assert (folder / "print-hi-2.py").read_text(encoding="utf-8") == "print('hi')\n"
    assert write.last_details == "```python\nprint('hi')\n```"


@pytest.mark.parametrize("request_, language, name", [
    ("Write a code for me that adds 2 binary numbers in Python language", "python", "adds-2-binary-numbers.py"),
    ("make a PowerShell script to list big files", "powershell", "list-big-files.ps1"),
    ("write some code", "python", "red-code.py"),
    ("a web page with a red button", "html", "web-page-red-button.html"),
])
def test_the_file_is_named_after_what_the_code_does(code, request_, language, name):
    assert code.file_name_for(request_, language) == name


def test_a_window_still_gets_the_code_when_saving_fails(code, folder, monkeypatch):
    def broken(self, result, name=""):
        raise code.ToolError("disk full")
    monkeypatch.setattr(code._CodeTool, "save", broken)
    ui = FakeUI()
    reply = tool(code, "write_code", CodeLLM("print('hi')"), ui).run(request="say hi")
    assert reply.startswith("Done, it's in the chat window. I couldn't save a copy.")
    assert "print('hi')" in ui.streams[0].final


def test_a_poem_is_words_not_code(code, folder):
    llm = CodeLLM("print('rain')", answer="Rain on the window, slow and kind.")
    ui = FakeUI()
    write = tool(code, "write_code", llm, ui)
    write.set_command("write me a poem about rain")
    assert write.run(request="a poem about rain") == "Rain on the window, slow and kind."
    assert ui.streams == [] and llm.calls[0][0] == code.CREATIVE_SYSTEM
    write.set_command("write a python script that prints a poem")
    write.run(request="a script that prints a poem")
    assert ui.streams                                                      # code words win


def test_write_code_is_honest_about_broken_python(code, folder):
    ui = FakeUI()
    reply = tool(code, "write_code", CodeLLM("def f(:\n    pass"), ui).run(request="x")
    assert "syntax error" in reply
    assert "doesn't parse yet, line 1" in ui.streams[0].final


def test_fences_from_the_model_are_stripped(code, folder):
    ui = FakeUI()
    tool(code, "write_code", CodeLLM("```python\nprint(1)\n```"), ui).run(request="x")
    assert ui.streams[0].final.count("```") == 2


def test_fix_from_the_clipboard_goes_to_the_window(code, folder, monkeypatch):
    monkeypatch.setattr(code._CodeTool, "read_clipboard", staticmethod(lambda: "prnt('hi')"))
    llm = StreamCodeLLM("print('hi')", summary="print was misspelled.")
    ui = FakeUI()
    reply = tool(code, "fix_code", llm, ui).run()
    assert reply == "Fixed version, it's in the chat window. print was misspelled."
    assert "prnt('hi')" in llm.calls[0][1] and ui.streams[0].final.endswith("print('hi')\n```")


def test_fix_a_named_file_never_changes_it(code, folder):
    folder.mkdir(parents=True)
    script = folder / "rename.py"
    script.write_text("prnt(1)\n", encoding="utf-8")
    tool(code, "fix_code", CodeLLM("print(1)"), FakeUI()).run(source="rename.py", problem="it crashes")
    assert script.read_text(encoding="utf-8") == "prnt(1)\n"


def test_explain_reads_and_answers(code, folder, monkeypatch):
    monkeypatch.setattr(code._CodeTool, "read_clipboard", staticmethod(lambda: "print('hi')"))
    llm = CodeLLM("", answer="It prints hi to the console.")
    assert tool(code, "explain_code", llm).run(source="what I copied") == "It prints hi to the console."
    assert "print('hi')" in llm.calls[0][1]


@pytest.mark.parametrize("source, error", [("clipboard", "clipboard is empty"),
                                           ("nothere.py", "couldn't find nothere.py")])
def test_nothing_to_read(code, folder, monkeypatch, source, error):
    monkeypatch.setattr(code._CodeTool, "read_clipboard", staticmethod(lambda: "  "))
    with pytest.raises(ToolError, match=error):
        tool(code, "explain_code", CodeLLM("")).run(source=source)


def test_no_model_says_so(code, folder):
    with pytest.raises(ToolError, match="local model"):
        tool(code, "write_code", None).run(request="x")


def test_helpers(code, tmp_path):
    assert code.strip_fences("```py\nx = 1\n```") == "x = 1"
    assert code.syntax_problem("x = (", "python").startswith("line 1")
    assert code.syntax_problem("x = 1", "python") == ""
    assert code.syntax_problem("Get-ChildItem (", "powershell") == ""
    (tmp_path / "a.py").write_text("")
    assert code.free_path(tmp_path, "a.py").name == "a-2.py"


# --- the window shows the stream -----------------------------------------------------

def test_the_chat_window_streams_a_bubble():
    from PySide6.QtWidgets import QApplication

    from red import chat_window as cw
    QApplication.instance() or QApplication([])
    ui = cw.ChatUI(lambda text: "")
    stream = ui.stream()
    stream.set("Writing it...")
    stream.done("Done.\n```python\nprint(1)\n```")
    QApplication.processEvents()
    bubble = ui.window.bubbles[-1]
    blocks = [w for w in bubble.findChildren(object) if hasattr(w, "code")]
    assert len(ui.window.bubbles) == 1 and [b.code for b in blocks] == ["print(1)"]


def test_saving_offers_vs_code(tmp_path):
    from PySide6.QtWidgets import QApplication

    from red import chat_window as cw
    QApplication.instance() or QApplication([])
    opened = []
    window = cw.window_class()(save_path=lambda s: str(tmp_path / "x.py"),
                               open_file=lambda p: opened.append(p) or True)
    window.add(cw.Line("red", "```python\nprint(1)\n```"))
    block = [w for w in window.bubbles[0].findChildren(object) if hasattr(w, "code")][0]
    window.save_code(block)
    block.open_button.click()
    assert opened == [tmp_path / "x.py"]
