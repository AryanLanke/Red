"""What the companion does when it is left alone: glance around, yawn, stretch, get bored, doze off,
hop along the edge to a new spot, and now and then go to another corner.

This module is the part that needs no screen: the scripts (which frame, for how long), the weighted
choice of what to do next and when, and the walk's path. The window (red/avatar/window.py) plays them,
either on lane 2's `idle_action` events (red/idle.py) or, when none arrive, on its own timer.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

# The frames these use exist for every placement: peek_<name>, cornerR_<name>, top_<name>, topL_<name>...
IDLE_FRAMES = ("look_left", "look_right", "look_up", "yawn", "stretch", "sleepy", "bored")

# name -> [(frame, seconds)]. None is the plain idle frame. `then` says what follows the last step.
SCRIPTS: dict[str, list[tuple[str | None, float]]] = {
    "look_around": [("look_left", 1.3), (None, 0.35), ("look_right", 1.6), (None, 0.3), ("look_up", 1.2)],
    "yawn": [("sleepy", 0.6), ("yawn", 2.2), (None, 0.4)],
    "stretch": [("stretch", 2.4), (None, 0.4)],
    "bored": [("bored", 5.0), ("look_left", 0.9), ("bored", 3.0)],
    "doze": [("sleepy", 2.5), (None, 0.35), ("sleepy", 3.0)],
}
THEN = {"doze": "sleep"}          # after the last step: fall asleep

# lane 2's idle_action names -> the script (or movement) to play
EVENT_ALIASES = {"look_around": "look_around", "yawn": "yawn", "stretch": "stretch", "doze": "doze",
                 "wander": "wander", "hum": "hum", "bored": "bored", "corner": "corner"}

# Which of the companion's idle switches (companion.toml [idle]) lets each action happen.
SWITCH = {"look_around": "look_around", "yawn": "look_around", "stretch": "look_around",
          "bored": "look_around", "hum": "look_around", "doze": "sleep", "wander": "wander",
          "corner": "wander"}

FIRST_AFTER = (20.0, 45.0)        # seconds of calm before the first thing
EVERY = (30.0, 90.0)              # then one thing every so often
BORED_AFTER = 90.0                # seconds since the last time anyone talked to it
DOZE_AFTER = 150.0
WALK_SPEED = 150.0                # pixels per second
HOP_SECONDS = 0.38
HOP_HEIGHT = 9.0                  # in units of SIZES[size] / 300


@dataclass
class Script:
    steps: list[tuple[str | None, float]]
    started: float
    then: str | None = None

    @property
    def length(self) -> float:
        return sum(seconds for _, seconds in self.steps)

    def at(self, now: float) -> tuple[bool, str | None]:
        """(finished, the frame name for this moment)."""
        t = now - self.started
        for frame, seconds in self.steps:
            if t < seconds:
                return False, frame
            t -= seconds
        return True, None


def script_for(name: str, now: float) -> Script | None:
    steps = SCRIPTS.get(name)
    return Script(list(steps), now, THEN.get(name)) if steps else None


def choose(idle_for: float, rng: random.Random, allowed, side: str, can_corner: bool = True) -> str:
    """What to do next, by chance. `idle_for` is how long since anyone talked to it; `allowed(action)`
    says whether the companion's idle switches let it."""
    weights = {"look_around": 40, "yawn": 12, "stretch": 8, "hum": 4}
    if idle_for > BORED_AFTER:
        weights["bored"] = 14
    if idle_for > DOZE_AFTER:
        weights["doze"] = 16
    if side in ("edge", "top"):
        weights["wander"] = 12
    if can_corner:
        weights["corner"] = 4
    weights = {k: w for k, w in weights.items() if allowed(k)}
    if not weights:
        return ""
    names = list(weights)
    return rng.choices(names, [weights[n] for n in names])[0]


def next_gap(rng: random.Random, first: bool = False) -> float:
    return rng.uniform(*(FIRST_AFTER if first else EVERY))


@dataclass
class Walk:
    """A hop-walk along an edge: from x0 to x1 (the middle of the character), a hop every step."""
    x0: float
    x1: float
    started: float
    hops: list[float] = field(default_factory=list)

    @property
    def seconds(self) -> float:
        return max(0.2, abs(self.x1 - self.x0) / WALK_SPEED)

    @property
    def direction(self) -> str:
        return "look_right" if self.x1 > self.x0 else "look_left"

    def x_at(self, now: float) -> float:
        t = min(1.0, max(0.0, (now - self.started) / self.seconds))
        eased = t * t * (3 - 2 * t)                     # it speeds up and slows down
        return self.x0 + (self.x1 - self.x0) * eased

    def hop_at(self, now: float) -> float:
        """0..1: how high the current hop is."""
        age = (now - self.started) % HOP_SECONDS
        return math.sin(math.pi * age / HOP_SECONDS)

    def done(self, now: float) -> bool:
        return now - self.started >= self.seconds


def walk_target(x: float, left: float, right: float, half: float, rng: random.Random,
                minimum: float = 140.0) -> float | None:
    """A new spot along the edge, at least `minimum` pixels from where it is, with `half` (half the
    picture's width) kept on screen. None if the edge is too short."""
    lo, hi = left + half + 12, right - half - 12
    if hi - lo < minimum:
        return None
    for _ in range(12):
        target = rng.uniform(lo, hi)
        if abs(target - x) >= minimum:
            return target
    return lo if abs(lo - x) >= abs(hi - x) else hi
