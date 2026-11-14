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

from . import (FALLBACK, SIDE_OF, SIDES, SIZES, TOP_SIDES, SLEEP_AFTER_SECONDS, Look, MouthMeter, Sprites, available_companions,
               clip_paths, companion_folder, emotion_from_text, frame_for_side, kokoro_synthesizer,
               load_sprites, make_clips, mark_for, meter_speaker, pick_frame, play_clip, side_for)
from .. import events
from . import dialogs, idle
from ..overlay import STATES, Overlay, _check_state, _clean

log = logging.getLogger(__name__)

BUBBLE_SPACE = 190         # logical pixels above the head kept for the bubbles and the marks
BUBBLE_WIDTH = 270
BUBBLE_TEXT = 200          # characters shown in Red's bubble
HEARD_TEXT = 120           # characters shown in the "you:" line
TYPE_SPEED = 38            # characters per second (a reply with no `said` events)
SAID_SPEED = 90            # characters per second for a piece that has just started to be spoken
NEW_REPLY_GAP = 8.0        # a piece this long after the last one starts a new reply
USER_INK = "#6b6f7a"       # grey: what Red heard, against what Red says
BUBBLE_HOLD = 5.0          # seconds the bubble stays after Red goes quiet
DRAG_START = 6             # pixels of movement before a press becomes a pickup
GRAVITY = 3200.0           # pixels per second squared when dropped
HOVER_SECONDS = 1.6
NOTICE_SECONDS = 0.9
GREETING_SECONDS = 1.6
EMOTION_HOLD = 4.0         # an emotion lingers this long after Red stops talking
FAST, NORMAL, SLOW = 33, 100, 500      # timer intervals (ms): animating, awake, asleep
SIDE_PAD = 24
CORNER_SNAP = 180          # dropped this close to a side (or the top) of the screen: it goes there
ANIM_SECONDS = 1.2         # the longest of the little animations below


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
        heard_signal = Signal(str)            # events "heard", "said" and "mic" arrive on Red's voice
        said_signal = Signal(str)             # thread: these queued signals hand them to Qt
        mic_signal = Signal(bool)
        summon_signal = Signal()              # the summon/hide hotkey (pynput's thread -> Qt)
        companion_signal = Signal(str)        # event "companion": switched by a voice command or the app
        idle_signal = Signal(str)             # event "idle_action": look around, yawn, doze, wander...
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
            self.pieces: list[tuple[str, float]] = []   # what Red has said this reply, with when each began
            self.pending_text = ""                       # the reply text of a "speaking" state, not yet voiced
            self.said_this_turn = False
            self.fresh = True                            # the next `said` starts a new reply
            self.pending_shown = False                   # the bubble shows a fallback line, not pieces
            self.reveal_from = 0                         # the characters before this are already shown
            self.type_speed = TYPE_SPEED
            self.heard_text = ""                         # what the user said, shown as "you: ..."
            self.heard_at = 0.0
            self.heard_until = 0.0
            self.muted = False                           # microphone off: a crossed mic on the companion
            self.on_mic: Callable[[bool], None] | None = None     # the host mutes the listener
            self.rng = random.Random()
            self.actions = None                           # MenuActions: reminders, tasks, talk, music
            self.on_settings: Callable[[], None] | None = None
            self.on_quit: Callable[[], None] | None = None
            self.on_quiet: Callable[[bool], None] | None = None
            self.on_switch: Callable[[str], None] | None = None   # switch everywhere (voice, persona)
            self.quiet = False
            self.script: idle.Script | None = None        # an idle frame sequence being played
            self.walk: idle.Walk | None = None            # a hop-walk along the edge
            self.idle_frame: str | None = None
            self.idle_next = clock() + idle.next_gap(self.rng, first=True)
            self.idle_events_until = 0.0                  # idle_action events are arriving: no own timer
            self.idle_switches: dict = {}                 # companion.toml [idle]; missing means on
            self._load_traits()
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
            self.side = "right"                          # edge, left, right (bottom corners) or top
            self.anims: dict[str, float] = {}
            self.load(sprites)
            self._restore()

            self.state_changed.connect(self._apply, Qt.ConnectionType.QueuedConnection)
            self.heard_signal.connect(self._on_heard, Qt.ConnectionType.QueuedConnection)
            self.said_signal.connect(self._on_said, Qt.ConnectionType.QueuedConnection)
            self.mic_signal.connect(self._on_mic, Qt.ConnectionType.QueuedConnection)
            self.idle_signal.connect(self._on_idle_action, Qt.ConnectionType.QueuedConnection)
            self.companion_signal.connect(self._on_companion, Qt.ConnectionType.QueuedConnection)
            self.summon_signal.connect(self.summon, Qt.ConnectionType.QueuedConnection)
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
            for set_name in ("peek", "cornerR", "cornerL", "top", "topL", "topR", "body"):
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
            while prefix not in self.set_size and prefix in FALLBACK:
                prefix = FALLBACK[prefix]
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
            if self.prefix in ("cornerR", "topR"):
                left = area.right() + 1 - width
                self.x_center = area.right() + 1 - w / 2
            elif self.prefix in ("cornerL", "topL"):
                left = area.left()
                self.x_center = area.left() + w / 2
            else:
                if self.side in ("left", "top-left"):         # a corner this model has no frames for
                    self.x_center = area.left() + w / 2
                elif self.side in ("right", "top-right"):
                    self.x_center = area.right() - w / 2
                elif self.x_center is None:
                    self.x_center = area.right() - w / 2 - SIDE_PAD
                self.x_center = min(max(self.x_center, area.left() + w / 2), area.right() - w / 2)
                left = self.x_center - width / 2
            if self.hanging:
                top = area.top()                         # hanging: the picture's top on the top edge
            self.setGeometry(round(left), top, round(width), round(height))

        @property
        def hanging(self) -> bool:
            """Upside down from the top edge: the picture is at the top and the bubble below it."""
            return self.prefix in ("top", "topL", "topR")

        def sprite_top(self, h: float) -> float:
            return 0.0 if self.hanging else self.height() - h

        def sprite_left(self, w: float) -> float:
            """Where the picture starts inside the window: flush with the screen side in a corner."""
            if self.prefix in ("cornerR", "topR"):
                return self.width() - w
            if self.prefix in ("cornerL", "topL"):
                return 0.0
            return (self.width() - w) / 2

        def place(self, side: str) -> None:
            self.side = side if side in SIDES else "edge"
            self.perch()
            self._save()
            self.until["notice"] = self.clock() + NOTICE_SECONDS
            self.animate("land")

        # --- little animations ------------------------------------------------
        # pop: picked up (a springy stretch); land: a squash when it settles; hop: a hop toward you on
        # hover, with a heart floating off; jolt: a startled shake when woken.

        def animate(self, name: str) -> None:
            self.anims[name] = self.clock()

        def anim_age(self, name: str, now: float, length: float) -> float | None:
            start = self.anims.get(name)
            if start is None or now - start > length:
                return None
            return now - start

        def animating(self, now: float) -> bool:
            return any(now - start < ANIM_SECONDS for start in self.anims.values())

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
                path = Path(self.state_file)
                path.parent.mkdir(parents=True, exist_ok=True)
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    data = data if isinstance(data, dict) else {}
                except (OSError, ValueError):
                    data = {}
                data.update({"x": self.x_center, "side": self.side, "companion": self.companion,
                             "size": self.size_name})
                path.write_text(json.dumps(data), encoding="utf-8")
            except OSError:
                log.debug("Couldn't save the companion's spot", exc_info=True)

        # --- states from Red ---------------------------------------------------

        def _apply(self, state: str, text: str) -> None:
            now = self.clock()
            previous = self.look.state
            if state != "idle":
                self.last_activity = now
                self.cancel_idle()
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
                # The words appear with the voice (the `said` events), never before it. This state comes
                # before the audio starts, so the text only waits here as a fallback for a speaker that
                # sends no `said`: tick() shows it once the voice is really sounding.
                if not self.said_this_turn:
                    self.pending_text = self._first_line(text)
            elif state in ("error", "confirm") and text:
                self._bubble(text, now)
            elif state in ("listening", "thinking"):
                if state == "listening":
                    self.turn_emotion = None
                    self.heard_until = now           # the user talks again: their last line goes too
                self._next_reply()
                self.bubble_until = now          # the last reply goes once you talk again
            if state == "idle":
                self.bubble_until = now + BUBBLE_HOLD
                if self.heard_until == float("inf"):
                    self.heard_until = now + BUBBLE_HOLD
                if self.turn_emotion:
                    self.until["emotion"] = now + EMOTION_HOLD
            self.look.state = state
            self.look.since = now
            self._speed(FAST)
            self.tick()

        @staticmethod
        def _first_line(text: str) -> str:
            first = (text or "").strip().splitlines()[0] if (text or "").strip() else ""
            if len(first) > BUBBLE_TEXT:
                first = first[:BUBBLE_TEXT - 1].rstrip() + "…"
            return first

        def _bubble(self, text: str, now: float) -> None:
            """Show a whole line at once (a question or a problem, and the fallback for a reply)."""
            first = self._first_line(text)
            if first != self.bubble_text:
                self.bubble_text = first
                self.bubble_started = now
                self.reveal_from = 0
                self.type_speed = TYPE_SPEED
            self.pieces = []
            self.bubble_until = float("inf")

        def _next_reply(self) -> None:
            """What comes next is a new reply: the pieces so far are old."""
            self.fresh = True
            self.said_this_turn = False
            self.pending_text = ""

        # --- the user's words, Red's words, the microphone ----------------------
        # Handlers of red.events run on Red's voice thread: the overlay turns them into these queued
        # signals, so the slots below run on the Qt thread.

        def _on_heard(self, text: str) -> None:
            """The transcript is final: show it at once, grey and italic ("you: ...")."""
            now = self.clock()
            text = " ".join((text or "").split())
            if not text:
                return
            if len(text) > HEARD_TEXT:
                text = text[:HEARD_TEXT - 1].rstrip() + "…"
            self.heard_text, self.heard_at, self.heard_until = text, now, float("inf")
            self.bubble_text, self.pieces, self.bubble_until = "", [], now
            self._next_reply()
            self.last_activity = now
            if not self.isVisible() and not self.hidden_for_fullscreen:
                self.show()
            self._speed(FAST)
            self.tick()

        def _on_said(self, text: str) -> None:
            """One piece of Red's reply, right after its audio started: reveal it now."""
            now = self.clock()
            text = " ".join((text or "").split())
            if not text:
                return
            gap = now - (self.pieces[-1][1] if self.pieces else now)
            if self.fresh or self.pending_shown or gap > NEW_REPLY_GAP:
                self.pieces = []
            self.fresh = self.pending_shown = False
            self.said_this_turn = True
            self.pending_text = ""
            self.pieces.append((text, now))
            while len(self.pieces) > 1 and sum(len(t) + 1 for t, _ in self.pieces) > BUBBLE_TEXT:
                self.pieces.pop(0)                   # the oldest pieces make room
            before = " ".join(t for t, _ in self.pieces[:-1])
            joined = " ".join(t for t, _ in self.pieces)
            if len(joined) > BUBBLE_TEXT:
                joined = "…" + joined[-(BUBBLE_TEXT - 1):]
                before = joined[: max(0, len(joined) - len(self.pieces[-1][0]))]
            self.bubble_text = joined
            self.reveal_from = len(before) + (1 if before else 0)
            self.bubble_started = now
            self.type_speed = SAID_SPEED
            self.bubble_until = float("inf")
            self.last_activity = now
            if not self.isVisible() and not self.hidden_for_fullscreen:
                self.show()
            self._speed(FAST)
            self.tick()

        def _on_mic(self, muted: bool) -> None:
            self.muted = bool(muted)
            self.update()

        def toggle_mic(self) -> None:
            """Microphone off or on from the menu: the host mutes the listener, then the badge shows."""
            muted = not self.muted
            if self.on_mic is None:
                log.warning("No microphone control is connected, so the microphone stays as it is")
                return
            try:
                self.on_mic(muted)
            except Exception:  # noqa: BLE001 - the menu must survive a listener that can't mute
                log.exception("Couldn't turn the microphone %s", "off" if muted else "on")
                return
            self.muted = muted
            self.update()

        # --- idle life ----------------------------------------------------------
        # Left alone, it looks around, yawns, stretches, gets bored, dozes off, hop-walks along the edge
        # and now and then goes to another corner. Lane 2's `idle_action` events say when; until they
        # arrive (idle_events_until), a timer of its own does (red/avatar/idle.py has the choices).

        def _load_traits(self) -> None:
            try:
                from .. import companions
                self.idle_switches = dict(companions.load(self.companion).idle)
            except Exception:  # noqa: BLE001 - no pack for this look: everything is allowed
                self.idle_switches = {}

        def allows(self, action: str) -> bool:
            return bool(self.idle_switches.get(idle.SWITCH.get(action, action), True))

        def _calm(self, now: float) -> bool:
            """Nothing is going on that an idle action would get in the way of."""
            look = self.look
            return (look.state == "idle" and not look.dragging and not look.falling and self.isVisible()
                    and not self.until and not (self.bubble_text and now < self.bubble_until)
                    and not (self.heard_text and now < self.heard_until))

        def cancel_idle(self) -> None:
            self.script = None
            self.idle_frame = None
            if self.walk is not None:
                self.walk = None
                self._save()

        def _on_idle_action(self, name: str) -> None:
            now = self.clock()
            self.idle_events_until = now + 900.0          # someone else is choosing: wait for them
            self.start_idle(name)

        def start_idle(self, name: str) -> bool:
            """Begin an idle action by name. False if it isn't allowed or now is not a calm moment."""
            now = self.clock()
            name = idle.EVENT_ALIASES.get(name, name)
            if self.quiet or name not in idle.SWITCH or not self.allows(name) or not self._calm(now):
                return False
            if self.script is not None or self.walk is not None:
                return False
            if name == "wander" and self.prefix not in ("peek", "top"):
                name = "corner"                           # in a corner it can't walk: it moves instead
            if name == "wander":
                area = self._area_for(self.x_center or 0)
                target = idle.walk_target(self.x_center, area.left(), area.right(), self.perch_size[0] / 2,
                                          self.rng)
                if target is None:
                    return False
                self.walk = idle.Walk(self.x_center, target, now)
            elif name == "corner":
                places = [s for s in SIDES if s != self.side and SIDES[s] in self.set_size]
                if not places:
                    return False
                self.place(self.rng.choice(places))
            elif name == "hum":
                self.turn_emotion = "happy"
                self.until["emotion"] = now + 3.5
            else:
                self.script = idle.script_for(name, now)
                if self.script is None:
                    return False
            self.idle_next = now + idle.next_gap(self.rng)
            self._speed(FAST if self.walk is not None else NORMAL)
            return True

        def _idle_life(self, now: float) -> None:
            if not self._calm(now):
                if self.script is not None or self.walk is not None:
                    self.cancel_idle()
                self.idle_frame = None
                return
            if self.walk is not None:
                self.x_center = self.walk.x_at(now)
                self.perch()
                self.idle_frame = self.walk.direction
                if self.walk.done(now):
                    self.walk = None
                    self.idle_frame = None
                    self._save()
                    self.animate("land")
            elif self.script is not None:
                finished, frame = self.script.at(now)
                self.idle_frame = frame
                if finished:
                    then, self.script, self.idle_frame = self.script.then, None, None
                    if then == "sleep":
                        self.look.state = "sleeping"
                        self.look.since = now
            else:
                self.idle_frame = None
                if now >= self.idle_next and now >= self.idle_events_until:
                    name = idle.choose(now - self.last_activity, self.rng, self.allows, self.side)
                    self.idle_next = now + idle.next_gap(self.rng)
                    if name:
                        self.start_idle(name)

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
            if (self.pending_text and not self.said_this_turn and look.state == "speaking"
                    and self.meter.playing()):
                self._bubble(self.pending_text, now)     # no `said` came, but the voice is sounding
                self.pending_shown, self.pending_text = True, ""
            look.emotion = "happy" if "hover" in self.until else self.turn_emotion

            if look.falling:
                self._fall(now)                          # may land, so before the frame is picked
            self._idle_life(now)
            look.action = self.idle_frame
            shown = Look(**vars(look))
            if "greeting" in self.until:
                shown.state, shown.since = "greeting", self.until["greeting"] - GREETING_SECONDS
            elif "notice" in self.until and look.state in ("listening", "idle", "sleeping"):
                shown.state = "notice"
            self.frame_name = frame_for_side(pick_frame(shown, now, self.has), SIDE_OF[self.prefix], self.has)
            self.shown = shown

            busy = (look.dragging or look.falling or look.state in ("speaking", "greeting") or self.until
                    or self._typing(now) or self.animating(now) or self.walk is not None)
            self._speed(FAST if busy else SLOW if look.state == "sleeping" else NORMAL)
            self.update()

        def _typed(self, now: float) -> int:
            """How many characters of the bubble are shown: the old pieces, then the new one typing in."""
            return self.reveal_from + int(max(0.0, now - self.bubble_started) * self.type_speed)

        def _typing(self, now: float) -> bool:
            return bool(self.bubble_text) and self._typed(now) < len(self.bubble_text)

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
                self.side = side_for(pos.x(), area.left(), area.right(), CORNER_SNAP, pos.y(), area.top())
                self._sound(self.drop_clips)
                self._speed(FAST)
                if self.side in TOP_SIDES:               # it grabs the top edge or corner: no falling
                    self.look.falling = False
                    self.x_center = pos.x()
                    self.until["notice"] = self.clock() + NOTICE_SECONDS
                    self.perch()
                    self._save()
                    self.animate("land")
                return
            if pressed is not None and self.on_click:
                try:
                    self.on_click()
                except Exception:  # noqa: BLE001 - the window must survive a broken callback
                    log.exception("Companion click failed")

        def _pick_up(self, pos: QPointF) -> None:
            self.cancel_idle()
            self.look.dragging = True
            self.last_activity = self.clock()
            self.until.pop("hover", None)
            if self.look.state == "sleeping":
                self.look.state = "idle"
            self.turn_emotion = "happy" if random.random() < 0.25 else None      # sometimes it enjoys it
            self.last_drag = (QPointF(pos), self.clock())
            self.swing = 0.0
            self.animate("pop")
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
                self.animate("land")
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
            self.cancel_idle()
            if self.look.state == "sleeping":
                self.look.state = "idle"
                self.until["notice"] = now + NOTICE_SECONDS
                self.animate("jolt")
            elif self.look.state == "idle":
                self.until["hover"] = now + HOVER_SECONDS
                if self.anim_age("hop", now, 1.5) is None:      # not again while it's still hopping
                    self.animate("hop")
            self.last_activity = now
            self.tick()

        def contextMenuEvent(self, event):  # noqa: N802
            self.build_menu().exec(event.globalPos())

        def build_menu(self):
            """The right-click menu, like Desktop Mate's: talk, reminders and tasks, music, where it sits,
            who it is, how big, asleep or quiet, the microphone, settings, hide and quit."""
            menu = QMenu()
            have = self.actions is not None
            menu.addAction("Talk", self.talk).setEnabled(have and self.actions.can_talk)
            if self.on_click:
                menu.addAction("Open chat", self.on_click)
            menu.addSeparator()
            menu.addAction("Set a reminder…", self.open_reminder).setEnabled(have)
            menu.addAction("Add a task…", self.open_task).setEnabled(have)
            menu.addAction("To-do list…", self.open_todo).setEnabled(have)
            menu.addAction("Play music", self.play_music).setEnabled(have and self.actions.can_play_music)
            menu.addSeparator()
            move = menu.addMenu("Move")
            for side, label in (("left", "Bottom-left corner"), ("edge", "Bottom edge"),
                                ("right", "Bottom-right corner"), ("top", "Top edge (hanging)"),
                                ("top-left", "Top-left corner (hanging)"),
                                ("top-right", "Top-right corner (hanging)")):
                action = move.addAction(label, functools.partial(self.place, side))
                action.setCheckable(True)
                action.setChecked(side == self.side)
                action.setEnabled(SIDES[side] in self.set_size)
            if self.models_dir is not None:
                switch = menu.addMenu("Switch companion")
                for cid, name in available_companions(self.models_dir).items():
                    action = switch.addAction(name, functools.partial(self.choose_companion, cid))
                    action.setCheckable(True)
                    action.setChecked(cid == self.companion)
            size = menu.addMenu("Size")
            for name in SIZES:
                action = size.addAction(name.capitalize(), functools.partial(self.set_size_name, name))
                action.setCheckable(True)
                action.setChecked(name == self.size_name)
            menu.addSeparator()
            asleep = self.look.state == "sleeping"
            menu.addAction("Wake up" if asleep else "Sleep", self.wake if asleep else self.sleep_now)
            quiet = menu.addAction("Quiet mode", self.toggle_quiet)
            quiet.setCheckable(True)
            quiet.setChecked(self.quiet)
            menu.addAction("Microphone on" if self.muted else "Microphone off", self.toggle_mic)
            menu.addSeparator()
            menu.addAction("Settings…", self.open_settings).setEnabled(self.on_settings is not None)
            menu.addAction("Hide", self.hide)
            menu.addAction("Quit Red", self.quit_red)
            return menu

        # --- what the menu does ---------------------------------------------------

        def show_note(self, text: str, seconds: float = 4.5) -> None:
            """A short line from the companion itself (not spoken): shown, then it fades."""
            now = self.clock()
            self.pieces = []
            self.bubble_text = self._first_line(text)
            self.bubble_started, self.reveal_from, self.type_speed = now, 0, TYPE_SPEED
            self.bubble_until = now + seconds
            self.last_activity = now
            self._speed(FAST)
            self.tick()

        def talk(self) -> None:
            if self.actions is not None:
                self.actions.talk()

        def play_music(self) -> None:
            line = self.actions.play_music() if self.actions is not None else None
            if line:
                self.show_note(line)

        def _open_dialog(self, dialog) -> None:
            self.dialogs = [d for d in getattr(self, "dialogs", []) if d.isVisible()]
            self.dialogs.append(dialog)
            dialog.on_done = self._dialog_done(dialog.on_done)
            dialog.show_near(self.geometry(), self._area_for(self.x_center or 0))

        def _dialog_done(self, inner):
            def done(text: str) -> None:
                self.show_note(text)
                if inner is not None:
                    inner(text)
            return done

        def open_reminder(self) -> None:
            if self.actions is not None:
                self._open_dialog(dialogs.reminder_dialog(self.actions))

        def open_task(self) -> None:
            if self.actions is not None:
                self._open_dialog(dialogs.task_dialog(self.actions))

        def open_todo(self) -> None:
            if self.actions is not None:
                self._open_dialog(dialogs.todo_dialog(self.actions))

        def choose_companion(self, companion: str) -> None:
            """From the menu: the host switches the companion everywhere (voice, persona, look); on its
            own, only the look changes."""
            if companion == self.companion:
                return
            if self.on_switch is not None:
                try:
                    self.on_switch(companion)
                    return
                except Exception:  # noqa: BLE001 - fall back to changing only the look
                    log.exception("Couldn't switch the companion everywhere")
            self.switch(companion)

        def _on_companion(self, companion: str) -> None:
            """The companion event (a voice command or the app): follow it."""
            if (companion and companion != self.companion and self.models_dir is not None
                    and companion in available_companions(self.models_dir)):
                self.switch(companion)

        def set_size_name(self, name: str) -> None:
            if name not in SIZES or name == self.size_name:
                return
            self.size_name = name
            self.load(self.sprites)
            self.perch()
            self._save()
            self.animate("land")
            self.tick()

        def sleep_now(self) -> None:
            self.cancel_idle()
            self.look.state = "sleeping"
            self.look.since = self.clock()
            self.bubble_until = 0
            self.tick()

        def wake(self) -> None:
            now = self.clock()
            self.look.state = "idle"
            self.last_activity = now
            self.until["notice"] = now + NOTICE_SECONDS
            self.animate("jolt")
            self.tick()

        def toggle_quiet(self) -> None:
            """Quiet mode: no idle actions and no unasked words (the host stops its idle life)."""
            self.quiet = not self.quiet
            self.cancel_idle()
            if self.on_quiet is not None:
                try:
                    self.on_quiet(self.quiet)
                except Exception:  # noqa: BLE001
                    log.exception("Couldn't switch quiet mode")

        def summon(self) -> None:
            """The summon/hide hotkey: hidden, it appears and waves; showing, it goes away."""
            now = self.clock()
            if self.isVisible() and not self.hidden_for_fullscreen:
                self.cancel_idle()
                self.hide()
                return
            if self.check_fullscreen():
                return                                   # a game or a video: not now
            self.hidden_for_fullscreen = False
            self.look.state = "idle"
            self.look.since = now
            self.last_activity = now
            self.until["greeting"] = now + GREETING_SECONDS
            self.show()
            self.perch()
            self.animate("land")
            self._speed(FAST)
            self.tick()

        def open_settings(self) -> None:
            if self.on_settings is not None:
                self.on_settings()

        def quit_red(self) -> None:
            if self.on_quit is not None:
                self.on_quit()
            else:
                QGuiApplication.instance().quit()

        def switch(self, companion: str) -> None:
            try:
                sprites = load_sprites(companion_folder(self.models_dir, companion))
            except (OSError, ValueError, KeyError) as e:
                log.warning("Couldn't switch to %s: %s", companion, e)
                return
            self.companion = companion
            self.cancel_idle()
            self._load_traits()
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
            unit = SIZES[self.size_name] / 300.0
            inward = 1.0 if self.hanging else -1.0       # toward the middle of the screen
            left = self.sprite_left(w)
            top = self.sprite_top(h)
            asleep = self.look.state == "sleeping"
            breath = (0.014 if asleep else 0.007) * math.sin(now * 2 * math.pi / (5.0 if asleep else 3.6))
            sx, sy, dx, dy = 1.0, 1.0 + breath, 0.0, 0.0
            age = self.anim_age("land", now, 0.6)
            if age is not None:                          # squash on the edge, then spring back
                squash = 0.14 * math.exp(-age * 9) * math.cos(age * 22)
                sx, sy = sx * (1 + squash * 0.6), sy * (1 - squash)
            age = self.anim_age("hop", now, 0.38)
            if age is not None:                          # a little hop toward you
                dy += inward * 12 * unit * math.sin(math.pi * age / 0.38)
                sy *= 1 + 0.04 * math.sin(math.pi * age / 0.38)
            age = self.anim_age("jolt", now, 0.5)
            if age is not None:                          # startled awake
                dx += 5 * unit * math.sin(age * 70) * math.exp(-age * 7)
            if self.walk is not None:                    # hop-walking along the edge
                dy += inward * idle.HOP_HEIGHT * unit * self.walk.hop_at(now)
            edge_y = 0.0 if self.hanging else self.height()   # it stretches and squashes from the edge
            p.save()
            p.translate(left + w / 2 + dx, edge_y + dy)
            p.scale(sx, sy)
            p.drawPixmap(QPointF(-w / 2, 0.0 if self.hanging else -h), pm)
            p.restore()
            head = self.mark_point(self.frame_name) + QPointF(left + dx, top + dy)
            mark = mark_for(self.shown) if hasattr(self, "shown") else None
            if mark:
                self._paint_mark(p, mark, head, now)
            age = self.anim_age("hop", now, 1.1)
            if age is not None:
                self._paint_heart(p, head, age, unit)
            self._paint_bubbles(p, head, now)
            if self.muted:
                self._paint_mic_badge(p, QRectF(left + dx, top + dy, w, h), unit)
            p.end()

        def _paint_heart(self, p, head: QPointF, age: float, unit: float) -> None:
            """A small heart that floats off the head and fades (on hover)."""
            t = age / 1.1
            away = -1.0 if not self.hanging else 1.0
            x = head.x() - 30 * unit + 8 * unit * math.sin(t * 6)
            y = head.y() + away * (60 + 45 * t) * unit
            font = QFont("Segoe UI Symbol", max(8, round((14 + 6 * t) * unit)))
            p.setFont(font)
            p.setPen(QColor(230, 80, 130, int(255 * (1 - t))))
            p.drawText(QPointF(x, y), "♥")

        def _paint_dangling(self, p, pm, w, h, now) -> None:
            # A pendulum: the body leans against the way you move it, then settles.
            target = -self.swing_speed / 2500.0 * 28.0
            self.swing += (target - self.swing) * 0.25
            self.swing_speed *= 0.85
            wobble = 3.0 * math.sin(now * 7.0) if self.look.dragging else 0.0
            p.translate(self.hold)
            p.rotate(self.swing + wobble)
            age = self.anim_age("pop", now, 0.8)
            if age is not None:                          # picked up: a springy stretch from your hand
                stretch = 0.16 * math.exp(-age * 7) * math.cos(age * 18)
                p.scale(1 - stretch * 0.5, 1 + stretch)
            p.drawPixmap(QPointF(-self.grab_offset.x(), -self.grab_offset.y()), pm)
            age = self.anim_age("pop", now, 0.5)
            if age is not None:                          # surprise lines around the head
                unit = SIZES[self.size_name] / 300.0
                head = self.mark_point("body_drag_1") - self.grab_offset
                p.setPen(QPen(QColor(40, 40, 50, int(230 * (1 - age / 0.5))), 2.5 * unit))
                for angle in (-150, -115, -65, -30):
                    a = math.radians(angle)
                    r1, r2 = (55 + 30 * age) * unit, (75 + 40 * age) * unit
                    p.drawLine(QPointF(head.x() + r1 * math.cos(a), head.y() + r1 * math.sin(a)),
                               QPointF(head.x() + r2 * math.cos(a), head.y() + r2 * math.sin(a)))

        def _paint_mark(self, p, mark: str, head: QPointF, now: float) -> None:
            unit = SIZES[self.size_name] / 300.0
            # Upside down the head's top points at the floor, so the marks go below it.
            down = -1.0 if self.hanging else 1.0
            past_hair = 92 if self.hanging else 70      # hanging hair falls past the head
            top = QPointF(head.x() + down * 34 * unit, head.y() - down * past_hair * unit)
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
                x = head.x() + down * (11 if mark == "tear" else 27) * unit
                y = head.y() - down * (19 if mark == "tear" else 44) * unit + fall
                path = QPainterPath()
                path.moveTo(x, y - 9 * unit)
                path.cubicTo(x + 7 * unit, y, x + 5 * unit, y + 7 * unit, x, y + 7 * unit)
                path.cubicTo(x - 5 * unit, y + 7 * unit, x - 7 * unit, y, x, y - 9 * unit)
                p.setPen(QPen(QColor(60, 120, 200), 1.2))
                p.setBrush(QColor(140, 195, 250, 220))
                p.drawPath(path)

        def _paint_bubbles(self, p, head: QPointF, now: float) -> None:
            """Red's words nearest the head, and above them (below, hanging) what the user said."""
            reach = 0.27 * SIZES[self.size_name]          # how far from the head the first bubble starts
            if self.bubble_text and now < self.bubble_until:
                shown = self.bubble_text[: max(0, self._typed(now))]
                if shown:
                    reach += self._paint_bubble(p, head, now, shown, reach) + 8
            if self.heard_text and now < self.heard_until:
                self._paint_heard(p, head, now, reach)

        def _paint_heard(self, p, head: QPointF, now: float, reach: float) -> None:
            """"you: ..." in grey italic, in a small quiet bubble: what Red heard, not what Red says."""
            font = QFont("Segoe UI", 9)
            font.setItalic(True)
            p.setFont(font)
            line = f"you: {self.heard_text}"
            inner = BUBBLE_WIDTH - 40
            full = QFontMetricsF(font).boundingRect(QRectF(0, 0, inner, 1000), Qt.TextFlag.TextWordWrap, line)
            height = min(full.height(), 2 * QFontMetricsF(font).lineSpacing() + 1) + 12
            width = min(inner, max(40.0, full.width())) + 22
            fade = 1.0 if self.heard_until == float("inf") else max(0.0, min(1.0, self.heard_until - now))
            fade = min(fade, min(1.0, (now - self.heard_at) * 6))        # and it fades in
            x = min(max(head.x() - width / 2, 4.0), self.width() - width - 4)
            if self.hanging:
                y = min(self.height() - height - 4.0, head.y() + reach)
            else:
                y = max(4.0, head.y() - reach - height)
            rect = QRectF(x, y, width, height)
            path = QPainterPath()
            path.addRoundedRect(rect, 9, 9)
            p.setOpacity(fade)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(236, 238, 242, 215))
            p.drawPath(path)
            p.setPen(QColor(USER_INK))
            p.drawText(rect.adjusted(11, 6, -11, -6), Qt.TextFlag.TextWordWrap, line)
            p.setOpacity(1.0)

        def _paint_mic_badge(self, p, sprite: QRectF, unit: float) -> None:
            """A small crossed-out microphone on the outer top corner of the picture: the mic is off."""
            r = max(10.0, 15 * unit)
            toward_left = self.prefix not in ("cornerL", "topL")     # away from the screen's side
            c = QPointF(sprite.left() + r + 6 if toward_left else sprite.right() - r - 6,
                        sprite.bottom() - r - 6 if self.hanging else sprite.top() + r + 6)
            p.save()
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(38, 40, 48, 225))
            p.drawEllipse(c, r, r)
            ink = QPen(QColor(245, 245, 248), max(1.3, r * 0.13))
            ink.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(ink)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(QRectF(c.x() - r * 0.2, c.y() - r * 0.58, r * 0.4, r * 0.7), r * 0.2, r * 0.2)
            p.drawArc(QRectF(c.x() - r * 0.40, c.y() - r * 0.38, r * 0.8, r * 0.68), 180 * 16, 180 * 16)
            p.drawLine(QPointF(c.x(), c.y() + r * 0.3), QPointF(c.x(), c.y() + r * 0.55))
            p.setPen(QPen(QColor("#e5484d"), max(1.8, r * 0.17), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawLine(QPointF(c.x() - r * 0.62, c.y() - r * 0.62), QPointF(c.x() + r * 0.62, c.y() + r * 0.62))
            p.restore()

        def _paint_bubble(self, p, head: QPointF, now: float, shown: str, reach: float) -> float:
            """Red's speech bubble, `reach` away from the head. Returns its height."""
            font = QFont("Segoe UI", 10)
            p.setFont(font)
            metrics = QFontMetricsF(font)
            inner = BUBBLE_WIDTH - 24
            full = metrics.boundingRect(QRectF(0, 0, inner, 1000), Qt.TextFlag.TextWordWrap, self.bubble_text)
            height = min(full.height(), BUBBLE_SPACE - 60) + 18
            width = min(inner, max(60.0, full.width())) + 24
            fade = 1.0 if self.bubble_until == float("inf") else max(0.0, min(1.0, (self.bubble_until - now)))
            x = min(max(head.x() - width / 2, 4.0), self.width() - width - 4)
            if self.hanging:                             # below the (upside-down) head
                y = min(self.height() - height - 4.0, head.y() + reach)
            else:
                y = max(4.0, head.y() - reach - height)
            rect = QRectF(x, y, width, height)
            path = QPainterPath()
            path.addRoundedRect(rect, 10, 10)
            tail = QPainterPath()
            tx = min(max(head.x(), x + 18), x + width - 18)
            if self.hanging:
                tail.moveTo(tx - 8, rect.top() + 1)
                tail.lineTo(tx + 2, rect.top() - 12)
                tail.lineTo(tx + 8, rect.top() + 1)
            else:
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
            return height

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
        # red.events handlers run on Red's voice thread: each one only emits a queued Qt signal.
        self._unsubscribe = [events.on("heard", self._heard), events.on("said", self._said),
                             events.on("mic", self._mic),
                             events.on("idle_action", self._idle_action),
                             events.on("companion", self._companion)]

    def _heard(self, text: str = "", **_) -> None:
        self._emit(self.window.heard_signal, str(text))

    def _said(self, text: str = "", **_) -> None:
        self._emit(self.window.said_signal, str(text))

    def _companion(self, id: str = "", **_) -> None:  # noqa: A002 - the event's payload key
        self._emit(self.window.companion_signal, str(id))

    def _idle_action(self, name: str = "", **_) -> None:
        self._emit(self.window.idle_signal, str(name))

    def _mic(self, muted: bool = False, **_) -> None:
        self._emit(self.window.mic_signal, bool(muted))

    def _emit(self, signal, value) -> None:
        if self._closed:
            return
        try:
            signal.emit(value)
        except RuntimeError:          # the window is already gone
            pass

    @property
    def on_mic(self):
        return self.window.on_mic

    @on_mic.setter
    def on_mic(self, callback) -> None:
        self.window.on_mic = callback

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
        hotkey = getattr(self, "summon_hotkey", None)
        if hotkey is not None:
            try:
                hotkey.stop()
            except Exception:  # noqa: BLE001
                pass
        for undo in self._unsubscribe:
            undo()
        self._unsubscribe = []
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
    size = settings.companion_size
    try:
        saved = json.loads(state_file.read_text(encoding="utf-8"))
        if companion is None:
            companion = saved.get("companion")
        if saved.get("size") in SIZES:
            size = saved["size"]                  # what the menu or the app last picked wins
    except (OSError, ValueError, AttributeError):
        pass
    installed = available_companions(models_dir)
    if companion not in installed:
        companion = "red" if "red" in installed else next(iter(installed), "red")
    sprites = load_sprites(companion_folder(models_dir, companion))
    return CompanionOverlay(sprites, size=size, models_dir=models_dir,
                            companion=companion, state_file=state_file, voice=settings.voice)


__all__ = ["CompanionOverlay", "companion_overlay", "fullscreen_app_in_front", "STATES"]
