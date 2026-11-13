"""The chat window (plan.md A4): offscreen Qt, fake router and tools, no keyboard hook, no audio."""

import json
import os
import threading
from datetime import datetime
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from red import chat_window as cw  # noqa: E402
from red.chat import Chat  # noqa: E402
from red.executor import Executor  # noqa: E402
from red.router import Route  # noqa: E402
from red.tools.base import Tool, ToolRegistry  # noqa: E402

NOW = datetime(2026, 11, 13, 20, 0)


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def texts(window):
    from PySide6.QtWidgets import QLabel
    out = []
    for bubble in window.bubbles:
        for i in range(bubble.box.count()):
            w = bubble.box.itemAt(i).widget()
            if isinstance(w, QLabel):
                out.append((bubble.who, w.text()))
            elif hasattr(w, "code"):
                out.append((bubble.who, f"<code {w.language}>{w.code}"))
    return out


# --- text helpers ---------------------------------------------------------------------

def test_split_code():
    text = "Here you go:\n```python\nprint('hi')\n```\nRun it yourself."
    assert cw.split_code(text) == [("text", "Here you go:", ""), ("code", "print('hi')", "python"),
                                   ("text", "Run it yourself.", "")]
    assert cw.split_code("no code") == [("text", "no code", "")]
    assert cw.split_code("```\nunclosed") == [("code", "unclosed", "")]


@pytest.mark.parametrize("language, n, name", [("python", 1, "red-code.py"), ("PowerShell", 1, "red-code.ps1"),
                                               ("", 2, "red-code-2.txt"), ("weird lang", 1, "red-code.txt")])
def test_code_filename(language, n, name):
    assert cw.code_filename(language, n) == name


@pytest.mark.parametrize("line, who, text", [
    ("You said: open Edge", "you", "open Edge"),
    ("Red: Opening Edge.", "red", "Opening Edge."),
    ("Red (hello): Morning, Aryan!", "red", "Morning, Aryan!"),
    ("Red (reminder): Call mom.", "red", "Call mom."),
    ("  Red asks: Shut down now?", "red", "Shut down now?"),
    ("     Red: 2 unpushed commits", "details", "Red: 2 unpushed commits"),
])
def test_the_voice_loops_lines_show_up(line, who, text):
    shown = cw.parse_out(line)
    assert shown.who == who and shown.text == text


@pytest.mark.parametrize("line", ["Ready. Press Ctrl+Alt+R, then speak. Ctrl+C quits.", "", "Red: ",
                                  "The wake word isn't available"])
def test_status_lines_dont(line):
    assert cw.parse_out(line) is None


def test_the_voice_loop_still_prints_what_the_window_reads():
    """The window mirrors spoken turns from these exact prints in red/__main__.py."""
    from pathlib import Path
    source = (Path(cw.__file__).parent / "__main__.py").read_text(encoding="utf-8")
    for printed in ('self.out(f"You said: {text}")', 'self.out(f"Red: {last}")',
                    'self.out(f"Red ({label}): {text}")', 'self.out(f"  Red asks: {question}")'):
        assert printed in source


# --- the window -----------------------------------------------------------------------

def test_messages_code_and_details(qapp):
    window = cw.window_class()()
    window.add(cw.Line("you", "write me a hello world"))
    window.add(cw.Line("red", "Here you go:\n```python\nprint('hello')\n```"))
    window.add(cw.Line("details", "saved nowhere yet"))
    assert texts(window) == [("you", "write me a hello world"), ("red", "Here you go:"),
                             ("red", "<code python>print('hello')"), ("red", "saved nowhere yet")]
    assert len(window.bubbles) == 2                       # details join Red's last bubble


def test_copy_and_save(qapp, tmp_path):
    class Clip:
        text = ""

        def setText(self, text):  # noqa: N802 - Qt's name
            Clip.text = text
    asked = []
    window = cw.window_class()(clipboard=Clip(), save_path=lambda s: asked.append(s) or str(tmp_path / "x.py"))
    window.add(cw.Line("red", "```python\nprint(1)\n```\n```python\nprint(2)\n```"))
    first, second = [w for w in window.bubbles[0].findChildren(object) if hasattr(w, "code")][:2]
    first.copy_button.click()
    assert Clip.text == "print(1)" and window.status.text() == "Copied."
    second.save_button.click()
    assert (tmp_path / "x.py").read_text(encoding="utf-8") == "print(2)\n"
    assert asked[0].endswith(os.path.join("Red Code", "red-code-2.py"))
    assert window.status.text() == "Saved x.py."


def test_save_cancelled_writes_nothing(qapp):
    window = cw.window_class()(save_path=lambda s: None)
    window.add(cw.Line("red", "```\nx\n```"))
    block = [w for w in window.bubbles[0].findChildren(object) if hasattr(w, "code")][0]
    assert window.save_code(block) is None and window.saved == []


def test_typing_sends_and_clears(qapp):
    window = cw.window_class()()
    got = []
    window.submitted.connect(got.append)
    window.input.setPlainText("  hello there  ")
    window._send_typed()
    assert got == ["hello there"] and window.input.toPlainText() == ""
    assert texts(window) == [("you", "hello there")]


def test_a_draft_has_send(qapp):
    window = cw.window_class()()
    fired = []
    window.action.connect(lambda tool, args, said: fired.append((tool, args, said)))
    window.add(cw.Line("red", "To: Rahul\nSubject: Late\n\nRunning 10 minutes late.",
                       action=("send_mail", {"to": "Rahul", "subject": "Late", "body": "Running late."})))
    button = window.bubbles[0].action_button
    button.click()
    assert fired == [("send_mail", {"to": "Rahul", "subject": "Late", "body": "Running late."}, "send it")]
    assert not button.isEnabled()                           # one click, one send


def test_the_window_has_no_edge_line(qapp):
    """Frosted glass with no rim: the outermost pixel row is the same glass as just inside it."""
    window = cw.window_class()()
    window.resize(cw.WIDTH, cw.HEIGHT)
    image = window.grab().toImage()
    y = cw.HEIGHT // 2
    edge, inside = image.pixelColor(0, y), image.pixelColor(3, y)
    assert abs(edge.red() - inside.red()) <= 2 and abs(edge.alpha() - inside.alpha()) <= 2
    assert edge.lightness() > 200                           # milky, not dark


def test_old_bubbles_go(qapp, monkeypatch):
    monkeypatch.setattr(cw, "MAX_MESSAGES", 5)
    window = cw.window_class()()
    for i in range(8):
        window.add(cw.Line("you", f"line {i}"))
    assert len(window.bubbles) == 5 and texts(window)[0] == ("you", "line 3")


# --- ChatUI: any thread in, Qt thread out --------------------------------------------

def test_chat_ui_shows_feeds_and_answers(qapp):
    from PySide6.QtWidgets import QApplication
    done = threading.Event()

    def answer(text):
        done.set()
        return f"echo: {text}"
    ui = cw.ChatUI(answer)
    ui.feed("You said: open Edge")
    ui.feed("Red: Opening Edge.")
    ui.feed("Ready. Press Ctrl+Alt+R")
    QApplication.processEvents()
    window = ui.window
    assert texts(window) == [("you", "open Edge"), ("red", "Opening Edge.")]
    ui.show()
    QApplication.processEvents()
    assert window.isVisible()
    window.input.setPlainText("hi")
    window._send_typed()
    assert done.wait(2)
    for _ in range(50):
        QApplication.processEvents()
        if len(window.bubbles) == 4:
            break
        threading.Event().wait(0.02)
    assert texts(window)[-2:] == [("you", "hi"), ("red", "echo: hi")]
    ui.toggle()
    QApplication.processEvents()
    assert not window.isVisible()


# --- typed turns ----------------------------------------------------------------------

class Echo(Tool):
    name = "echo"
    description = "echo"
    args_schema = {"type": "object", "properties": {"text": {"type": "string"}}}

    def run(self, text=""):
        return f"Echo {text}."


class Danger(Tool):
    name = "danger"
    description = "danger"
    destructive = True
    args_schema = {"type": "object", "properties": {}}

    def run(self):
        return "Boom."


class ChatLLM:
    def complete_json(self, system, user, schema, **kw):
        return json.dumps({"reply": "Ha, nice."})


class FakeRouter:
    def __init__(self, routes):
        self.routes = routes
        self.contexts = []

    def route_many(self, text, context=""):
        self.contexts.append(context)
        return [(text, r) for r in self.routes.get(text, [Route("none", {"reply": "?"}, False)])]


def make_app(routes, answers=("yes",)):
    import red.__main__ as main
    answers = list(answers)
    registry = ToolRegistry([Echo(), Danger()])
    asked = []
    executor = Executor(registry, ask=lambda q, t: asked.append(q) or answers.pop(0))
    voice_app = type("VoiceApp", (SimpleNamespace,), {"__module__": main.__name__})
    return voice_app(chat=Chat(ChatLLM(), now=lambda: NOW), router=FakeRouter(routes),
                     executor=executor, _turn=threading.RLock(), asked=asked)


def test_a_typed_command_runs_like_a_spoken_one():
    app = make_app({"echo hi": [Route("echo", {"text": "hi"}, False)]})
    assert cw.typed_turn(app, "echo hi") == "Echo hi."
    assert app.chat.history() == "User: echo hi\nRed: Echo hi."


def test_typed_chat_and_spoken_share_one_conversation():
    app = make_app({})
    app.chat.remember("open Edge", "Opening Edge.")            # said aloud a moment ago
    assert cw.typed_turn(app, "how are you doing today") == "Ha, nice."
    assert "User: open Edge" in app.router.contexts[0]         # the router saw the spoken turn
    assert app.chat.history().endswith("User: how are you doing today\nRed: Ha, nice.")


def test_typed_destructive_still_asks():
    app = make_app({"danger": [Route("danger", {}, True)]}, answers=["no"])
    assert cw.typed_turn(app, "danger") == "Cancelled."
    assert app.asked == ["Danger?"]


def test_typed_small_talk_and_names(tmp_path):
    from red.memory import Memory
    app = make_app({})
    app.chat.memory = Memory(tmp_path)
    assert cw.typed_turn(app, "call me Ari") == "Ari. Got it, nice to meet you properly."
    assert cw.typed_turn(app, "thanks") == "Anytime!"
    assert cw.typed_turn(app, "   ") == ""


def test_a_button_runs_through_the_executor_and_asks():
    app = make_app({}, answers=["yes"])
    assert cw.run_action(app, "danger", {}, "send it") == "Boom."
    assert app.asked == ["Danger?"]


# --- open chat, attach ------------------------------------------------------------------

def test_open_chat_tool():
    from red.tools.base import ToolError
    from red.tools.chat import OpenChat
    tool = OpenChat()
    with pytest.raises(ToolError):
        tool.run()
    shown = []
    tool.bind_chat_window(lambda: shown.append(1))
    assert tool.run() == "Here you go." and shown == [1]


def test_open_chat_is_registered():
    from red.tools import default_registry
    assert "open_chat" in default_registry(google=False)


def test_attach_wires_the_out_lines_tools_and_hotkey(qapp, monkeypatch):
    from PySide6.QtWidgets import QApplication

    from red.tools.chat import OpenChat
    hooked = []
    monkeypatch.setattr(cw, "start_hotkey", lambda hotkey, cb: hooked.append(hotkey) or SimpleNamespace(stop=lambda: None))
    printed = []
    tool = OpenChat()
    app = make_app({})
    app.out = printed.append
    app.settings = SimpleNamespace(chat_hotkey="<ctrl>+<alt>+<space>")
    app.executor.registry = ToolRegistry([tool])
    ui = cw._attach_chat_window(app)
    assert ui is not None and hooked == ["<ctrl>+<alt>+<space>"]
    app.out("You said: hello")
    assert printed == ["You said: hello"]                     # still printed as before
    QApplication.processEvents()
    assert texts(ui.window) == [("you", "hello")]
    tool.run()
    QApplication.processEvents()
    assert ui.window.isVisible()
    ui.window.hide()


def test_chat_hotkey_setting(tmp_path, monkeypatch):
    from red.config import load_settings
    monkeypatch.delenv("RED_CHAT_HOTKEY", raising=False)
    assert load_settings(tmp_path).chat_hotkey == "<ctrl>+<alt>+<space>"
    monkeypatch.setenv("RED_CHAT_HOTKEY", "off")
    assert load_settings(tmp_path).chat_hotkey is None
