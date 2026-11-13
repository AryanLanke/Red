"""A tiny in-process event bus (plan.md 0.2), so the companion can follow what Red hears and says.

    from red import events
    events.on("said", lambda text: bubble.reveal(text))
    events.emit("said", text="Not much. You?")

Names in use:
- `state(name, text)`: idle, listening, thinking, speaking, error (the overlay's states)
- `heard(text)`: the user's words, once the transcript is final
- `said(text)`: one piece of Red's reply, at the moment its audio starts playing (not when written)
- `emotion(name, strength)`, `companion(id)`, `idle_action(name)`, `mic(muted)`

Handlers run on the emitter's thread, in the order they were added. A handler that
raises is logged and skipped: it never breaks the emitter (the voice loop) or the
other handlers. Handlers must be quick; a slow one should hand the work to its own
thread (Qt widgets: a queued signal).
"""

from __future__ import annotations

import logging
import threading
from collections import defaultdict
from typing import Callable

log = logging.getLogger(__name__)

Handler = Callable[..., object]

_lock = threading.Lock()
_handlers: dict[str, list[Handler]] = defaultdict(list)


def on(name: str, fn: Handler) -> Callable[[], None]:
    """Call `fn(**payload)` on every `emit(name, ...)`. Returns a function that removes it again."""
    with _lock:
        _handlers[name].append(fn)
    return lambda: off(name, fn)


def off(name: str, fn: Handler) -> None:
    with _lock:
        try:
            _handlers[name].remove(fn)
        except ValueError:
            pass


def emit(event: str, /, **payload) -> None:
    """Tell every handler of `event`. Never raises. (`event` is positional, so a payload may
    have its own `name`, like state(name="speaking").)"""
    with _lock:
        handlers = list(_handlers.get(event, ()))
    for fn in handlers:
        try:
            fn(**payload)
        except Exception:  # noqa: BLE001 - a display or a plugin must never break Red
            log.exception("Event handler for %r failed", event)


def clear() -> None:
    """Remove every handler (tests)."""
    with _lock:
        _handlers.clear()
