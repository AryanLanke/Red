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

# The glow: a thin glossy line of light right at the screen edge, with a
# soft halo behind it. A few soft patches of colour drift slowly along the
# edges at different speeds, so the light looks liquid rather than spinning.
# Corners are rounded, so the line runs smoothly round them.

# Colour patches per state. Calm blues, violets and roses; warmer while Red
# speaks, cooler while it asks you to confirm, amber for a problem.
GLOW_PALETTES = {
    "listening": ("#5b8cff", "#9b6bff", "#ff5c8a", "#ff9a6b"),
    "thinking": ("#4f7dff", "#8f6bff", "#c86bff", "#5bc8ff"),
    "confirm": ("#3b82f6", "#60c6ff", "#7c8cff", "#3bb8f6"),
    "speaking": ("#ff6b8f", "#9b6bff", "#5b8cff", "#ffb36b"),
    "error": ("#ffb020", "#ff6b4a", "#ffcc5c", "#ff8a3d"),
}
GLOW_SPEED = {          # how fast the colours drift: share of the screen's edge per second
    "listening": 0.05,
    "thinking": 0.16,
    "confirm": 0.04,
    "speaking": 0.08,
    "error": 0.03,
}
GLOW_PULSE = {          # breaths per second
    "listening": 0.6,
    "thinking": 1.1,
    "confirm": 0.5,
    "speaking": 1.4,
    "error": 1.6,
}
GLOW_DEPTH = 48         # pixels: how far the faint halo reaches in from each edge
GLOW_RADIUS = 28        # pixels: the rounded corners the light follows
GLOW_INSET = 3.0        # pixels: the bright line sits just inside the edge, fully visible
GLOW_GLOSS = 0.45       # how far the bright line is mixed towards white
GLOW_FPS = 30
GLOW_FADE_IN = 0.3      # seconds
GLOW_FADE_OUT = 0.7     # seconds
GLOW_STOPS = 16         # colour samples along each strip (the colour patches are wide)


def rounded_edge_distance(xs, ys, width: int, height: int, radius: float):
    """Distance in pixels from each point to the screen's rounded-corner outline.

    xs, ys are numpy grids of pixel positions. Along the straight edges it's
    simply the distance to the nearest edge; inside a corner it's measured
    to the corner's arc, so the light bends smoothly instead of meeting at
    a sharp diagonal.
    """
    import numpy as np

    right, bottom = width - 1 - radius, height - 1 - radius
    dx = np.maximum(np.maximum(radius - xs, xs - right), 0.0)
    dy = np.maximum(np.maximum(radius - ys, ys - bottom), 0.0)
    straight = np.minimum(np.minimum(xs, width - 1 - xs), np.minimum(ys, height - 1 - ys))
    corner = radius - np.hypot(dx, dy)
    return np.where((dx > 0) & (dy > 0), corner, straight)


def glow_profile(distance, depth: float):
    """(halo, line) strength, 0..1, at `distance` pixels from the glow's centre line.

    The halo has a brighter inner part and a wide faint tail that ends
    smoothly at `depth`; the line is a narrow highlight.
    """
    import numpy as np

    d = np.abs(np.asarray(distance, dtype=np.float32))
    tail = np.clip(1.0 - (d / float(depth)) ** 2, 0.0, 1.0) ** 2
    halo = (0.62 * np.exp(-(d / 8.0) ** 2) + 0.30 * np.exp(-(d / 24.0) ** 2)) * tail
    line = np.exp(-(d / 1.7) ** 2)
    return np.clip(halo, 0.0, 1.0), np.clip(line, 0.0, 1.0)


def glow_masks(x0: int, y0: int, w: int, h: int, screen_w: int, screen_h: int,
               depth: int = GLOW_DEPTH, radius: float = GLOW_RADIUS, inset: float = GLOW_INSET):
    """The halo and line strengths for every pixel of one strip, as uint8 (h, w) arrays.

    (x0, y0) is the strip's corner relative to the screen's corner.
    """
    import numpy as np

    ys, xs = np.mgrid[y0:y0 + h, x0:x0 + w].astype(np.float32)
    d = rounded_edge_distance(xs, ys, screen_w, screen_h, radius) - inset
    halo, line = glow_profile(d, depth)
    return (np.round(halo * 255).astype(np.uint8), np.round(line * 255).astype(np.uint8))


def _hex_rgb(colour: str) -> tuple[float, float, float]:
    colour = colour.lstrip("#")
    return tuple(int(colour[i:i + 2], 16) / 255 for i in (0, 2, 4))  # type: ignore[return-value]


def flow_colour(position: float, seconds: float, palette: tuple[str, ...],
                speed: float) -> tuple[int, int, int]:
    """The colour at `position` (0..1 round the screen's edge) at time `seconds`.

    Each palette colour is a soft patch drifting round the edge at its own
    speed (some the other way). Colours are mixed in linear light, so blends
    stay clean instead of turning muddy.
    """
    n = len(palette)
    total = [0.0, 0.0, 0.0]
    weight_sum = 0.0
    for i, colour in enumerate(palette):
        direction = 1 if i % 2 == 0 else -1
        centre = (i / n + direction * speed * (1 + 0.37 * i) * seconds) % 1.0
        gap = abs(position - centre)
        gap = min(gap, 1.0 - gap)
        weight = math.exp(-(gap / 0.16) ** 2) + 1e-4
        for k, c in enumerate(_hex_rgb(colour)):
            total[k] += weight * c ** 2.2
        weight_sum += weight
    return tuple(int(round(255 * (t / weight_sum) ** (1 / 2.2))) for t in total)  # type: ignore[return-value]


@functools.lru_cache(maxsize=16)
def _linear_palette(palette: tuple[str, ...]):
    import numpy as np

    return np.array([_hex_rgb(c) for c in palette], dtype=np.float64) ** 2.2


def flow_colours(positions, seconds: float, palette: tuple[str, ...],
                 speed: float) -> list[tuple[int, int, int]]:
    """flow_colour for many positions at once (numpy), as used on every frame."""
    import numpy as np

    pos = np.asarray(positions, dtype=np.float64)[:, None]
    n = len(palette)
    i = np.arange(n)
    direction = np.where(i % 2 == 0, 1.0, -1.0)
    centres = (i / n + direction * speed * (1 + 0.37 * i) * seconds) % 1.0
    gap = np.abs(pos - centres[None, :])
    gap = np.minimum(gap, 1.0 - gap)
    weights = np.exp(-(gap / 0.16) ** 2) + 1e-4
    mixed = (weights @ _linear_palette(tuple(palette))) / weights.sum(axis=1, keepdims=True)
    rgb = np.round(255 * mixed ** (1 / 2.2)).astype(int)
    return [tuple(int(c) for c in row) for row in rgb]


def glossy(rgb: tuple[int, int, int], amount: float = GLOW_GLOSS) -> tuple[int, int, int]:
    """Mix a colour towards white, for the bright highlight line."""
    return tuple(int(round(c + (255 - c) * amount)) for c in rgb)  # type: ignore[return-value]


def perimeter_span(side: str, x: int, y: int, w: int, h: int, screen_w: int, screen_h: int):
    """Where a strip starts and ends along the edge, as (start, end) in 0..1 going clockwise."""
    p = 2.0 * (screen_w + screen_h)
    if side == "top":
        return x / p, (x + w) / p
    if side == "right":
        return (screen_w + y) / p, (screen_w + y + h) / p
    if side == "bottom":
        return ((screen_w + screen_h + (screen_w - x)) / p,
                (screen_w + screen_h + (screen_w - x - w)) / p)
    return ((2 * screen_w + screen_h + (screen_h - y)) / p,
            (2 * screen_w + screen_h + (screen_h - y - h)) / p)


def glow_alpha(level: float, state: str, seconds: float) -> float:
    """How strong the glow is right now: the fade level times a gentle breath."""
    pulse = GLOW_PULSE.get(state, 1.0)
    breath = 0.85 + 0.15 * math.sin(seconds * 2 * math.pi * pulse)
    eased = 1 - (1 - max(0.0, min(1.0, level))) ** 2      # quick to appear, soft to settle
    return eased * breath


def step_toward(value: float, target: float, dt: float,
                fade_in: float = GLOW_FADE_IN, fade_out: float = GLOW_FADE_OUT) -> float:
    """Move a 0..1 fade level toward `target` over the fade time."""
    if target > value:
        return min(target, value + dt / fade_in)
    return max(target, value - dt / fade_out)


def edge_strips(x: int, y: int, width: int, height: int,
                depth: int) -> dict[str, tuple[int, int, int, int]]:
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
    from PySide6.QtGui import QColor, QGuiApplication, QImage, QLinearGradient, QPainter
    from PySide6.QtWidgets import QWidget

    def to_image(values):
        """A white image whose alpha is `values` (uint8 rows), used as a mask."""
        import numpy as np

        h, w = values.shape
        a = values.astype(np.uint32)
        pixels = np.ascontiguousarray((a << 24) | (a << 16) | (a << 8) | a)  # premultiplied white
        return QImage(pixels.data, w, h, w * 4, QImage.Format.Format_ARGB32_Premultiplied).copy()

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
            self.halo = self.line = None      # mask images, made when placed
            self.line_at = None               # where the line's band starts in the strip
            self.span = (0.0, 0.0)
            self.buffer = None                # scratch image for the highlight line

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
            self.palette = GLOW_PALETTES["listening"]
            self.speed = GLOW_SPEED["listening"]
            self.flow = 0.0           # how far the colours have drifted (speed changes stay smooth)
            self.screen = QRectF()
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
            if QRectF(g) == self.screen and all(s.halo is not None for s in self.strips.values()):
                return
            self.screen = QRectF(g)
            for side, (x, y, w, h) in edge_strips(g.x(), g.y(), g.width(), g.height(),
                                                  self.depth).items():
                strip = self.strips[side]
                strip.setGeometry(x, y, w, h)
                lx, ly = x - g.x(), y - g.y()
                strip.span = perimeter_span(side, lx, ly, w, h, g.width(), g.height())
                strip.halo = strip.line = strip.buffer = None
                if w > 0 and h > 0:
                    try:
                        import numpy as np

                        halo, line = glow_masks(lx, ly, w, h, g.width(), g.height(), self.depth)
                    except ImportError:          # no numpy: show nothing rather than fail
                        continue
                    strip.halo = to_image(halo)
                    # The bright line only lives in a thin band (wider at the
                    # corners): keep just that part, so drawing it is cheap.
                    rows = np.flatnonzero(line.any(axis=1))
                    cols = np.flatnonzero(line.any(axis=0))
                    if rows.size and cols.size:
                        r0, r1, c0, c1 = rows[0], rows[-1] + 1, cols[0], cols[-1] + 1
                        strip.line = to_image(np.ascontiguousarray(line[r0:r1, c0:c1]))
                        strip.line_at = QPointF(float(c0), float(r0))
                        strip.buffer = QImage(int(c1 - c0), int(r1 - r0),
                                              QImage.Format.Format_ARGB32_Premultiplied)

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
            self.flow += dt * self.speed / GLOW_SPEED["listening"]
            self.level = step_toward(self.level, self.target, dt)
            if self.level <= 0.0 and self.target <= 0.0:
                self.timer.stop()
                for strip in self.strips.values():
                    strip.hide()
                return
            for strip in self.strips.values():
                strip.update()

        def gradients(self, strip):
            """The flowing colours along this strip: (halo gradient, glossy line gradient)."""
            w, h = strip.width(), strip.height()
            horizontal = strip.side in ("top", "bottom")
            # span[0] is where this strip's own left (or top) end sits along the
            # edge, so the gradients always run from there to its other end.
            far = QPointF(w, 0) if horizontal else QPointF(0, h)
            halo, line = QLinearGradient(QPointF(0, 0), far), QLinearGradient(QPointF(0, 0), far)
            start, end = strip.span
            ts = [i / GLOW_STOPS for i in range(GLOW_STOPS + 1)]
            colours = flow_colours([(start + (end - start) * t) % 1.0 for t in ts], self.flow,
                                   self.palette, GLOW_SPEED["listening"])
            for t, rgb in zip(ts, colours):
                halo.setColorAt(t, QColor(*rgb))
                line.setColorAt(t, QColor(*glossy(rgb)))
            return halo, line

        def paint(self, strip) -> None:
            alpha = glow_alpha(self.level, self.state if self.state != "idle" else "speaking",
                               self.clock.elapsed() / 1000)
            if alpha <= 0.0 or strip.halo is None:
                return
            halo_colours, line_colours = self.gradients(strip)
            p = QPainter(strip)
            # The halo: colours over the whole strip, cut to the soft halo shape.
            p.setOpacity(alpha)
            p.fillRect(strip.rect(), halo_colours)
            p.setOpacity(1.0)
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
            p.drawImage(0, 0, strip.halo)
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
            if strip.buffer is not None:
                # The glossy line, made in a small scratch image covering only
                # its band, then laid on top of the halo.
                buf = strip.buffer
                buf.fill(0)
                bp = QPainter(buf)
                bp.translate(-strip.line_at.x(), -strip.line_at.y())
                bp.fillRect(QRectF(strip.line_at, QPointF(strip.line_at.x() + buf.width(),
                                                          strip.line_at.y() + buf.height())),
                            line_colours)
                bp.resetTransform()
                bp.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
                bp.drawImage(0, 0, strip.line)
                bp.end()
                p.setOpacity(alpha)
                p.drawImage(strip.line_at, buf)
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
