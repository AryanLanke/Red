"""The companion's window (PySide6): it peeks over the bottom edge of the screen.

- It sits on the bottom edge of the work area (above the taskbar), anywhere along it or in a corner,
  forearms on the edge. Breathing is a slight stretch of the picture, so it never looks frozen.
- Hover: it brightens up (or wakes up if it was asleep). Click: the chat window opens. Right-click: a menu.
- Press and drag: you pick it up. The whole body shows, dangling and swinging under the cursor, and it
  says "whoa!". Let go and it drops back to the edge where you let go.
- While Red talks, the mouth follows the voice (MouthMeter) and a speech bubble types the reply out.
- Marks over the head (zzz, !, ?, a tear, an anger mark, a note) make the feeling readable when small.
- Asleep after 5 minutes of nothing; hidden while a full-screen app or game is in front.

`set_state()` is safe from any thread (a Qt signal), like the other overlays in red/overlay.py.
Transparent pixels let clicks through to the window below (a Windows layered window), so only the
character itself is clickable.
"""

from __future__ import annotations

import functools
import json
import logging
import math
import random
import time
from pathlib import Path
from typing import Callable

from . import (SIDES, SIZES, SLEEP_AFTER_SECONDS, Look, MouthMeter, Sprites, available_companions,
               clip_paths, companion_folder, emotion_from_text, frame_for_side, kokoro_synthesizer,
               load_sprites, make_clips, mark_for, meter_speaker, pick_frame, play_clip, side_for)
from ..overlay import STATES, Overlay, _check_state, _clean

log = logging.getLogger(__name__)

BUBBLE_SPACE = 150         # logical pixels above the head kept for the bubble and the marks
BUBBLE_WIDTH = 270
BUBBLE_TEXT = 200          # characters shown in the bubble
TYPE_SPEED = 38            # characters per second
BUBBLE_HOLD = 5.0          # seconds the bubble stays after Red goes quiet
DRAG_START = 6             # pixels of movement before a press becomes a pickup
GRAVITY = 3200.0           # pixels per second squared when dropped
HOVER_SECONDS = 1.6
NOTICE_SECONDS = 0.9
GREETING_SECONDS = 1.6
EMOTION_HOLD = 4.0         # an emotion lingers this long after Red stops talking
FAST, NORMAL, SLOW = 33, 100, 500      # timer intervals (ms): animating, awake, asleep
SIDE_PAD = 24
CORNER_SNAP = 180          # dropped this close to a side of the screen: it goes into that corner


def fullscreen_app_in_front() -> bool:
    """True when the window in front covers its whole monitor (a game, a video, a presentation)."""
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        if not hwnd or hwnd in (user32.GetDesktopWindow(), user32.GetShellWindow()):
            return False
        name = ctypes.create_unicode_buffer(64)
        user32.GetClassNameW(hwnd, name, 64)
        if name.value in ("Progman", "WorkerW", "Shell_TrayWnd"):
            return False
        rect = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))

        class MONITORINFO(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                        ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]
        info = MONITORINFO()
        info.cbSize = ctypes.sizeof(MONITORINFO)
        monitor = user32.MonitorFromWindow(hwnd, 2)
        if not user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
            return False
        m = info.rcMonitor
        return rect.left <= m.left and rect.top <= m.top and rect.right >= m.right and rect.bottom >= m.bottom
    except Exception:  # noqa: BLE001 - not Windows, or the call failed: never hide by mistake
        return False


@functools.cache
def _window_class():
    from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
    from PySide6.QtGui import (QColor, QFont, QFontMetricsF, QGuiApplication, QPainter, QPainterPath,
                               QPen, QPixmap)
    from PySide6.QtWidgets import QMenu, QWidget

    class CompanionWindow(QWidget):
        state_changed = Signal(str, str)
        finished = Signal()

        def __init__(self, sprites: Sprites, *, size: str = "medium", models_dir: Path | None = None,
                     companion: str = "red", state_file: Path | None = None,
                     clock: Callable[[], float] = time.monotonic, meter: MouthMeter | None = None,
                     check_fullscreen: Callable[[], bool] = fullscreen_app_in_front):
            super().__init__(None)
            self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
                                | Qt.WindowType.Tool | Qt.WindowType.WindowDoesNotAcceptFocus)
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
            self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
            self.setMouseTracking(True)
            self.setWindowTitle("Red companion")
            self.clock = clock
            self.meter = meter or MouthMeter()
            self.models_dir = models_dir
            self.companion = companion
            self.state_file = state_file
            self.check_fullscreen = check_fullscreen
            self.on_click: Callable[[], None] | None = None
            self.size_name = size if size in SIZES else "medium"
            self.look = Look(since=clock())
            self.last_activity = clock()
            self.until: dict[str, float] = {}           # temporary states and emotions -> end time
            self.turn_emotion: str | None = None
            self.bubble_text = ""
            self.bubble_started = 0.0
            self.bubble_until = 0.0
            self.press_at: QPointF | None = None
            self.grab_offset = QPointF(0, 0)
            self.drag_pos = QPointF(0, 0)
            self.last_drag = (QPointF(0, 0), 0.0)
            self.swing = 0.0
            self.swing_speed = 0.0
            self.fall_y = 0.0
            self.fall_v = 0.0
            self.hidden_for_fullscreen = False
            self.frame_name = ""
            self.pickup_clips: list[Path] = []
            self.drop_clips: list[Path] = []
            self.x_center: float | None = None
            self.side = "right"                          # edge, left or right (a bottom corner)
            self.load(sprites)
            self._restore()

            self.state_changed.connect(self._apply, Qt.ConnectionType.QueuedConnection)
            self.timer = QTimer(self)
            self.timer.timeout.connect(self.tick)
            self.timer.start(NORMAL)
            self.full_timer = QTimer(self)
            self.full_timer.timeout.connect(self._check_fullscreen)
            self.full_timer.start(2000)

        # --- pictures --------------------------------------------------------

        def load(self, sprites: Sprites) -> None:
            self.sprites = sprites
            dpr = max(1.0, self.devicePixelRatioF())
            self.scale = SIZES[self.size_name] / sprites.px_per_metre
            self.pixmaps: dict[str, QPixmap] = {}
            for name, frame in sprites.frames.items():
                pm = QPixmap(str(frame.path))
                if pm.isNull():
                    continue
                pm = pm.scaled(round(pm.width() * self.scale * dpr), round(pm.height() * self.scale * dpr),
                               Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
                pm.setDevicePixelRatio(dpr)
                self.pixmaps[name] = pm
            peek = self.pixmaps["peek_idle"]
            self.set_size = {}                           # frame set -> (width, height) on screen
            for set_name in ("peek", "cornerR", "cornerL", "body"):
                pm = next((p for n, p in self.pixmaps.items() if n.startswith(set_name + "_")), None)
                if pm is not None:
                    self.set_size[set_name] = (pm.width() / dpr, pm.height() / dpr)
            self.body_w, self.body_h = self.set_size.get("body", self.set_size["peek"])

        def has(self, name: str) -> bool:
            return name in self.pixmaps

        @property
        def prefix(self) -> str:
            """The frame set for where it sits; a corner the model has no frames for is the edge."""
            prefix = SIDES.get(self.side, "peek")
            return prefix if prefix in self.set_size else "peek"

        @property
        def perch_size(self) -> tuple[float, float]:
            return self.set_size[self.prefix]

        def mark_point(self, name: str, key: str = "head") -> QPointF:
            """A mark of the current frame, in the frame's display pixels."""
            frame = self.sprites.frames.get(name) or self.sprites.frames["peek_idle"]
            x, y = frame.marks.get(key, [0, 0])
            return QPointF(x * self.scale, y * self.scale)

        # --- where it sits ---------------------------------------------------

        def perch(self) -> None:
            """Sit in a bottom corner (side left/right, flush with the screen's side) or on the bottom
            edge at x_center (the middle of the character)."""
            area = QGuiApplication.primaryScreen().availableGeometry() if self.x_center is None \
                else self._area_for(self.x_center)
            w, h = self.perch_size
            width = max(w, BUBBLE_WIDTH) + (SIDE_PAD if self.prefix != "peek" else 2 * SIDE_PAD)
            height = BUBBLE_SPACE + h
            top = round(area.bottom() + 1 - height)
            if self.prefix == "cornerR":
                left = area.right() + 1 - width
                self.x_center = area.right() + 1 - w / 2
            elif self.prefix == "cornerL":
                left = area.left()
                self.x_center = area.left() + w / 2
            else:
                if self.x_center is None:
                    self.x_center = area.right() - w / 2 - SIDE_PAD
                self.x_center = min(max(self.x_center, area.left() + w / 2), area.right() - w / 2)
                left = self.x_center - width / 2
            self.setGeometry(round(left), top, round(width), round(height))

        def sprite_left(self, w: float) -> float:
            """Where the picture starts inside the window: flush with the screen side in a corner."""
            if self.prefix == "cornerR":
                return self.width() - w
            if self.prefix == "cornerL":
                return 0.0
            return (self.width() - w) / 2

        def place(self, side: str) -> None:
            self.side = side if side in SIDES else "edge"
            self.perch()
            self._save()
            self.until["notice"] = self.clock() + NOTICE_SECONDS

        def _area_for(self, x: float):
            for screen in QGuiApplication.screens():
                g = screen.availableGeometry()
                if g.left() <= x <= g.right():
                    return g
            return QGuiApplication.primaryScreen().availableGeometry()

        def _restore(self) -> None:
            try:
                saved = json.loads(Path(self.state_file).read_text(encoding="utf-8")) if self.state_file else {}
                self.x_center = float(saved["x"]) if saved.get("x") is not None else None
                self.side = saved.get("side", "right") if saved.get("side") in SIDES else "right"
            except (OSError, ValueError, KeyError, TypeError):
                self.x_center = None
            self.perch()

        def _save(self) -> None:
            if not self.state_file:
                return
            try:
                Path(self.state_file).parent.mkdir(parents=True, exist_ok=True)
                Path(self.state_file).write_text(json.dumps({"x": self.x_center, "side": self.side,
                                                             "companion": self.companion}), encoding="utf-8")
            except OSError:
                log.debug("Couldn't save the companion's spot", exc_info=True)

        # --- states from Red ---------------------------------------------------

        def _apply(self, state: str, text: str) -> None:
            now = self.clock()
            previous = self.look.state
            if state != "idle":
                self.last_activity = now
                if not self.isVisible() and not self.hidden_for_fullscreen:
                    self.show()                          # "Hide until Red talks"
            if previous == "sleeping" and state != "idle":
                self.until["notice"] = now + NOTICE_SECONDS
            if state == "listening" and previous in ("idle", "sleeping"):
                self.until["notice"] = now + NOTICE_SECONDS
            if state == "speaking":
                feeling = emotion_from_text(text)
                if feeling == "greeting":
                    self.until["greeting"] = now + GREETING_SECONDS
                    feeling = "happy"
                if feeling:
                    self.turn_emotion = feeling
                self._bubble(text, now)
            elif state in ("error", "confirm") and text:
                self._bubble(text, now)
            elif state in ("listening", "thinking"):
                if state == "listening":
                    self.turn_emotion = None
                self.bubble_until = now          # the last reply goes once you talk again
            if state == "idle":
                self.bubble_until = now + BUBBLE_HOLD
                if self.turn_emotion:
                    self.until["emotion"] = now + EMOTION_HOLD
            self.look.state = state
            self.look.since = now
            self._speed(FAST)
            self.tick()

        def _bubble(self, text: str, now: float) -> None:
            first = (text or "").strip().split("\n")[0]
            if len(first) > BUBBLE_TEXT:
                first = first[:BUBBLE_TEXT - 1].rstrip() + "…"
            if first != self.bubble_text:
                self.bubble_text = first
                self.bubble_started = now
            self.bubble_until = float("inf")

        # --- the clock --------------------------------------------------------

        def _speed(self, interval: int) -> None:
            if self.timer.interval() != interval:
                self.timer.setInterval(interval)

        def tick(self) -> None:
            now = self.clock()
            look = self.look
            for key in [k for k, end in self.until.items() if end <= now]:
                del self.until[key]
                if key == "emotion":
                    self.turn_emotion = None
            if look.state == "idle" and now - self.last_activity > SLEEP_AFTER_SECONDS and not look.dragging:
                look.state = "sleeping"
            look.mouth = self.meter.level() if look.state == "speaking" else 0.0
            look.emotion = "happy" if "hover" in self.until else self.turn_emotion

            if look.falling:
                self._fall(now)                          # may land, so before the frame is picked
            shown = Look(**vars(look))
            if "greeting" in self.until:
                shown.state, shown.since = "greeting", self.until["greeting"] - GREETING_SECONDS
            elif "notice" in self.until and look.state in ("listening", "idle", "sleeping"):
                shown.state = "notice"
            self.frame_name = frame_for_side(pick_frame(shown, now, self.has), self.side, self.has)
            self.shown = shown

            busy = (look.dragging or look.falling or look.state in ("speaking", "greeting") or self.until
                    or self._typing(now))
            self._speed(FAST if busy else SLOW if look.state == "sleeping" else NORMAL)
            self.update()

        def _typing(self, now: float) -> bool:
            return bool(self.bubble_text) and (now - self.bubble_started) * TYPE_SPEED < len(self.bubble_text)

        def _check_fullscreen(self) -> None:
            if self.look.dragging:
                return
            full = bool(self.check_fullscreen())
            if full and self.isVisible():
                self.hidden_for_fullscreen = True
                self.hide()
            elif not full and self.hidden_for_fullscreen:
                self.hidden_for_fullscreen = False
                self.show()

        # --- picking it up ----------------------------------------------------

        def press(self, pos: QPointF) -> None:
            self.press_at = QPointF(pos)

        def move(self, pos: QPointF) -> None:
            if self.press_at is None:
                return
            if not self.look.dragging:
                if (pos - self.press_at).manhattanLength() < DRAG_START:
                    return
                self._pick_up(pos)
            now = self.clock()
            last_pos, last_t = self.last_drag
            dt = max(1e-3, now - last_t)
            vx = (pos.x() - last_pos.x()) / dt
            self.swing_speed = max(-2500.0, min(2500.0, vx))
            self.last_drag = (QPointF(pos), now)
            self.drag_pos = QPointF(pos)
            self._place_dragged()

        def release(self, pos: QPointF) -> None:
            pressed, self.press_at = self.press_at, None
            if self.look.dragging:
                self.look.dragging = False
                self.look.falling = True
                self.fall_v = 0.0
                self.fall_y = self.geometry().top()
                area = self._area_for(pos.x())
                self.side = side_for(pos.x(), area.left(), area.right(), CORNER_SNAP)
                self._sound(self.drop_clips)
                self._speed(FAST)
                return
            if pressed is not None and self.on_click:
                try:
                    self.on_click()
                except Exception:  # noqa: BLE001 - the window must survive a broken callback
                    log.exception("Companion click failed")

        def _pick_up(self, pos: QPointF) -> None:
            self.look.dragging = True
            self.last_activity = self.clock()
            self.until.pop("hover", None)
            if self.look.state == "sleeping":
                self.look.state = "idle"
            self.turn_emotion = "happy" if random.random() < 0.25 else None      # sometimes it enjoys it
            self.last_drag = (QPointF(pos), self.clock())
            self.swing = 0.0
            self._sound(self.pickup_clips)
            # Hold it by the top of the head: the grab point is above the head mark.
            body_head = self.mark_point("body_drag_1")
            self.grab_offset = QPointF(body_head.x(), body_head.y() - 0.16 * SIZES[self.size_name])
            self._speed(FAST)

        # While carried, the window is big enough for the whole body swinging either way, and the
        # grab point (the top of the head) sits at `hold` inside it, under the cursor.
        @property
        def hold(self) -> QPointF:
            width = self.body_w + self.body_h
            return QPointF(width / 2, self.grab_offset.y() + 20)

        def _place_dragged(self) -> None:
            hold = self.hold
            width = self.body_w + self.body_h
            self.setGeometry(round(self.drag_pos.x() - hold.x()), round(self.drag_pos.y() - hold.y()),
                             round(width), round(self.body_h + 60))

        def _fall(self, now: float) -> None:
            dt = 1 / 30
            self.fall_v += GRAVITY * dt
            self.fall_y += self.fall_v * dt
            area = self._area_for(self.drag_pos.x())
            # Lands when the falling head reaches where the head is when peeking, so the switch from
            # the whole body to peeking happens with the head in the same place.
            grab_to_head = self.mark_point("body_drop").y() - self.grab_offset.y()
            head_y = self.fall_y + self.hold.y() + grab_to_head
            peek_head_y = area.bottom() + 1 - self.perch_size[1] + self.mark_point(f"{self.prefix}_idle").y()
            if head_y >= peek_head_y:
                self.look.falling = False
                self.x_center = self.drag_pos.x()
                self.until["notice"] = now + NOTICE_SECONDS
                self.perch()
                self._save()
                return
            g = self.geometry()
            self.setGeometry(g.left(), round(self.fall_y), g.width(), g.height())

        def _sound(self, clips: list[Path]) -> None:
            existing = [p for p in clips if p.exists()]
            if existing and self.meter.level() == 0.0:          # never over Red's own voice
                play_clip(random.choice(existing))

        # --- Qt events --------------------------------------------------------

        def mousePressEvent(self, event):  # noqa: N802
            if event.button() == Qt.MouseButton.LeftButton:
                self.press(event.globalPosition())

        def mouseMoveEvent(self, event):  # noqa: N802
            self.move(event.globalPosition())

        def mouseReleaseEvent(self, event):  # noqa: N802
            if event.button() == Qt.MouseButton.LeftButton:
                self.release(event.globalPosition())

        def enterEvent(self, event):  # noqa: N802
            now = self.clock()
            if self.look.dragging or self.look.falling:
                return
            if self.look.state == "sleeping":
                self.look.state = "idle"
                self.until["notice"] = now + NOTICE_SECONDS
            elif self.look.state == "idle":
                self.until["hover"] = now + HOVER_SECONDS
            self.last_activity = now
            self.tick()

        def contextMenuEvent(self, event):  # noqa: N802
            menu = QMenu()
            if self.on_click:
                menu.addAction("Open chat", self.on_click)
            menu.addSeparator()
            for side, label in (("left", "Sit in the left corner"), ("edge", "Sit on the bottom edge"),
                                ("right", "Sit in the right corner")):
                if side != self.side:
                    menu.addAction(label, functools.partial(self.place, side))
            if self.models_dir is not None:
                menu.addSeparator()
                for cid, name in available_companions(self.models_dir).items():
                    if cid != self.companion:
                        menu.addAction(f"Switch to {name}", functools.partial(self.switch, cid))
            menu.addSeparator()
            menu.addAction("Hide until Red talks", self.hide)
            menu.exec(event.globalPos())

        def switch(self, companion: str) -> None:
            try:
                sprites = load_sprites(companion_folder(self.models_dir, companion))
            except (OSError, ValueError, KeyError) as e:
                log.warning("Couldn't switch to %s: %s", companion, e)
                return
            self.companion = companion
            self.load(sprites)
            self.perch()
            self._save()
            self.set_clips(self._clips_for(companion, None))
            self.until["notice"] = self.clock() + NOTICE_SECONDS

        def _clips_for(self, companion: str, default_voice: str | None) -> tuple[list[Path], list[Path], str]:
            voice = self.sprites.voice or default_voice or getattr(self, "default_voice", None) or "af_heart"
            self.default_voice = default_voice or getattr(self, "default_voice", None)
            folder = self.sprites.folder
            return clip_paths(folder, voice, "pickup"), clip_paths(folder, voice, "drop"), voice

        def set_clips(self, clips) -> None:
            self.pickup_clips, self.drop_clips = list(clips[0]), list(clips[1])

        # --- drawing ----------------------------------------------------------

        def paintEvent(self, event):  # noqa: N802
            now = self.clock()
            pm = self.pixmaps.get(self.frame_name) or self.pixmaps["peek_idle"]
            dpr = pm.devicePixelRatio()
            w, h = pm.width() / dpr, pm.height() / dpr
            p = QPainter(self)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            if self.look.dragging or self.look.falling:
                self._paint_dangling(p, pm, w, h, now)
                p.end()
                return
            left = self.sprite_left(w)
            top = self.height() - h
            asleep = self.look.state == "sleeping"
            breath = (0.014 if asleep else 0.007) * math.sin(now * 2 * math.pi / (5.0 if asleep else 3.6))
            p.save()
            p.translate(left + w / 2, self.height())
            p.scale(1.0, 1.0 + breath)
            p.drawPixmap(QPointF(-w / 2, -h), pm)
            p.restore()
            head = self.mark_point(self.frame_name) + QPointF(left, top)
            mark = mark_for(self.shown) if hasattr(self, "shown") else None
            if mark:
                self._paint_mark(p, mark, head, now)
            if self.bubble_text and now < self.bubble_until:
                self._paint_bubble(p, head, now)
            p.end()

        def _paint_dangling(self, p, pm, w, h, now) -> None:
            # A pendulum: the body leans against the way you move it, then settles.
            target = -self.swing_speed / 2500.0 * 28.0
            self.swing += (target - self.swing) * 0.25
            self.swing_speed *= 0.85
            wobble = 3.0 * math.sin(now * 7.0) if self.look.dragging else 0.0
            p.translate(self.hold)
            p.rotate(self.swing + wobble)
            p.drawPixmap(QPointF(-self.grab_offset.x(), -self.grab_offset.y()), pm)

        def _paint_mark(self, p, mark: str, head: QPointF, now: float) -> None:
            unit = SIZES[self.size_name] / 300.0
            top = QPointF(head.x() + 34 * unit, head.y() - 70 * unit)
            bob = 3 * unit * math.sin(now * 3.0)
            ink = QColor("#2b2b33")
            font = QFont("Segoe UI", max(9, round(20 * unit)))
            font.setBold(True)
            p.setFont(font)
            if mark == "zzz":
                for i, size in enumerate((14, 19, 25)):
                    t = (now * 0.5 + i * 0.33) % 1.0
                    f = QFont(font)
                    f.setPointSizeF(size * unit)
                    p.setFont(f)
                    p.setPen(QColor(60, 80, 150, int(255 * min(1.0, 1.4 * (1 - t)))))
                    p.drawText(QPointF(top.x() + i * 12 * unit, top.y() + 20 * unit - t * 30 * unit), "z")
            elif mark in ("exclaim", "question"):
                p.setPen(QPen(QColor("#e5484d") if mark == "exclaim" else ink))
                p.drawText(QPointF(top.x(), top.y() + bob), "!" if mark == "exclaim" else "?")
            elif mark == "dots":
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(ink)
                for i in range(3):
                    lift = 3 * unit * math.sin(now * 6 - i * 0.8)
                    p.drawEllipse(QPointF(top.x() + i * 9 * unit, top.y() + lift), 3 * unit, 3 * unit)
            elif mark == "note":
                p.setPen(QColor("#e0609a"))
                p.drawText(QPointF(top.x(), top.y() + bob), "♪")
            elif mark == "anger":
                pen = QPen(QColor("#e5484d"), 3.5 * unit)
                p.setPen(pen)
                c = QPointF(top.x() + 6 * unit, top.y() - 8 * unit)
                r = 9 * unit
                for dx, dy, start in ((-1, -1, 270), (1, -1, 180), (1, 1, 90), (-1, 1, 0)):
                    rect = QRectF(c.x() + dx * r - r, c.y() + dy * r - r, 2 * r, 2 * r)
                    p.drawArc(rect, start * 16, 90 * 16)
            elif mark in ("tear", "sweat"):
                # The head mark is the base of the skull: the eyes are about 7 cm above it.
                fall = ((now * 0.8) % 1.0) * 10 * unit if mark == "tear" else 0.0
                x = head.x() + (11 if mark == "tear" else 27) * unit
                y = head.y() - (19 if mark == "tear" else 44) * unit + fall
                path = QPainterPath()
                path.moveTo(x, y - 9 * unit)
                path.cubicTo(x + 7 * unit, y, x + 5 * unit, y + 7 * unit, x, y + 7 * unit)
                path.cubicTo(x - 5 * unit, y + 7 * unit, x - 7 * unit, y, x, y - 9 * unit)
                p.setPen(QPen(QColor(60, 120, 200), 1.2))
                p.setBrush(QColor(140, 195, 250, 220))
                p.drawPath(path)

        def _paint_bubble(self, p, head: QPointF, now: float) -> None:
            shown = self.bubble_text[: max(0, int((now - self.bubble_started) * TYPE_SPEED))]
            if not shown:
                return
            font = QFont("Segoe UI", 10)
            p.setFont(font)
            metrics = QFontMetricsF(font)
            inner = BUBBLE_WIDTH - 24
            full = metrics.boundingRect(QRectF(0, 0, inner, 1000), Qt.TextFlag.TextWordWrap, self.bubble_text)
            height = min(full.height(), BUBBLE_SPACE - 40) + 18
            width = min(inner, max(60.0, full.width())) + 24
            fade = 1.0 if self.bubble_until == float("inf") else max(0.0, min(1.0, (self.bubble_until - now)))
            x = min(max(head.x() - width / 2, 4.0), self.width() - width - 4)
            y = max(4.0, head.y() - 0.27 * SIZES[self.size_name] - height)
            rect = QRectF(x, y, width, height)
            path = QPainterPath()
            path.addRoundedRect(rect, 10, 10)
            tail = QPainterPath()
            tx = min(max(head.x(), x + 18), x + width - 18)
            tail.moveTo(tx - 8, rect.bottom() - 1)
            tail.lineTo(tx + 2, rect.bottom() + 12)
            tail.lineTo(tx + 8, rect.bottom() - 1)
            path = path.united(tail)
            p.setOpacity(fade)
            p.setPen(QPen(QColor(0, 0, 0, 40), 1))
            p.setBrush(QColor(255, 255, 255, 240))
            p.drawPath(path)
            p.setPen(QColor("#1f1f26"))
            p.drawText(rect.adjusted(12, 9, -12, -9), Qt.TextFlag.TextWordWrap, shown)
            p.setOpacity(1.0)

    return CompanionWindow


class CompanionOverlay(Overlay):
    """The companion as Red's overlay: `set_state()` from any thread, like GlowOverlay."""

    def __init__(self, sprites: Sprites, *, size: str = "medium", models_dir: Path | None = None,
                 companion: str = "red", state_file: Path | None = None, voice: str | None = None,
                 **window_args):
        self.meter = MouthMeter()
        self.window = _window_class()(sprites, size=size, models_dir=models_dir, companion=companion,
                                      state_file=state_file, meter=self.meter, **window_args)
        self.voice = voice
        self.window.set_clips(self.window._clips_for(companion, voice))
        self.window.show()
        self._closed = False

    @property
    def on_click(self):
        return self.window.on_click

    @on_click.setter
    def on_click(self, callback) -> None:
        self.window.on_click = callback

    def set_state(self, state: str, text: str = "") -> None:
        _check_state(state)
        if self._closed:
            return
        try:
            self.window.state_changed.emit(state, _clean(text))
        except RuntimeError:          # the window is already gone
            pass

    def attach_speaker(self, speaker) -> None:
        """Let the mouth follow Red's voice, and make the "whoa!" clips in this voice if missing."""
        meter_speaker(speaker, self.meter)
        synthesize = kokoro_synthesizer(speaker)
        voice = self.voice or getattr(speaker, "voice_name", None)
        if synthesize is None or self.window.models_dir is None:
            return
        import threading

        def make() -> None:
            for cid in available_companions(self.window.models_dir):
                try:
                    sprites = load_sprites(companion_folder(self.window.models_dir, cid))
                    make_clips(sprites.folder, sprites.voice or voice or "af_heart", synthesize)
                except Exception:  # noqa: BLE001 - sounds are a nicety
                    log.exception("Couldn't make the pickup clips for %s", cid)
        threading.Thread(target=make, name="red-companion-clips", daemon=True).start()

    def close(self) -> None:
        self._closed = True
        try:
            self.window.timer.stop()
            self.window.full_timer.stop()
            self.window._save()
            self.window.close()
        except RuntimeError:
            pass


def companion_overlay(settings) -> CompanionOverlay:
    """Red's companion from its settings. Raises if the companion's pictures aren't there."""
    models_dir = settings.models_dir
    state_file = settings.home / "cache" / "companion.json"
    companion = settings.companion
    if companion is None:
        try:
            companion = json.loads(state_file.read_text(encoding="utf-8")).get("companion")
        except (OSError, ValueError, AttributeError):
            companion = None
    installed = available_companions(models_dir)
    if companion not in installed:
        companion = "red" if "red" in installed else next(iter(installed), "red")
    sprites = load_sprites(companion_folder(models_dir, companion))
    return CompanionOverlay(sprites, size=settings.companion_size, models_dir=models_dir,
                            companion=companion, state_file=state_file, voice=settings.voice)


__all__ = ["CompanionOverlay", "companion_overlay", "fullscreen_app_in_front", "STATES"]
