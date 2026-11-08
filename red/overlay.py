"""Floating status overlay.

A small frameless window in the bottom-right corner of the primary screen
that shows what Red is doing. It stays on top, is see-through, never takes
keyboard focus, and ignores the mouse. It hides itself a few seconds after
Red returns to "idle".

Qt must own the main thread, so `run_with_overlay()` starts Qt on the
calling (main) thread and runs your worker in a background thread. The
worker updates the window with `overlay.set_state()`, which is safe to call
from any thread: it emits a Qt signal that is delivered on the Qt thread.

If PySide6 can't be imported or Qt can't start, Red falls back to Windows
notifications for the states that matter (confirm, speaking, error).

Try it: python -m red.overlay
"""

from __future__ import annotations

import argparse
import base64
import functools
import logging
import os
import signal
import subprocess
import sys
import threading
import time
from typing import Callable

log = logging.getLogger(__name__)

STATES = ("idle", "listening", "thinking", "confirm", "speaking", "error")

LABELS = {
    "idle": "Ready",
    "listening": "Listening",
    "thinking": "Thinking",
    "confirm": "Confirm",
    "speaking": "Red",
    "error": "Problem",
}

# Dot colour for each state (dark-background friendly).
COLORS = {
    "idle": "#8b8d98",
    "listening": "#e5484d",   # a red dot reads as "recording"
    "thinking": "#8e8cff",
    "confirm": "#3e9bff",
    "speaking": "#30a46c",
    "error": "#f5a524",
}

HIDE_AFTER_IDLE_SECONDS = 3.0
MAX_TEXT = 600         # characters; longer text is cut with an ellipsis
WIDTH = 360            # pixels (Qt scales for high DPI)
MARGIN = 24            # pixels from the screen edges

Worker = Callable[["Overlay"], None]


def _check_state(state: str) -> None:
    if state not in STATES:
        raise ValueError(f"Unknown overlay state {state!r}; use one of {STATES}")


def _clean(text: object) -> str:
    text = "" if text is None else str(text).strip()
    if len(text) > MAX_TEXT:
        text = text[:MAX_TEXT - 1].rstrip() + "…"
    return text


class Overlay:
    """What a worker sees. `set_state` is safe to call from any thread."""

    def set_state(self, state: str, text: str = "") -> None:
        raise NotImplementedError


# --------------------------------------------------------------------------
# Qt window
# --------------------------------------------------------------------------

@functools.cache
def _window_class():
    """Build the Qt window class. Imported lazily so Red runs without PySide6."""
    from PySide6.QtCore import QRectF, Qt, QTimer, Signal, Slot
    from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPen
    from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

    class Dot(QWidget):
        def __init__(self, parent=None):
            super().__init__(parent)
            self.setFixedSize(12, 12)
            self.color = QColor(COLORS["idle"])

        def paintEvent(self, event):  # noqa: N802 (Qt name)
            p = QPainter(self)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(self.color)
            p.drawEllipse(self.rect().adjusted(1, 1, -1, -1))

    class OverlayWindow(QWidget):
        # Emitted from any thread; delivered on the Qt thread (queued).
        requested = Signal(str, str)
        # Emitted by the worker thread when it's done, to quit the app.
        finished = Signal()

        def __init__(self, hide_after: float = HIDE_AFTER_IDLE_SECONDS):
            flags = (Qt.WindowType.FramelessWindowHint
                     | Qt.WindowType.WindowStaysOnTopHint
                     | Qt.WindowType.Tool                     # no taskbar button
                     | Qt.WindowType.WindowDoesNotAcceptFocus
                     | Qt.WindowType.WindowTransparentForInput)
            super().__init__(None, flags)
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
            self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
            self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            self.setWindowTitle("Red")
            self.setFixedWidth(WIDTH)

            self.state = "idle"
            self.text = ""
            self.hide_after = hide_after

            self.dot = Dot(self)
            self.title = QLabel(self)
            self.title.setStyleSheet("color: #f2f2f5; font-size: 11pt; font-weight: 600;")
            self.body = QLabel(self)
            self.body.setWordWrap(True)
            self.body.setTextFormat(Qt.TextFormat.PlainText)
            self.body.setStyleSheet("color: #c9cad1; font-size: 10pt;")

            text_col = QVBoxLayout()
            text_col.setContentsMargins(0, 0, 0, 0)
            text_col.setSpacing(2)
            text_col.addWidget(self.title)
            text_col.addWidget(self.body)
            text_col.addStretch(1)

            row = QHBoxLayout(self)
            row.setContentsMargins(16, 12, 16, 12)
            row.setSpacing(10)
            row.addWidget(self.dot, 0, Qt.AlignmentFlag.AlignTop)
            row.addLayout(text_col, 1)
            # Keep the dot level with the title's first line.
            self.dot.setContentsMargins(0, 4, 0, 0)

            self.hide_timer = QTimer(self)
            self.hide_timer.setSingleShot(True)
            self.hide_timer.timeout.connect(self.hide)

            self.requested.connect(self.apply, Qt.ConnectionType.QueuedConnection)
            self.apply("idle", "")

        def paintEvent(self, event):  # noqa: N802 (Qt name)
            p = QPainter(self)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setPen(QPen(QColor(255, 255, 255, 36), 1))
            p.setBrush(QColor(22, 22, 28, 228))
            p.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 14, 14)

        @Slot(str, str)
        def apply(self, state: str, text: str) -> None:
            self.state, self.text = state, text
            self.title.setText(LABELS[state])
            self.body.setText(text)
            self.body.setVisible(bool(text))
            self.dot.color = QColor(COLORS[state])
            self.dot.update()
            # Word-wrapped labels need height-for-width; adjustSize() gets it wrong.
            self.layout().activate()
            self.setFixedHeight(max(self.layout().totalHeightForWidth(WIDTH),
                                    self.layout().totalMinimumSize().height()))
            self.place()

            if state == "idle":
                if text and not self.isVisible():
                    self.show()
                if self.isVisible():
                    self.hide_timer.start(int(self.hide_after * 1000))
            else:
                self.hide_timer.stop()
                if not self.isVisible():
                    self.show()
                self.update()

        def place(self) -> None:
            screen = QGuiApplication.primaryScreen()
            if screen is None:
                return
            area = screen.availableGeometry()   # leaves the taskbar uncovered
            self.move(area.x() + area.width() - self.width() - MARGIN,
                      area.y() + area.height() - self.height() - MARGIN)

    return OverlayWindow


class QtOverlay(Overlay):
    """The real overlay window. Create it on the Qt thread after QApplication."""

    def __init__(self, hide_after: float = HIDE_AFTER_IDLE_SECONDS):
        self.window = _window_class()(hide_after)
        self._closed = False

    def set_state(self, state: str, text: str = "") -> None:
        _check_state(state)
        if self._closed:
            return
        try:
            self.window.requested.emit(state, _clean(text))
        except RuntimeError:     # the window was already deleted at shutdown
            self._closed = True

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self.window.hide_timer.stop()
            self.window.close()


# --------------------------------------------------------------------------
# Fallback: Windows notifications
# --------------------------------------------------------------------------

# A fixed script. The title and text arrive through environment variables and
# are added as XML text nodes, so nothing the user or the model says is ever
# parsed as script or markup.
_TOAST_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null
$xml = New-Object Windows.Data.Xml.Dom.XmlDocument
$xml.LoadXml('<toast><visual><binding template="ToastGeneric"><text/><text/></binding></visual></toast>')
$nodes = $xml.GetElementsByTagName('text')
$nodes.Item(0).AppendChild($xml.CreateTextNode($env:RED_TOAST_TITLE)) | Out-Null
$nodes.Item(1).AppendChild($xml.CreateTextNode($env:RED_TOAST_BODY)) | Out-Null
$toast = [Windows.UI.Notifications.ToastNotification]::new($xml)
$app = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe'
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($app).Show($toast)
"""

NOTIFY_STATES = ("confirm", "speaking", "error")


def toast_command() -> list[str]:
    encoded = base64.b64encode(_TOAST_SCRIPT.encode("utf-16-le")).decode("ascii")
    return ["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded]


class NotificationOverlay(Overlay):
    """Shows confirm, speaking and error states as Windows notifications."""

    def __init__(self, runner=subprocess.Popen, states: tuple[str, ...] = NOTIFY_STATES):
        self._runner = runner
        self.states = states

    def set_state(self, state: str, text: str = "") -> None:
        _check_state(state)
        text = _clean(text)
        if state not in self.states:
            return
        if not text:
            if state != "error":
                return
            text = "Something went wrong."
        self.notify(f"Red: {LABELS[state]}" if state != "speaking" else "Red", text)

    def notify(self, title: str, body: str) -> None:
        env = dict(os.environ, RED_TOAST_TITLE=title, RED_TOAST_BODY=body)
        try:
            self._runner(toast_command(), env=env,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL,
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except OSError as e:
            log.warning("Couldn't show a notification: %s", e)


class ConsoleOverlay(Overlay):
    """Prints state changes. Used by the demo and handy for typed mode."""

    def __init__(self, write=print):
        self._write = write
        self._lock = threading.Lock()

    def set_state(self, state: str, text: str = "") -> None:
        _check_state(state)
        with self._lock:
            self._write(f"[{state}] {_clean(text)}".rstrip())


# --------------------------------------------------------------------------
# Running a worker with the overlay
# --------------------------------------------------------------------------

def _run_worker(worker: Worker, overlay: Overlay) -> int:
    try:
        worker(overlay)
        return 0
    except KeyboardInterrupt:
        return 130
    except Exception as e:  # noqa: BLE001 - report, never crash the UI thread
        log.exception("Worker failed")
        try:
            overlay.set_state("error", f"Red stopped: {e}")
        except Exception:  # noqa: BLE001
            pass
        return 1


def _start_qt(hide_after: float):
    """Return (app, overlay), or raise if Qt can't be used."""
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([sys.argv[0] if sys.argv else "red"])
    if QGuiApplication.primaryScreen() is None:
        raise RuntimeError("no screen")
    app.setQuitOnLastWindowClosed(False)
    return app, QtOverlay(hide_after)


def run_with_overlay(worker: Worker, *, hide_after: float = HIDE_AFTER_IDLE_SECONDS,
                     fallback: Callable[[], Overlay] = NotificationOverlay) -> int:
    """Run Qt on this (main) thread and `worker(overlay)` on a background thread.

    Returns 0 when the worker finishes, 1 if it raised, and 130 on Ctrl+C.
    If Qt isn't available, runs the worker here with `fallback()` instead.
    """
    try:
        app, overlay = _start_qt(hide_after)
    except Exception as e:  # noqa: BLE001 - ImportError, missing DLLs, no screen
        log.warning("Overlay unavailable (%s); using Windows notifications instead", e)
        return _run_worker(worker, fallback())

    from PySide6.QtCore import Qt, QTimer

    window = overlay.window
    window.finished.connect(app.quit, Qt.ConnectionType.QueuedConnection)
    result: list[int] = []

    def target() -> None:
        result.append(_run_worker(worker, overlay))
        try:
            window.finished.emit()
        except RuntimeError:
            pass

    # Qt's event loop blocks Python's Ctrl+C handling; a timer lets it run.
    on_main = threading.current_thread() is threading.main_thread()
    previous = signal.signal(signal.SIGINT, lambda *_: app.quit()) if on_main else None
    tick = QTimer()
    tick.timeout.connect(lambda: None)
    tick.start(250)

    thread = threading.Thread(target=target, name="red-worker", daemon=True)
    QTimer.singleShot(0, thread.start)
    try:
        app.exec()
    finally:
        tick.stop()
        overlay.close()
        if on_main:
            signal.signal(signal.SIGINT, previous)
    thread.join(timeout=1.0)
    return result[0] if result else 130


# --------------------------------------------------------------------------
# Demo
# --------------------------------------------------------------------------

DEMO = (
    ("listening", ""),
    ("thinking", "open Downloads"),
    ("confirm", "Shut down in 2 hours (at 11:40 PM)? Say yes or no."),
    ("speaking", "Opening Downloads."),
    ("speaking", "2 of 3 repos need attention: red is ahead by 2, notes has "
                 "uncommitted changes.\nred: main, 2 to push\nnotes: main, 3 changed files"),
    ("error", "I couldn't reach the local model."),
    ("idle", ""),
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m red.overlay",
                                     description="Show every overlay state, then exit.")
    parser.add_argument("--seconds", type=float, default=1.5, help="time per state")
    parser.add_argument("--fallback", action="store_true",
                        help="show the Windows notification fallback instead")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    def demo(overlay: Overlay) -> None:
        for state, text in DEMO:
            print(f"[{state}] {text}".rstrip(), flush=True)
            overlay.set_state(state, text)
            time.sleep(args.seconds)
        time.sleep(HIDE_AFTER_IDLE_SECONDS + 0.5)   # watch it hide itself

    if args.fallback:
        return _run_worker(demo, NotificationOverlay())
    return run_with_overlay(demo)


if __name__ == "__main__":
    sys.exit(main())
