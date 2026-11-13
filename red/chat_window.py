"""The chat window (plan.md A4): type to Red, and see code, drafts and tool results.

Open it with Ctrl+Alt+Space (RED_CHAT_HOTKEY) or by saying "open chat". It
holds one conversation with the voice loop: what you say aloud and what you
type land in the same `Chat`, so "what did I just ask?" works either way.

- Typed turns go through the same router, tools and confirmations as spoken
  ones (`typed_turn`), on a worker thread; the reply shows up as text and
  isn't spoken.
- Spoken turns appear too: the voice loop's own lines ("You said: ...",
  "Red: ...") are mirrored in (`ChatUI.feed`), so nothing in the listener changes.
- Code in a reply (``` fences) gets Copy and Save buttons. Save opens a dialog
  in Documents\\Red Code that asks before replacing a file. Red never runs it.
- A mail draft gets a Send button; sending still goes through the tool's
  read-back (the Executor asks once).

The look follows the glow rules: frosted, milky glass, no rim line, no outline,
square corners.
"""

from __future__ import annotations

import logging
import re
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

log = logging.getLogger(__name__)

DEFAULT_CHAT_HOTKEY = "<ctrl>+<alt>+<space>"
WIDTH, HEIGHT = 440, 640
MAX_MESSAGES = 200                 # older bubbles are dropped from the window (not from memory)

# Glass: milky white, a breath of the glow's colours at the top, no edge line.
GLASS = (246, 246, 250, 242)
GLASS_TINT = ("#bf5af2", "#5e5ce6", "#64d2ff")
INK = "#1d1d24"
MUTED = "#6b6b78"
YOU_FILL = "rgba(94, 92, 230, 0.13)"
RED_FILL = "rgba(255, 255, 255, 0.72)"
CODE_FILL = "rgba(29, 29, 36, 0.92)"
ACCENT = "#5e5ce6"


# --- text -----------------------------------------------------------------------------

_FENCE = re.compile(r"```[ \t]*([\w+#.-]*)[ \t]*\n(.*?)(?:```|\Z)", re.S)

EXTENSIONS = {"python": "py", "py": "py", "powershell": "ps1", "ps1": "ps1", "javascript": "js",
              "js": "js", "typescript": "ts", "ts": "ts", "html": "html", "css": "css",
              "json": "json", "bash": "sh", "sh": "sh", "batch": "bat", "bat": "bat", "cmd": "cmd",
              "c": "c", "cpp": "cpp", "c++": "cpp", "csharp": "cs", "cs": "cs", "java": "java",
              "go": "go", "rust": "rs", "rs": "rs", "sql": "sql", "yaml": "yaml", "toml": "toml",
              "markdown": "md", "md": "md", "text": "txt", "": "txt"}


def split_code(text: str) -> list[tuple[str, str, str]]:
    """'Here: ```python\\nprint(1)\\n``` done' -> [("text", "Here:", ""), ("code", "print(1)", "python"), ...]."""
    parts: list[tuple[str, str, str]] = []
    pos = 0
    for m in _FENCE.finditer(text):
        before = text[pos:m.start()].strip()
        if before:
            parts.append(("text", before, ""))
        parts.append(("code", m.group(2).rstrip("\n"), m.group(1).lower()))
        pos = m.end()
    rest = text[pos:].strip()
    if rest:
        parts.append(("text", rest, ""))
    return parts


def code_filename(language: str, n: int = 1) -> str:
    ext = EXTENSIONS.get(language.lower(), language.lower() if language.isalnum() else "txt")
    return f"red-code-{n}.{ext}" if n > 1 else f"red-code.{ext}"


def vscode_exe() -> Path | None:
    """VS Code's Code.exe, found from code.cmd on PATH (the file VS Code's installer adds)."""
    import shutil
    cmd = shutil.which("code.cmd") or shutil.which("code")
    if not cmd:
        return None
    exe = Path(cmd).resolve().parent.parent / "Code.exe"
    return exe if exe.is_file() else None


def open_in_vscode(path: Path) -> bool:
    """Open a file the user saved in VS Code: Code.exe with the path as one argument, no shell."""
    import subprocess
    exe = vscode_exe()
    if exe is None or not Path(path).is_file():
        return False
    subprocess.Popen([str(exe), str(Path(path).resolve())], close_fds=True)
    return True


def red_code_folder() -> Path:
    """Documents\\Red Code (Documents wherever Windows keeps it)."""
    try:
        from .known_folders import known_folder
        documents = known_folder("documents")
    except Exception:  # noqa: BLE001
        documents = None
    return (documents or Path.home() / "Documents") / "Red Code"


@dataclass
class Line:
    """One thing to show: who said it, the text, and for a draft what Send runs."""
    who: str                              # "you", "red", "details"
    text: str
    action: tuple[str, dict] | None = None   # (tool, args) for a Send button
    action_label: str = "Send"
    extra: dict = field(default_factory=dict)


_YOU = re.compile(r"^You said: (.*)$", re.S)
_RED = re.compile(r"^(?:  )?Red(?: \((?:reminder|hello)\))?(?: asks)?: (.*)$", re.S)
_DETAIL = re.compile(r"^ {5}(\S.*)$", re.S)


def parse_out(line: str) -> Line | None:
    """A line the voice loop prints, as something to show (None for status lines)."""
    for pattern, who in ((_YOU, "you"), (_RED, "red"), (_DETAIL, "details")):
        m = pattern.match(line)
        if m and m.group(1).strip():
            return Line(who, m.group(1).strip())
    return None


# --- typed turns ------------------------------------------------------------------------

def typed_turn(app, text: str) -> str:
    """Run one typed message like a spoken one (same router, tools, Chat), and return the reply.

    `app` is the running VoiceApp. The reply isn't spoken; confirmations still ask.
    """
    from .executor import run_later
    from .smalltalk import dismissal_reply, is_filler, quick_reply
    main = sys.modules[type(app).__module__]          # red.__main__ (or __main__ under -m)
    text = " ".join(text.split())
    if not text or is_filler(text):
        return ""
    chat, router, executor = app.chat, app.router, app.executor
    with app._turn:
        named = chat.take_name(text)
        if named is not None:
            return named
        quick = dismissal_reply(text) or quick_reply(text, name=chat.user_name())
        if quick is not None:
            chat.remember(text, quick)
            return quick
        try:
            talk_only = getattr(main, "talk_only", None)
            if talk_only is not None and talk_only(text, None, getattr(app, "settings", None)):
                from .router import Router
                steps = [(text, Router.talk_route())]           # plain talk: straight to Chat
            else:
                steps = router.route_many(text, context=chat.history(getattr(main, "CONTEXT_LINES", 6)))
        except Exception as e:  # noqa: BLE001 - RouteError, LLMError
            log.warning("Couldn't route typed %r: %s", text, e)
            return "Sorry, I didn't get that. Could you put it another way?"
        if len(steps) > 1:
            done = []
            for part, route in steps:
                reply = executor.execute(part, route)
                run_later(executor.last_later)
                executor.last_later = None
                done.append((part, reply, executor.last_status))
                if executor.last_status in ("error", "cancelled"):
                    break
                chat.remember(part, reply)
            return main.steps_reply(done, len(steps))
        route = steps[0][1]
        logging.getLogger("red.commands").info("%r (typed) -> %s", text, route.to_json())
        reply = executor.execute(text, route, talk=lambda said, fallback: chat.reply(said, fallback=fallback))
        run_later(executor.last_later)
        executor.last_later = None
        if not route.is_none:
            chat.remember(text, reply)
        details = executor.last_details.strip()
        return f"{reply}\n{details}" if details else reply


def run_action(app, tool: str, args: dict, said: str) -> str:
    """A button in the window (a draft's Send): the tool runs through the Executor, so it asks first."""
    from .router import Route
    with app._turn:
        tool_obj = app.executor.registry.get(tool) if tool in app.executor.registry else None
        destructive = bool(getattr(tool_obj, "destructive", False))
        reply = app.executor.execute(said, Route(tool=tool, args=dict(args), destructive=destructive))
        app.chat.remember(said, reply)
        return reply


# --- the window (Qt thread only) --------------------------------------------------------

def _qt():
    from PySide6 import QtCore, QtGui, QtWidgets
    return QtCore, QtGui, QtWidgets


def frost(hwnd: int) -> None:
    """Square corners and a blur behind the window (Windows 10/11). Best effort, signed APIs."""
    if sys.platform != "win32" or not hwnd:
        return
    import ctypes
    from ctypes import wintypes
    try:
        corner = ctypes.c_int(1)                                        # DWMWCP_DONOTROUND
        ctypes.windll.dwmapi.DwmSetWindowAttribute(wintypes.HWND(hwnd), 33, ctypes.byref(corner),
                                                   ctypes.sizeof(corner))
    except (AttributeError, OSError):
        pass
    try:
        class ACCENT(ctypes.Structure):
            _fields_ = [("state", ctypes.c_int), ("flags", ctypes.c_int),
                        ("color", ctypes.c_uint), ("animation", ctypes.c_int)]

        class DATA(ctypes.Structure):
            _fields_ = [("attribute", ctypes.c_int), ("data", ctypes.c_void_p),
                        ("size", ctypes.c_size_t)]
        accent = ACCENT(3, 0, 0, 0)                                     # ACCENT_ENABLE_BLURBEHIND
        data = DATA(19, ctypes.cast(ctypes.byref(accent), ctypes.c_void_p), ctypes.sizeof(accent))
        ctypes.windll.user32.SetWindowCompositionAttribute(wintypes.HWND(hwnd), ctypes.byref(data))
    except (AttributeError, OSError):
        pass


def make_window_class():
    """The ChatWindow class, built on first use so importing this module needs no Qt."""
    QtCore, QtGui, QtWidgets = _qt()
    Qt = QtCore.Qt

    flat = ("QPushButton {{ border: none; background: {bg}; color: {fg}; padding: 4px 10px; "
            "font-weight: 600; }} QPushButton:hover {{ background: {hover}; }}")

    class Bubble(QtWidgets.QFrame):
        def __init__(self, who: str, parent=None):
            super().__init__(parent)
            self.who = who
            fill = {"you": YOU_FILL, "red": RED_FILL}.get(who, "transparent")
            self.setObjectName("bubble")
            self.setStyleSheet(f"#bubble {{ background: {fill}; border: none; }}")
            self.box = QtWidgets.QVBoxLayout(self)
            self.box.setContentsMargins(12, 8, 12, 8)
            self.box.setSpacing(6)

    class CodeBlock(QtWidgets.QFrame):
        def __init__(self, code: str, language: str, window, parent=None):
            super().__init__(parent)
            self.code, self.language = code, language
            self.setObjectName("code")
            self.setStyleSheet(f"#code {{ background: {CODE_FILL}; border: none; }}")
            box = QtWidgets.QVBoxLayout(self)
            box.setContentsMargins(10, 6, 10, 10)
            head = QtWidgets.QHBoxLayout()
            label = QtWidgets.QLabel(language or "code")
            label.setStyleSheet("color: #b9b9c6; font-size: 11px;")
            head.addWidget(label, 1)
            style = flat.format(bg="transparent", fg="#e6e6f0", hover="rgba(255,255,255,0.12)")
            self.copy_button = QtWidgets.QPushButton("Copy")
            self.copy_button.setStyleSheet(style)
            self.copy_button.clicked.connect(lambda: window.copy_code(self))
            self.save_button = QtWidgets.QPushButton("Save")
            self.save_button.setStyleSheet(style)
            self.save_button.clicked.connect(lambda: window.save_code(self))
            head.addWidget(self.copy_button)
            head.addWidget(self.save_button)
            box.addLayout(head)
            text = QtWidgets.QPlainTextEdit()
            text.setPlainText(code)
            text.setReadOnly(True)
            text.setLineWrapMode(QtWidgets.QPlainTextEdit.LineWrapMode.NoWrap)   # code keeps its lines
            text.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
            text.setStyleSheet("QPlainTextEdit { background: transparent; border: none; color: #f2f2f7; "
                               "font-family: Consolas, 'Cascadia Mono', monospace; font-size: 12px; }"
                               "QScrollBar { height: 6px; width: 6px; background: transparent; }"
                               "QScrollBar::handle { background: rgba(255,255,255,0.25); }"
                               "QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }")
            rows = min(code.count("\n") + 1, 18)
            line = QtGui.QFontMetrics(text.font()).lineSpacing()
            text.setFixedHeight(int(rows * (line + 1) + 20))
            box.addWidget(text)
            self.view = text

    class Input(QtWidgets.QPlainTextEdit):
        submit = QtCore.Signal()

        def keyPressEvent(self, event):  # noqa: N802 - Qt's name
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not (
                    event.modifiers() & Qt.KeyboardModifier.ShiftModifier):
                self.submit.emit()
                return
            super().keyPressEvent(event)

    class ChatWindow(QtWidgets.QWidget):
        submitted = QtCore.Signal(str)           # the user typed something
        action = QtCore.Signal(str, dict, str)   # a button: tool, args, what it stands for

        def __init__(self, *, save_path: Callable[[str], str | None] | None = None,
                     clipboard=None, open_file: Callable[[Path], bool] | None = open_in_vscode,
                     parent=None):
            super().__init__(parent)
            self._save_path = save_path
            self._clipboard = clipboard
            self._open_file = open_file if open_file is not open_in_vscode or vscode_exe() else None
            self.saved: list[Path] = []
            self.setWindowTitle("Red")
            self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
                                | Qt.WindowType.WindowStaysOnTopHint)
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
            self.resize(WIDTH, HEIGHT)
            self._drag: QtCore.QPoint | None = None
            self._frosted = False

            outer = QtWidgets.QVBoxLayout(self)
            outer.setContentsMargins(16, 12, 16, 14)
            outer.setSpacing(10)

            head = QtWidgets.QHBoxLayout()
            title = QtWidgets.QLabel("Red")
            title.setStyleSheet(f"color: {INK}; font-size: 17px; font-weight: 700;")
            head.addWidget(title)
            self.status = QtWidgets.QLabel("")
            self.status.setStyleSheet(f"color: {MUTED}; font-size: 12px;")
            head.addWidget(self.status, 1)
            self.close_button = QtWidgets.QPushButton("✕")
            self.close_button.setToolTip("Hide (Ctrl+Alt+Space brings it back)")
            self.close_button.setStyleSheet(flat.format(bg="transparent", fg=MUTED,
                                                        hover="rgba(0,0,0,0.06)"))
            self.close_button.clicked.connect(self.hide)
            head.addWidget(self.close_button)
            outer.addLayout(head)

            self.scroll = QtWidgets.QScrollArea()
            self.scroll.setWidgetResizable(True)
            self.scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
            self.scroll.setStyleSheet("QScrollArea, QScrollArea > QWidget > QWidget "
                                      "{ background: transparent; border: none; }"
                                      "QScrollBar:vertical { width: 6px; background: transparent; }"
                                      "QScrollBar::handle:vertical { background: rgba(0,0,0,0.18); }"
                                      "QScrollBar::add-line, QScrollBar::sub-line { height: 0; }")
            self.list = QtWidgets.QWidget()
            self.lines = QtWidgets.QVBoxLayout(self.list)
            self.lines.setContentsMargins(0, 0, 4, 0)
            self.lines.setSpacing(8)
            self.lines.addStretch(1)
            self.scroll.setWidget(self.list)
            outer.addWidget(self.scroll, 1)

            self.input = Input()
            self.input.setPlaceholderText("Type to Red. Enter sends, Shift+Enter for a new line.")
            self.input.setFixedHeight(64)
            self.input.setStyleSheet(f"QPlainTextEdit {{ background: rgba(255,255,255,0.78); "
                                     f"border: none; color: {INK}; padding: 6px; font-size: 13px; }}")
            self.input.submit.connect(self._send_typed)
            outer.addWidget(self.input)
            self.bubbles: list[Bubble] = []
            self.streams: dict[str, Bubble] = {}

        # painting: milky glass, a faint wash of the glow's colours, no edge line

        def paintEvent(self, event):  # noqa: N802 - Qt's name
            p = QtGui.QPainter(self)
            try:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QtGui.QColor(*GLASS))
                p.drawRect(self.rect())
                wash = QtGui.QLinearGradient(0, 0, self.width(), 0)
                for i, colour in enumerate(GLASS_TINT):
                    c = QtGui.QColor(colour)
                    c.setAlpha(34)
                    wash.setColorAt(i / (len(GLASS_TINT) - 1), c)
                fade = QtGui.QLinearGradient(0, 0, 0, 120)
                fade.setColorAt(0, QtGui.QColor(0, 0, 0, 255))
                fade.setColorAt(1, QtGui.QColor(0, 0, 0, 0))
                band = QtGui.QImage(self.width(), 120, QtGui.QImage.Format.Format_ARGB32_Premultiplied)
                band.fill(Qt.GlobalColor.transparent)
                bp = QtGui.QPainter(band)
                bp.fillRect(band.rect(), QtGui.QBrush(wash))
                bp.setCompositionMode(QtGui.QPainter.CompositionMode.CompositionMode_DestinationIn)
                bp.fillRect(band.rect(), QtGui.QBrush(fade))
                bp.end()
                p.drawImage(0, 0, band)
            finally:
                p.end()

        def showEvent(self, event):  # noqa: N802
            super().showEvent(event)
            if not self._frosted:
                self._frosted = True
                try:
                    frost(int(self.winId()))
                except Exception:  # noqa: BLE001 - plain milky glass is fine too
                    log.exception("Couldn't frost the chat window")

        # moving it: drag anywhere on the header

        def mousePressEvent(self, event):  # noqa: N802
            if event.button() == Qt.MouseButton.LeftButton and event.position().y() < 44:
                self._drag = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

        def mouseMoveEvent(self, event):  # noqa: N802
            if self._drag is not None:
                self.move(event.globalPosition().toPoint() - self._drag)

        def mouseReleaseEvent(self, event):  # noqa: N802
            self._drag = None

        def keyPressEvent(self, event):  # noqa: N802
            if event.key() == Qt.Key.Key_Escape:
                self.hide()
                return
            super().keyPressEvent(event)

        # content

        def place(self) -> None:
            screen = QtGui.QGuiApplication.primaryScreen()
            if screen is None:
                return
            area = screen.availableGeometry()
            self.move(area.right() - self.width() - 24, area.bottom() - self.height() - 24)

        def add(self, line: Line, into=None) -> None:
            if into is not None:
                bubble = into
            elif line.who == "details" and self.bubbles and self.bubbles[-1].who == "red":
                bubble = self.bubbles[-1]
            else:
                bubble = Bubble("you" if line.who == "you" else "red")
                self.lines.insertWidget(self.lines.count() - 1, bubble)
                self.bubbles.append(bubble)
            n = sum(isinstance(bubble.box.itemAt(i).widget(), CodeBlock)
                    for i in range(bubble.box.count()))
            for kind, body, language in split_code(line.text):
                if kind == "code":
                    n += 1
                    block = CodeBlock(body, language, self)
                    block.filename = code_filename(language, n)
                    bubble.box.addWidget(block)
                else:
                    label = QtWidgets.QLabel(body)
                    label.setTextFormat(Qt.TextFormat.PlainText)
                    label.setWordWrap(True)
                    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
                    small = line.who == "details" and into is None
                    colour = MUTED if small else INK
                    size = 12 if small else 13
                    label.setStyleSheet(f"color: {colour}; font-size: {size}px;")
                    if line.who == "you":
                        label.setAlignment(Qt.AlignmentFlag.AlignRight)
                    bubble.box.addWidget(label)
            if line.action is not None:
                tool, args = line.action
                button = QtWidgets.QPushButton(line.action_label)
                button.setStyleSheet(flat.format(bg=ACCENT, fg="white", hover="#4b49c8"))
                button.clicked.connect(lambda: (button.setEnabled(False),
                                                self.action.emit(tool, dict(args),
                                                                 f"{line.action_label.lower()} it")))
                bubble.box.addWidget(button, 0, Qt.AlignmentFlag.AlignLeft)
                bubble.action_button = button
            while len(self.bubbles) > MAX_MESSAGES:
                old = self.bubbles.pop(0)
                old.setParent(None)
                old.deleteLater()
            QtCore.QTimer.singleShot(0, self._to_bottom)

        def start_stream(self, key: str, who: str = "red") -> None:
            """A bubble whose text is replaced as it streams in (code being written)."""
            bubble = Bubble(who)
            self.lines.insertWidget(self.lines.count() - 1, bubble)
            self.bubbles.append(bubble)
            self.streams[key] = bubble

        def set_stream(self, key: str, text: str) -> None:
            bubble = self.streams.get(key)
            if bubble is None:
                return
            while bubble.box.count():
                widget = bubble.box.takeAt(0).widget()
                if widget is not None:
                    widget.setParent(None)
                    widget.deleteLater()
            self.add(Line("details", text), into=bubble)

        def _to_bottom(self) -> None:
            bar = self.scroll.verticalScrollBar()
            bar.setValue(bar.maximum())

        def set_status(self, text: str) -> None:
            self.status.setText(text)

        def _send_typed(self) -> None:
            text = self.input.toPlainText().strip()
            if not text:
                return
            self.input.clear()
            self.add(Line("you", text))
            self.submitted.emit(text)

        # code buttons

        def copy_code(self, block) -> None:
            clipboard = self._clipboard or QtGui.QGuiApplication.clipboard()
            clipboard.setText(block.code)
            self.set_status("Copied.")

        def save_code(self, block) -> Path | None:
            folder = red_code_folder()
            suggested = str(folder / getattr(block, "filename", code_filename(block.language)))
            if self._save_path is not None:
                chosen = self._save_path(suggested)
            else:
                try:
                    folder.mkdir(parents=True, exist_ok=True)
                except OSError:
                    pass
                # The dialog itself asks before replacing a file that's there.
                chosen, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Save code", suggested)
            if not chosen:
                return None
            path = Path(chosen)
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(block.code + "\n", encoding="utf-8")
            except OSError as e:
                self.set_status(f"Couldn't save: {e}")
                return None
            self.saved.append(path)
            self.set_status(f"Saved {path.name}.")
            block.saved_path = path
            if self._open_file is not None and getattr(block, "open_button", None) is None:
                button = QtWidgets.QPushButton("Open in VS Code")
                button.setStyleSheet(block.copy_button.styleSheet())
                button.clicked.connect(lambda: self._open_file(block.saved_path)
                                       or self.set_status("VS Code isn't installed."))
                block.layout().itemAt(0).layout().addWidget(button)
                block.open_button = button
            return path

    return ChatWindow


_WINDOW_CLASS = None


def window_class():
    global _WINDOW_CLASS
    if _WINDOW_CLASS is None:
        _WINDOW_CLASS = make_window_class()
    return _WINDOW_CLASS


# --- from any thread --------------------------------------------------------------------

class ChatUI:
    """The chat window, safe to use from any thread. The window itself lives on Qt's thread.

    `on_text(text)` gets typed messages, and `on_action(tool, args, said)` the
    buttons; both are called on a fresh worker thread, never Qt's.
    """

    def __init__(self, on_text: Callable[[str], str], on_action: Callable[[str, dict, str], str] | None = None,
                 *, window_factory: Callable[[], object] | None = None):
        QtCore, _, QtWidgets = _qt()
        self._on_text = on_text
        self._on_action = on_action
        self._factory = window_factory or (lambda: window_class()())
        self.window = None
        ui = self

        class Bridge(QtCore.QObject):
            show = QtCore.Signal()
            toggle = QtCore.Signal()
            add = QtCore.Signal(object)
            status = QtCore.Signal(str)
            stream_start = QtCore.Signal(str)
            stream_set = QtCore.Signal(str, str)

            def do_stream_start(self, key):
                self._window().start_stream(key)

            def do_stream_set(self, key, text):
                self._window().set_stream(key, text)

            def _window(self):
                if ui.window is None:
                    ui.window = ui._factory()
                    ui.window.submitted.connect(ui._typed)
                    ui.window.action.connect(ui._action)
                    ui.window.place()
                return ui.window

            def do_show(self):
                window = self._window()
                window.show()
                window.raise_()
                window.activateWindow()
                window.input.setFocus()

            def do_toggle(self):
                if ui.window is not None and ui.window.isVisible():
                    ui.window.hide()
                else:
                    self.do_show()

            def do_add(self, line):
                self._window().add(line)

            def do_status(self, text):
                if ui.window is not None:
                    ui.window.set_status(text)

        self._bridge = Bridge()
        app = QtWidgets.QApplication.instance()
        if app is not None and self._bridge.thread() is not app.thread():
            self._bridge.moveToThread(app.thread())
        self._bridge.show.connect(self._bridge.do_show)
        self._bridge.toggle.connect(self._bridge.do_toggle)
        self._bridge.add.connect(self._bridge.do_add)
        self._bridge.status.connect(self._bridge.do_status)
        self._bridge.stream_start.connect(self._bridge.do_stream_start)
        self._bridge.stream_set.connect(self._bridge.do_stream_set)
        self._streams = 0

    def stream(self) -> "Stream":
        """A bubble to fill as text arrives: `s.set(text_so_far)`, then `s.done(final_text)`."""
        self._streams += 1
        key = f"s{self._streams}"
        self._bridge.stream_start.emit(key)
        return Stream(self._bridge, key)

    def show(self) -> None:
        self._bridge.show.emit()

    def toggle(self) -> None:
        self._bridge.toggle.emit()

    def add(self, who: str, text: str, action: tuple[str, dict] | None = None,
            action_label: str = "Send") -> None:
        self._bridge.add.emit(Line(who, text, action=action, action_label=action_label))

    def feed(self, line: str) -> None:
        """A line the voice loop printed: spoken turns show up in the window too."""
        shown = parse_out(str(line))
        if shown is not None:
            self._bridge.add.emit(shown)

    def _work(self, job: Callable[[], str]) -> None:
        def run():
            self._bridge.status.emit("Thinking...")
            try:
                reply = job()
            except Exception as e:  # noqa: BLE001 - show it rather than lose it
                log.exception("Chat window turn failed")
                reply = f"Sorry, that broke: {e}"
            self._bridge.status.emit("")
            if reply:
                self._bridge.add.emit(Line("red", reply))
        threading.Thread(target=run, name="red-chat-turn", daemon=True).start()

    def _typed(self, text: str) -> None:
        self._work(lambda: self._on_text(text))

    def _action(self, tool: str, args: dict, said: str) -> None:
        if self._on_action is not None:
            self._work(lambda: self._on_action(tool, args, said))


class Stream:
    """One streaming bubble. set() is throttled (the window redraws a few times a second)."""

    EVERY = 0.12            # seconds between redraws

    def __init__(self, bridge, key: str, clock: Callable[[], float] | None = None):
        import time
        self._bridge, self.key = bridge, key
        self._clock = clock or time.monotonic
        self._last = -1e9
        self.text = ""

    def set(self, text: str) -> None:
        self.text = text
        now = self._clock()
        if now - self._last >= self.EVERY:
            self._last = now
            self._bridge.stream_set.emit(self.key, text)

    def done(self, text: str | None = None) -> None:
        if text is not None:
            self.text = text
        self._bridge.stream_set.emit(self.key, self.text)


# --- the hotkey -------------------------------------------------------------------------

def start_hotkey(hotkey: str, callback: Callable[[], None]):
    """A global hotkey (pynput) that calls `callback`. Returns the listener (stop() it)."""
    from pynput import keyboard
    listener = keyboard.GlobalHotKeys({hotkey: callback})
    listener.daemon = True
    listener.start()
    return listener


def _attach_chat_window(app):
    """Give a running VoiceApp its chat window: the hotkey, "open chat", and both kinds of turns.

    None when there's no Qt app (the overlay is off or notifications only).
    """
    try:
        from PySide6.QtWidgets import QApplication
        if QApplication.instance() is None:
            return None
        ui = ChatUI(lambda text: typed_turn(app, text),
                    lambda tool, args, said: run_action(app, tool, args, said))
    except Exception:  # noqa: BLE001 - Red works without the window
        log.exception("Couldn't set up the chat window")
        return None
    out = app.out

    def tee(line: str) -> None:
        out(line)
        try:
            ui.feed(line)
        except Exception:  # noqa: BLE001
            log.exception("Chat window feed failed")
    app.out = tee
    for tool in app.executor.registry:
        bind = getattr(tool, "bind_chat_window", None)
        if callable(bind):
            bind(ui.show)
        bind = getattr(tool, "bind_chat", None)           # tools that write into the window
        if callable(bind):
            bind(ui)
    hotkey = getattr(app.settings, "chat_hotkey", DEFAULT_CHAT_HOTKEY)
    if hotkey:
        try:
            ui.hotkey = start_hotkey(hotkey, ui.toggle)
        except Exception:  # noqa: BLE001 - "open chat" still works
            log.exception("Couldn't start the chat window hotkey %r", hotkey)
    return ui


attach_chat_window = _attach_chat_window
