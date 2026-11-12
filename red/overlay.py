"""What Red shows on screen while it works.

Two looks, picked with RED_OVERLAY:

- "glow" (the default): an animated glow in Red's colours along all four
  edges of the screen, like a phone assistant. It appears when Red starts
  listening, changes colour and speed while Red thinks, asks or speaks, and
  fades away when Red is done. It never covers the middle of the screen.
- "card": a small frameless card in the bottom-right corner with the state
  and the text.

Both stay on top, never take keyboard focus, and let mouse clicks through.

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
import math
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
# Glow around the screen edges
# --------------------------------------------------------------------------

# Colours that sweep around the edges, per state. Red's own warm colours
# while it listens and speaks, cooler ones while it thinks or asks.
GLOW_PALETTES = {
    "listening": ("#ff3b30", "#ff9500", "#ff2d55", "#bf5af2"),
    "thinking": ("#bf5af2", "#5e5ce6", "#ff2d55", "#64d2ff"),
    "confirm": ("#0a84ff", "#64d2ff", "#5e5ce6", "#0a84ff"),
    "speaking": ("#ff375f", "#ff9f0a", "#ff453a", "#bf5af2"),
    "error": ("#ff9f0a", "#ff453a", "#ff9f0a", "#ffd60a"),
}
GLOW_SPEED = {          # turns of the colour sweep per second
    "listening": 0.25,
    "thinking": 0.9,
    "confirm": 0.2,
    "speaking": 0.35,
    "error": 0.15,
}
GLOW_PULSE = {          # breaths per second
    "listening": 0.9,
    "thinking": 1.6,
    "confirm": 0.7,
    "speaking": 1.2,
    "error": 2.0,
}
GLOW_DEPTH = 56         # pixels: how far the glow reaches in from each edge
GLOW_FPS = 30
GLOW_FADE_IN = 0.25     # seconds
GLOW_FADE_OUT = 0.6     # seconds
# Without numpy (no smooth mask): stacked strokes instead, as (stroke width
# as a share of 2 x depth, opacity), wide and faint to thin and bright.
GLOW_LAYERS = tuple((1.0 - i / 12, 0.06 + 0.5 * (i / 12) ** 2) for i in range(12))
GLOW_SOFTNESS = 0.42    # the glow fades to about a third every 0.42 x depth pixels


def edge_falloff(distance, depth: float):
    """Glow strength (0..1) at `distance` pixels in from the nearest screen edge.

    Bright at the edge, dying away smoothly and reaching exactly 0 at
    `depth`. Works on numbers and on numpy arrays.
    """
    import numpy as np

    d = np.clip(np.asarray(distance, dtype=np.float32) / float(depth), 0.0, 1.0)
    return np.exp(-d / GLOW_SOFTNESS) * (1.0 - d)


def glow_mask(x0: int, y0: int, w: int, h: int, screen_w: int, screen_h: int, depth: int):
    """Glow strength for every pixel of one strip, as uint8 rows (h, w).

    (x0, y0) is the strip's corner relative to the screen's corner. Each
    pixel uses its distance to the nearest of the four edges, so the
    corners blend smoothly where two strips meet.
    """
    import numpy as np

    xs = np.arange(w, dtype=np.float32) + x0
    ys = np.arange(h, dtype=np.float32) + y0
    dx = np.minimum(xs, screen_w - 1 - xs)[None, :]
    dy = np.minimum(ys, screen_h - 1 - ys)[:, None]
    strength = edge_falloff(np.minimum(dx, dy), depth)
    return np.round(strength * 255).astype(np.uint8)


def glow_alpha(level: float, state: str, seconds: float) -> float:
    """How strong the glow is right now: the fade level times a gentle breath."""
    pulse = GLOW_PULSE.get(state, 1.0)
    breath = 0.8 + 0.2 * math.sin(seconds * 2 * math.pi * pulse)
    return max(0.0, min(1.0, level)) * breath


def step_toward(value: float, target: float, dt: float,
                fade_in: float = GLOW_FADE_IN, fade_out: float = GLOW_FADE_OUT) -> float:
    """Move a 0..1 fade level toward `target` over the fade time."""
    if target > value:
        return min(target, value + dt / fade_in)
    return max(target, value - dt / fade_out)


def edge_strips(x: int, y: int, width: int, height: int, depth: int) -> dict[str, tuple[int, int, int, int]]:
    """The four thin windows (x, y, w, h) that together frame the screen.

    Four strips instead of one full-screen window: a see-through window is
    redrawn whole on every frame, and the strips are about a tenth of the
    pixels.
    """
    depth = max(1, min(depth, width // 2, height // 2))
    return {
        "top": (x, y, width, depth),
        "bottom": (x, y + height - depth, width, depth),
        "left": (x, y + depth, depth, height - 2 * depth),
        "right": (x + width - depth, y + depth, depth, height - 2 * depth),
    }


@functools.cache
def _glow_class():
    """Build the Qt glow classes. Imported lazily so Red runs without PySide6."""
    from PySide6.QtCore import QElapsedTimer, QObject, QPointF, QRectF, Qt, QTimer, Signal, Slot
    from PySide6.QtGui import (QBrush, QColor, QConicalGradient, QGuiApplication, QImage,
                               QPainter, QPen)
    from PySide6.QtWidgets import QWidget

    def mask_image(x0: int, y0: int, w: int, h: int, screen_w: int, screen_h: int, depth: int):
        """The strip's fade as a white image whose alpha is the glow strength, or None."""
        if w <= 0 or h <= 0:
            return None
        try:
            import numpy as np
        except ImportError:
            return None
        a = glow_mask(x0, y0, w, h, screen_w, screen_h, depth).astype(np.uint32)
        pixels = np.ascontiguousarray((a << 24) | (a << 16) | (a << 8) | a)  # premultiplied white
        image = QImage(pixels.data, w, h, w * 4, QImage.Format.Format_ARGB32_Premultiplied)
        return image.copy()     # own the pixels; the numpy array goes away

    class Strip(QWidget):
        def __init__(self, glow, side: str):
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
            self.glow, self.side = glow, side

        def paintEvent(self, event):  # noqa: N802 (Qt name)
            self.glow.paint(self)

    class GlowWindow(QObject):
        # Same signals as the card window, so run_with_overlay treats both alike.
        requested = Signal(str, str)
        finished = Signal()

        def __init__(self, depth: int = GLOW_DEPTH, fps: int = GLOW_FPS):
            super().__init__()
            self.depth = depth
            self.state = "idle"
            self.text = ""
            self.level = 0.0          # fade, 0 (hidden) .. 1 (full)
            self.target = 0.0
            self.phase = 0.0          # degrees the colour sweep has turned
            self.palette = GLOW_PALETTES["listening"]
            self.speed = GLOW_SPEED["listening"]
            self.screen = QRectF()
            self.masks: dict = {}
            self.clock = QElapsedTimer()
            self.clock.start()
            self.last = 0
            self.strips = {side: Strip(self, side) for side in ("top", "bottom", "left", "right")}
            self.timer = QTimer(self)
            self.timer.setInterval(max(1, int(1000 / fps)))
            self.timer.timeout.connect(self.tick)
            self.requested.connect(self.apply, Qt.ConnectionType.QueuedConnection)

        def isVisible(self) -> bool:  # noqa: N802 - matches QWidget, used by tests
            return any(s.isVisible() for s in self.strips.values())

        def place(self) -> None:
            screen = QGuiApplication.primaryScreen()
            if screen is None:
                return
            g = screen.geometry()        # the whole screen, taskbar included
            if QRectF(g) == self.screen and self.masks:
                return
            self.screen = QRectF(g)
            for side, (x, y, w, h) in edge_strips(g.x(), g.y(), g.width(), g.height(),
                                                  self.depth).items():
                self.strips[side].setGeometry(x, y, w, h)
                self.masks[side] = mask_image(x - g.x(), y - g.y(), w, h,
                                              g.width(), g.height(), self.depth)

        @Slot(str, str)
        def apply(self, state: str, text: str) -> None:
            self.state, self.text = state, text
            if state == "idle":
                self.target = 0.0
            else:
                self.palette = GLOW_PALETTES[state]
                self.speed = GLOW_SPEED[state]
                self.target = 1.0
                if not self.isVisible():
                    self.place()
                    for strip in self.strips.values():
                        strip.show()
            if self.target > 0 or self.level > 0:
                if not self.timer.isActive():
                    self.last = self.clock.elapsed()
                    self.timer.start()

        def tick(self) -> None:
            now = self.clock.elapsed()
            dt = min(0.1, (now - self.last) / 1000)
            self.last = now
            self.phase = (self.phase + self.speed * 360 * dt) % 360
            self.level = step_toward(self.level, self.target, dt)
            if self.level <= 0.0 and self.target <= 0.0:
                self.timer.stop()
                for strip in self.strips.values():
                    strip.hide()
                return
            for strip in self.strips.values():
                strip.update()

        def paint(self, strip) -> None:
            alpha = glow_alpha(self.level, self.state if self.state != "idle" else "speaking",
                               self.clock.elapsed() / 1000)
            if alpha <= 0.0 or self.screen.isEmpty():
                return
            p = QPainter(strip)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            # Paint in screen coordinates, so the four strips join up seamlessly.
            g = strip.geometry()
            dx, dy = self.screen.x() - g.x(), self.screen.y() - g.y()
            p.translate(dx, dy)
            w, h = self.screen.width(), self.screen.height()
            sweep = QConicalGradient(QPointF(w / 2, h / 2), self.phase)
            colours = self.palette + (self.palette[0],)
            for i, colour in enumerate(colours):
                sweep.setColorAt(i / (len(colours) - 1), QColor(colour))
            mask = self.masks.get(strip.side)
            if mask is not None:
                # The colours fill the strip; the mask then fades them out
                # smoothly from the screen edge inwards.
                p.setOpacity(alpha)
                p.fillRect(QRectF(-dx, -dy, g.width(), g.height()), QBrush(sweep))
                p.resetTransform()
                p.setOpacity(1.0)
                p.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
                p.drawImage(QRectF(0, 0, g.width(), g.height()), mask)
            else:
                edge = QRectF(0, 0, w, h)
                for share, opacity in GLOW_LAYERS:
                    pen = QPen(QBrush(sweep), max(1.0, 2 * self.depth * share))
                    pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
                    p.setPen(pen)
                    p.setBrush(Qt.BrushStyle.NoBrush)
                    p.setOpacity(opacity * alpha)
                    p.drawRect(edge)
            p.end()

        def close(self) -> None:
            self.timer.stop()
            for strip in self.strips.values():
                strip.close()

    return GlowWindow


class GlowOverlay(Overlay):
    """The glow around the screen edges. Create it on the Qt thread after QApplication."""

    def __init__(self, depth: int = GLOW_DEPTH):
        self.window = _glow_class()(depth)
        self._closed = False

    def set_state(self, state: str, text: str = "") -> None:
        _check_state(state)
        if self._closed:
            return
        try:
            self.window.requested.emit(state, _clean(text))
        except RuntimeError:     # already deleted at shutdown
            self._closed = True

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self.window.close()


class NullOverlay(Overlay):
    """Shows nothing (RED_OVERLAY=off). Red still prints and speaks."""

    def set_state(self, state: str, text: str = "") -> None:
        _check_state(state)


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
        show_notification(title, body, runner=self._runner)


def show_notification(title: str, body: str, runner=subprocess.Popen) -> None:
    """Show one Windows toast. The title and body are text nodes, never markup."""
    env = dict(os.environ, RED_TOAST_TITLE=title, RED_TOAST_BODY=body)
    try:
        runner(toast_command(), env=env,
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


def _start_qt(hide_after: float, style: str = "card"):
    """Return (app, overlay), or raise if Qt can't be used."""
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([sys.argv[0] if sys.argv else "red"])
    if QGuiApplication.primaryScreen() is None:
        raise RuntimeError("no screen")
    app.setQuitOnLastWindowClosed(False)
    return app, (GlowOverlay() if style == "glow" else QtOverlay(hide_after))


def run_with_overlay(worker: Worker, *, hide_after: float = HIDE_AFTER_IDLE_SECONDS,
                     fallback: Callable[[], Overlay] = NotificationOverlay,
                     style: str = "card") -> int:
    """Run Qt on this (main) thread and `worker(overlay)` on a background thread.

    `style` is "glow" (screen edges), "card" (corner card), "notify" (Windows
    notifications only) or "off" (nothing on screen).
    Returns 0 when the worker finishes, 1 if it raised, and 130 on Ctrl+C.
    If Qt isn't available, runs the worker here with `fallback()` instead.
    """
    if style == "off":
        return _run_worker(worker, NullOverlay())
    if style == "notify":
        return _run_worker(worker, fallback())
    try:
        app, overlay = _start_qt(hide_after, style)
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
    parser.add_argument("--style", choices=("glow", "card"), default="glow",
                        help="the screen-edge glow (default) or the corner card")
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
    return run_with_overlay(demo, style=args.style)


if __name__ == "__main__":
    sys.exit(main())
