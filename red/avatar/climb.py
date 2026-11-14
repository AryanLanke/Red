"""The screen's edges as a climbing frame: the part of the companion's movement that needs no screen.

The four edges make one loop, walked clockwise as seen on the screen: along the bottom to the right, up
the right side, along the top to the left, down the left side. A `Spot` is a place on that loop (an edge
and the character's middle along it). `plan()` makes a `Route` from one spot to another, the short way
round unless the mouse cursor is on it; the window plays the route: a hop-walk along the bottom (peek
frames), hand over hand up or down a side (climbR/climbL frames), and across the top on the bars
(bars_moveR/bars_moveL), with a short pause at each corner.

An `Arc` is a jump (onto an app window's top edge, or off it) and a `Flight` is a fling: thrown, it flies
under gravity until it reaches an edge and grabs it. `Shake` tells a shake (fast back and forth) from a
drag. Everything takes a clock value, so tests run with a fake clock.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

EDGES = ("bottom", "right", "top", "left")          # clockwise as seen on the screen
# Which way the coordinate runs, going clockwise: x grows along the bottom, y shrinks up the right side,
# x shrinks along the top, y grows down the left side.
CW_SIGN = {"bottom": 1, "right": -1, "top": -1, "left": 1}
SPEED = {"bottom": 150.0, "right": 95.0, "left": 95.0, "top": 120.0}       # pixels a second, unit 1
CORNER_PAUSE = 0.4                                  # seconds at a corner: a breath, a new grip
STRIDE = {"right": 46.0, "left": 46.0, "top": 52.0}      # pixels of movement per frame of a climb cycle
CURSOR_CLEAR = 170.0                                # a route never passes this close to the mouse cursor
MOVING_SET = {"bottom": "peek", "right": "climbR", "left": "climbL", "top": "bars"}

# The placement a spot on an edge settles into, and back.
EDGE_OF = {"edge": "bottom", "left": "bottom", "right": "bottom", "top": "top", "top-left": "top",
           "top-right": "top", "side-left": "left", "side-right": "right"}


@dataclass(frozen=True)
class Area:
    left: float
    top: float
    right: float
    bottom: float

    @property
    def width(self) -> float:
        return self.right - self.left

    @property
    def height(self) -> float:
        return self.bottom - self.top


@dataclass(frozen=True)
class Spot:
    edge: str            # bottom, right, top or left
    at: float            # x along the bottom and top, y along the sides: the character's middle


Limits = dict[str, tuple[float, float]]      # edge -> (lowest, highest) coordinate of the middle


def limits(area: Area, half: dict[str, float]) -> Limits:
    """Where the middle can be on each edge, keeping `half[edge]` (half the picture along it) on screen."""
    out = {}
    for edge in EDGES:
        lo, hi = (area.left, area.right) if edge in ("bottom", "top") else (area.top, area.bottom)
        h = half.get(edge, 0.0)
        out[edge] = (lo + h, max(lo + h, hi - h))
    return out


def clamp_spot(spot: Spot, lims: Limits) -> Spot:
    lo, hi = lims[spot.edge]
    return Spot(spot.edge, min(max(spot.at, lo), hi))


def point(spot: Spot, area: Area, inset: float = 60.0) -> tuple[float, float]:
    """Roughly where the character's middle is on the screen (for the cursor check)."""
    if spot.edge == "bottom":
        return spot.at, area.bottom - inset
    if spot.edge == "top":
        return spot.at, area.top + inset
    if spot.edge == "right":
        return area.right - inset, spot.at
    return area.left + inset, spot.at


def _ends(edge: str, lims: Limits, clockwise: bool) -> tuple[float, float]:
    """(entry, exit) coordinate of an edge, walked clockwise or not."""
    lo, hi = lims[edge]
    first, last = (lo, hi) if CW_SIGN[edge] > 0 else (hi, lo)
    return (first, last) if clockwise else (last, first)


def _ahead(edge: str, a: float, b: float, clockwise: bool) -> bool:
    sign = CW_SIGN[edge] * (1 if clockwise else -1)
    return (b - a) * sign >= 0


@dataclass
class Leg:
    edge: str
    a: float
    b: float
    start: float          # seconds after the route started
    seconds: float

    @property
    def length(self) -> float:
        return abs(self.b - self.a)

    def coord(self, t: float) -> float:
        p = min(1.0, max(0.0, (t - self.start) / self.seconds)) if self.seconds > 0 else 1.0
        eased = p * p * (3 - 2 * p)                 # it gets going and slows down at each end
        return self.a + (self.b - self.a) * eased

    def travelled(self, t: float) -> float:
        return abs(self.coord(t) - self.a)


@dataclass
class Route:
    legs: list[Leg]
    started: float
    end: Spot
    then: str             # the placement it settles into at the end
    clockwise: bool = True
    unit: float = 1.0

    @property
    def seconds(self) -> float:
        last = self.legs[-1]
        return last.start + last.seconds

    def done(self, now: float) -> bool:
        return now - self.started >= self.seconds

    def at(self, now: float) -> tuple[Leg, float, bool]:
        """(the leg it is on, where it is along that edge, moving or pausing at a corner)."""
        t = now - self.started
        for i, leg in enumerate(self.legs):
            if t < leg.start:                         # the pause before this leg: still at the last corner
                prev = self.legs[i - 1]
                return prev, prev.b, False
            if t <= leg.start + leg.seconds:
                return leg, leg.coord(t), True
        last = self.legs[-1]
        return last, last.b, False

    def frame(self, now: float) -> tuple[str, str | None]:
        """(frame set, frame name or None for the walk's own look): what the moving character shows."""
        leg, _, moving = self.at(now)
        t = now - self.started
        if leg.edge == "bottom":
            return "peek", ("look_right" if leg.b > leg.a else "look_left")
        if leg.edge in ("right", "left"):
            n = int(leg.travelled(t) / (STRIDE[leg.edge] * self.unit)) % 4
            up = leg.b < leg.a
            step = n if up else 3 - n                 # down: the climb played backwards
            return MOVING_SET[leg.edge], f"{MOVING_SET[leg.edge]}_{step + 1}"
        if not moving:
            return "bars", "bars_idle"
        n = int(leg.travelled(t) / (STRIDE["top"] * self.unit)) % 4
        return "bars", f"bars_move{'R' if leg.b > leg.a else 'L'}_{n + 1}"


def _legs(start: Spot, end: Spot, lims: Limits, clockwise: bool) -> list[tuple[str, float, float]]:
    out = []
    edge, a = start.edge, start.at
    for _ in range(5):
        if edge == end.edge and _ahead(edge, a, end.at, clockwise):
            out.append((edge, a, end.at))
            return out
        out.append((edge, a, _ends(edge, lims, clockwise)[1]))
        i = EDGES.index(edge)
        edge = EDGES[(i + (1 if clockwise else -1)) % 4]
        a = _ends(edge, lims, clockwise)[0]
    out.append((edge, a, end.at))
    return out


def _near_cursor(legs, area: Area, cursor) -> bool:
    if cursor is None:
        return False
    cx, cy = cursor
    for edge, a, b in legs:
        p, q = point(Spot(edge, a), area), point(Spot(edge, b), area)
        dx, dy = q[0] - p[0], q[1] - p[1]
        seg = dx * dx + dy * dy
        u = 0.0 if seg == 0 else max(0.0, min(1.0, ((cx - p[0]) * dx + (cy - p[1]) * dy) / seg))
        if math.hypot(p[0] + u * dx - cx, p[1] + u * dy - cy) < CURSOR_CLEAR:
            return True
    return False


def plan(start: Spot, end: Spot, area: Area, half: dict[str, float], now: float, then: str,
         cursor: tuple[float, float] | None = None, unit: float = 1.0) -> Route:
    """A route around the edges from `start` to `end`: the shorter way, unless the cursor is on it and the
    other way is clear. `half[edge]` is half the moving picture's size along that edge."""
    lims = limits(area, half)
    start, end = clamp_spot(start, lims), clamp_spot(end, lims)
    options = []
    for clockwise in (True, False):
        legs = [leg for leg in _legs(start, end, lims, clockwise)]
        length = sum(abs(b - a) for _, a, b in legs)
        options.append((_near_cursor(legs, area, cursor), length, clockwise, legs))
    options.sort(key=lambda o: (o[0], o[1]))
    _, _, clockwise, legs = options[0]
    out, t = [], 0.0
    for i, (edge, a, b) in enumerate(legs):
        if i:
            t += CORNER_PAUSE
        seconds = max(0.15, abs(b - a) / (SPEED[edge] * unit))
        out.append(Leg(edge, a, b, t, seconds))
        t += seconds
    return Route(out, now, end, then, clockwise, unit)


def spot_of(side: str, x: float | None, y: float | None, lims: Limits) -> Spot:
    """Where a placement is on the loop: a corner is the end of its edge."""
    edge = EDGE_OF.get(side, "bottom")
    lo, hi = lims[edge]
    if side in ("left", "top-left"):
        return Spot(edge, lo)
    if side in ("right", "top-right"):
        return Spot(edge, hi)
    at = (x if edge in ("bottom", "top") else y)
    return clamp_spot(Spot(edge, (lo + hi) / 2 if at is None else at), lims)


# --------------------------------------------------------------------------
# Jumps, falls and flings
# --------------------------------------------------------------------------

GRAVITY = 2600.0          # pixels a second squared (unit 1)


@dataclass
class Arc:
    """A jump from one point to another in `seconds`, along a parabola: up and over, then down."""
    x0: float
    y0: float
    x1: float
    y1: float
    started: float
    seconds: float = 0.7
    gravity: float = GRAVITY

    def at(self, now: float) -> tuple[float, float]:
        t = min(self.seconds, max(0.0, now - self.started))
        vx = (self.x1 - self.x0) / self.seconds
        vy = (self.y1 - self.y0) / self.seconds - self.gravity * self.seconds / 2
        return self.x0 + vx * t, self.y0 + vy * t + self.gravity * t * t / 2

    def done(self, now: float) -> bool:
        return now - self.started >= self.seconds


@dataclass
class Flight:
    """Thrown: the character's middle flies under gravity and a little air drag until it meets an edge."""
    x: float
    y: float
    vx: float
    vy: float
    spin: float = 0.0               # degrees, for drawing: it tumbles the way it was thrown
    gravity: float = GRAVITY

    def step(self, dt: float) -> None:
        drag = 0.6 ** dt
        self.vx *= drag
        self.vy = self.vy * drag + self.gravity * dt
        self.x += self.vx * dt
        self.y += self.vy * dt
        self.spin += self.vx * dt * 0.25

    def hit(self, area: Area, half_w: float, half_h: float) -> Spot | None:
        """The edge it reaches now, if any. The sides and the top are grabbed; the bottom is a landing."""
        if self.x - half_w <= area.left and self.vx < 0:
            return Spot("left", self.y)
        if self.x + half_w >= area.right and self.vx > 0:
            return Spot("right", self.y)
        if self.y - half_h <= area.top and self.vy < 0:
            return Spot("top", self.x)
        if self.y + half_h >= area.bottom and self.vy > 0:
            return Spot("bottom", self.x)
        return None


FLING_SPEED = 1100.0      # released moving at least this fast (pixels a second): it is thrown


def released_fast(vx: float, vy: float) -> bool:
    return math.hypot(vx, vy) >= FLING_SPEED


# --------------------------------------------------------------------------
# Shake: fast back and forth while carried
# --------------------------------------------------------------------------

@dataclass
class Shake:
    window: float = 1.0             # seconds looked back
    turns: int = 4                  # this many changes of direction, each fast, make a shake
    speed: float = 700.0
    _marks: list[tuple[float, int]] = field(default_factory=list)
    _sign: int = 0

    def feel(self, now: float, vx: float) -> bool:
        """Feed the carried speed; True once, when it becomes a shake."""
        if abs(vx) < self.speed:
            return False
        sign = 1 if vx > 0 else -1
        if self._sign and sign != self._sign:
            self._marks.append((now, sign))
        self._sign = sign
        self._marks = [m for m in self._marks if now - m[0] <= self.window]
        if len(self._marks) >= self.turns:
            self._marks.clear()
            return True
        return False

    def reset(self) -> None:
        self._marks.clear()
        self._sign = 0
