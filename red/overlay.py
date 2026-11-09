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

# The glow is frosted glass along the screen edges, not coloured light, and
# with no line or rim anywhere:
# - a milky white haze that fades in from each edge,
# - liquid: the haze swells and thins in slow waves that flow along the edges,
# - glassy: a soft sheen of light glides through the haze now and then,
# - soft, muted clouds of colour drifting underneath, as if the haze is lit.

# The colour clouds per state: muted and pale, never neon. Aqua and amber
# while listening and speaking, cooler while thinking or asking.
GLOW_PALETTES = {
    "listening": ("#7fdcd7", "#efc97f", "#c7d3e2", "#9fe3dd"),
    "thinking": ("#a3c4f3", "#c3b8ec", "#8fd8d4", "#d3dbe6"),
    "confirm": ("#9cc3f5", "#b8d4f8", "#86aee8", "#cfe0f7"),
    "speaking": ("#efc97f", "#8fdcd6", "#e6d5bd", "#b9e3df"),
    "error": ("#f0b56f", "#ec9c7c", "#f3d09a", "#e2c3a6"),
}
GLOW_SPEED = {          # how fast the colour clouds drift: share of the screen's edge per second
    "listening": 0.025,
    "thinking": 0.07,
    "confirm": 0.02,
    "speaking": 0.04,
    "error": 0.015,
}
GLOW_PULSE = {          # breaths per second
    "listening": 0.45,
    "thinking": 0.9,
    "confirm": 0.4,
    "speaking": 1.1,
    "error": 1.2,
}
GLOW_DEPTH = 96         # pixels: how far the haze reaches in, where it swells most
GLOW_SHINE_SPEED = 0.06 # share of the edge the gleam travels per second
GLOW_FPS = 24           # the motion is slow, so this is smooth and lighter on the CPU
GLOW_FADE_IN = 0.35     # seconds
GLOW_FADE_OUT = 0.8     # seconds
GLOW_STOPS = 24         # samples along each strip (enough for the waves and corners)
GLASS_WHITE = (255, 255, 255)
LAYERS = ("haze", "swell", "clouds", "sheen")
GLOW_WAVE_SPEED = 0.03  # share of the edge the liquid waves travel per second


def soft_edge_distance(xs, ys, width: int, height: int, softness: float = 26.0):
    """Like the distance to the nearest edge, but rounded wherever two edges are close.

    A plain minimum makes a sharp diagonal crease in each corner; this soft
    minimum turns every line of equal distance into a smooth curve, so the
    haze bends round the corners too.
    """
    import numpy as np

    k = float(softness)
    parts = np.stack([xs, width - 1 - xs, ys, height - 1 - ys]).astype(np.float64)
    low = parts.min(axis=0)
    return (low - k * np.log(np.exp(-(parts - low) / k).sum(axis=0))).astype(np.float32)


def glass_profile(distance, depth: float) -> dict:
    """Strength 0..1 of each glass layer at `distance` pixels in from the edge.

    haze: the thin, always-there milky glass. swell: the extra haze where the
    liquid wave is high (haze + swell is the thickest the glass gets). clouds:
    where the colour sits. sheen: a soft band of light inside the haze, shown
    only where a gleam passes. None of them is a hard line.
    """
    import numpy as np

    a = np.abs(np.asarray(distance, dtype=np.float32))
    tail = np.clip(1.0 - (a / float(depth)) ** 2, 0.0, 1.0) ** 2
    thin = (0.24 * np.exp(-(a / 15.0) ** 2) + 0.12 * np.exp(-(a / 32.0) ** 2)) * tail
    thick = (0.32 * np.exp(-(a / 26.0) ** 2) + 0.20 * np.exp(-(a / 58.0) ** 2)) * tail
    return {
        "haze": np.clip(thin, 0, 1),
        "swell": np.clip(thick - thin, 0, 1),
        "clouds": np.clip((0.70 * np.exp(-(a / 18.0) ** 2) + 0.30 * np.exp(-(a / 44.0) ** 2)) * tail, 0, 1),
        "sheen": np.clip(0.55 * np.exp(-((a - 14.0) / 11.0) ** 2) * tail, 0, 1),
    }


def glass_masks(x0: int, y0: int, w: int, h: int, screen_w: int, screen_h: int,
                depth: int = GLOW_DEPTH) -> dict:
    """Each glass layer's strength for every pixel of one strip, as uint8 (h, w) arrays.

    (x0, y0) is the strip's corner relative to the screen's corner.
    """
    import numpy as np

    ys, xs = np.mgrid[y0:y0 + h, x0:x0 + w].astype(np.float32)
    # The soft distance curves the haze round the corners, with no creases.
    layers = glass_profile(soft_edge_distance(xs, ys, screen_w, screen_h), depth)
    return {name: np.round(v * 255).astype(np.uint8) for name, v in layers.items()}


def _hex_rgb(colour: str) -> tuple[float, float, float]:
    colour = colour.lstrip("#")
    return tuple(int(colour[i:i + 2], 16) / 255 for i in (0, 2, 4))  # type: ignore[return-value]


@functools.lru_cache(maxsize=16)
def _linear_palette(palette: tuple[str, ...]):
    import numpy as np

    return np.array([_hex_rgb(c) for c in palette], dtype=np.float64) ** 2.2


def flow_colours(positions, seconds: float, palette: tuple[str, ...],
                 speed: float) -> list[tuple[int, int, int]]:
    """The colour at each position (0..1 round the screen's edge) at time `seconds`.

    Each palette colour is a soft cloud drifting round the edge at its own
    speed (some the other way). Colours are mixed in linear light, so blends
    stay clean instead of turning muddy.
    """
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


def flow_colour(position: float, seconds: float, palette: tuple[str, ...],
                speed: float) -> tuple[int, int, int]:
    """flow_colours for one position."""
    return flow_colours([position], seconds, palette, speed)[0]


def shine(positions, seconds: float) -> list[float]:
    """How strong the sheen is at each position (0..1 round the edge): 0 to 1.

    Two gleams travel round the edge in opposite directions, slowly, like
    light sliding across glass; elsewhere there is no sheen at all.
    """
    import numpy as np

    pos = np.asarray(positions, dtype=np.float64)
    out = np.zeros_like(pos)
    for start, direction in ((0.12, 1.0), (0.62, -1.0)):
        centre = (start + direction * GLOW_SHINE_SPEED * seconds) % 1.0
        gap = np.abs(pos - centre)
        gap = np.minimum(gap, 1.0 - gap)
        out = np.maximum(out, np.exp(-(gap / 0.07) ** 2))
    return list(out)


def liquid(positions, seconds: float) -> list[float]:
    """How swollen the glass is at each position (0..1 round the edge): 0..1.

    Two slow waves of different lengths flow in opposite directions, so the
    bulges grow, merge and drift like liquid instead of marching in step.
    """
    import numpy as np

    pos = np.asarray(positions, dtype=np.float64)
    t = GLOW_WAVE_SPEED * seconds
    wave = (0.6 * np.sin(2 * np.pi * (3 * pos - t))
            + 0.4 * np.sin(2 * np.pi * (5 * pos + 1.7 * t) + 1.3))
    return list(np.clip(0.5 + 0.5 * wave, 0.0, 1.0))


def corner_snap(positions, screen_w: int, screen_h: int, depth: int) -> list[float]:
    """Hold the flowing effects steady near each corner, so the strips agree there.

    In a corner, the top strip and the side strip cover the same patch of
    glass but would read the waves and colours from different spots along
    the edge, which shows as a faint step where they meet. Within `depth`
    of a corner every position is moved to the corner itself, and just past
    that it catches up smoothly, so nothing jumps.
    """
    p = 2.0 * (screen_w + screen_h)
    corners = (0.0, screen_w / p, (screen_w + screen_h) / p, (2 * screen_w + screen_h) / p)
    flat = depth / p
    ramp = depth / p
    out = []
    for pos in positions:
        best, sign, dist = 0.0, 1.0, 2.0
        for c in corners:
            gap = (pos - c) % 1.0
            if gap > 0.5:
                gap -= 1.0
            if abs(gap) < dist:
                best, sign, dist = c, (1.0 if gap >= 0 else -1.0), abs(gap)
        if dist <= flat:
            out.append(best % 1.0)
        elif dist < flat + ramp:
            out.append((best + sign * (dist - flat) * (flat + ramp) / ramp) % 1.0)
        else:
            out.append(pos % 1.0)
    return out


def perimeter_span(side: str, x: int, y: int, w: int, h: int, screen_w: int, screen_h: int):
    """Where a strip's own top (or left) end and its other end sit along the edge, 0..1 clockwise."""
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
    """How strong the glass is right now: the fade level times a gentle breath."""
    pulse = GLOW_PULSE.get(state, 1.0)
    breath = 0.88 + 0.12 * math.sin(seconds * 2 * math.pi * pulse)
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
    redrawn whole on every frame, and the strips are a fraction of the pixels.
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

    ARGB = QImage.Format.Format_ARGB32_Premultiplied

    def to_image(values, rgb=(255, 255, 255)):
        """An image of colour `rgb` whose alpha is `values` (uint8 rows)."""
        import numpy as np

        h, w = values.shape
        a = values.astype(np.uint32)
        r, g, b = ((a * c + 127) // 255 for c in rgb)            # premultiplied
        pixels = np.ascontiguousarray((a << 24) | (r << 16) | (g << 8) | b)
        return QImage(pixels.data, w, h, w * 4, ARGB).copy()

    class Layer:
        """One glass layer of a strip, cropped to where it isn't empty."""

        def __init__(self, values, rgb=(255, 255, 255)):
            import numpy as np

            rows = np.flatnonzero(values.any(axis=1))
            cols = np.flatnonzero(values.any(axis=0))
            self.empty = not (rows.size and cols.size)
            if self.empty:
                return
            r0, r1, c0, c1 = rows[0], rows[-1] + 1, cols[0], cols[-1] + 1
            self.at = QPointF(float(c0), float(r0))
            self.image = to_image(np.ascontiguousarray(values[r0:r1, c0:c1]), rgb)
            self.buffer = QImage(int(c1 - c0), int(r1 - r0), ARGB)

        def tinted(self, colours) -> QImage:
            """This layer's shape filled with `colours` (a gradient in strip coordinates)."""
            buf = self.buffer
            buf.fill(0)
            bp = QPainter(buf)
            bp.translate(-self.at.x(), -self.at.y())
            bp.fillRect(QRectF(self.at.x(), self.at.y(), buf.width(), buf.height()), colours)
            bp.resetTransform()
            bp.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
            bp.drawImage(0, 0, self.image)
            bp.end()
            return buf

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
            self.layers: dict[str, Layer] = {}   # made when placed
            self.span = (0.0, 0.0)

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
            self.flow = 0.0           # how far the clouds have drifted (speed changes stay smooth)
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
            if QRectF(g) == self.screen and all(s.layers for s in self.strips.values()):
                return
            self.screen = QRectF(g)
            for side, (x, y, w, h) in edge_strips(g.x(), g.y(), g.width(), g.height(),
                                                  self.depth).items():
                strip = self.strips[side]
                strip.setGeometry(x, y, w, h)
                lx, ly = x - g.x(), y - g.y()
                strip.span = perimeter_span(side, lx, ly, w, h, g.width(), g.height())
                strip.layers = {}
                if w <= 0 or h <= 0:
                    continue
                try:
                    masks = glass_masks(lx, ly, w, h, g.width(), g.height(), self.depth)
                except ImportError:          # no numpy: show nothing rather than fail
                    continue
                for name in LAYERS:
                    layer = Layer(masks[name], GLASS_WHITE)
                    if not layer.empty:
                        strip.layers[name] = layer

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
            """(colour clouds, liquid swell, sheen) along this strip, as gradients over its long side."""
            w, h = strip.width(), strip.height()
            far = QPointF(w, 0) if strip.side in ("top", "bottom") else QPointF(0, h)
            clouds, swell, sheen = (QLinearGradient(QPointF(0, 0), far) for _ in range(3))
            start, end = strip.span
            ts = [i / GLOW_STOPS for i in range(GLOW_STOPS + 1)]
            positions = corner_snap([(start + (end - start) * t) % 1.0 for t in ts],
                                    int(self.screen.width()), int(self.screen.height()), self.depth)
            seconds = self.clock.elapsed() / 1000
            colours = flow_colours(positions, self.flow, self.palette, GLOW_SPEED["listening"])
            waves = liquid(positions, self.flow)
            gleams = shine(positions, seconds)
            for t, rgb, wave, gleam in zip(ts, colours, waves, gleams):
                clouds.setColorAt(t, QColor(*rgb))
                swell.setColorAt(t, QColor(255, 255, 255, int(255 * wave)))
                sheen.setColorAt(t, QColor(255, 255, 255, int(255 * gleam)))
            return clouds, swell, sheen

        def paint(self, strip) -> None:
            alpha = glow_alpha(self.level, self.state if self.state != "idle" else "speaking",
                               self.clock.elapsed() / 1000)
            layers = strip.layers
            if alpha <= 0.0 or not layers:
                return
            clouds, swell, sheen = self.gradients(strip)
            p = QPainter(strip)
            if "haze" in layers:                       # the milky glass, always there
                p.setOpacity(alpha * 0.9)
                p.drawImage(layers["haze"].at, layers["haze"].image)
            if "swell" in layers:                      # liquid: thicker where the wave is high
                p.setOpacity(alpha * 0.9)
                p.drawImage(layers["swell"].at, layers["swell"].tinted(swell))
            if "clouds" in layers:                     # colour drifting underneath
                p.setOpacity(alpha * 0.5)
                p.drawImage(layers["clouds"].at, layers["clouds"].tinted(clouds))
            if "sheen" in layers:                      # glassy: light gliding through
                p.setOpacity(alpha * 0.8)
                p.drawImage(layers["sheen"].at, layers["sheen"].tinted(sheen))
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
