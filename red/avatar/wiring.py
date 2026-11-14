"""Connects the companion's right-click menu to the running voice loop (called once from red/__main__.py).

Everything here is a small adapter over what the voice loop already has: the listener (Talk), the idle life's
song chooser (Play music), the companions module (Switch companion), the scheduler (reminders), the Red app
(Settings). Each is looked up defensively: a part that isn't there only greys its menu item out.
"""

from __future__ import annotations

import logging
import subprocess
import sys
import threading
from typing import Callable

from .actions import MenuActions

log = logging.getLogger(__name__)


def talk_function(get_listener: Callable[[], object]) -> Callable[[], None]:
    """Start listening, as if the hotkey had been pressed."""
    def talk() -> None:
        listener = get_listener()
        fire = getattr(listener, "trigger", None) or getattr(listener, "_fire", None)
        if fire is None:
            raise RuntimeError("Red isn't listening yet")
        fire("menu")
    return talk


def music_function(app, make_music=None, active=None) -> Callable[[], str | None]:
    """Pick a song the way the idle life does and play it after Red says what it is. Returns a line only
    if there is nothing to play; the song itself starts on its own thread."""
    def music() -> str | None:
        nonlocal make_music, active
        if make_music is None:
            from ..idle import make_music as make
            make_music = make
        if active is None:
            from .. import companions
            active = lambda: companions.active(app.settings.home)  # noqa: E731
        song = make_music(app.executor.registry)(active())
        if song is None:
            return "I can't find anything to play."

        def play() -> None:
            try:
                app.greet(song.announce)
                song.play()
            except Exception:  # noqa: BLE001 - a song that won't start is not worth a crash
                log.exception("Couldn't play the song")
        threading.Thread(target=play, name="red-menu-song", daemon=True).start()
        return None
    return music


def switch_function(app) -> Callable[[str], None]:
    """Switch everywhere (persona, voice, look): lane 2's set_active tells everyone with an event."""
    def switch(companion_id: str) -> None:
        from .. import companions
        companions.set_active(companion_id, app.settings.home)
    return switch


def quiet_function(app) -> Callable[[bool], None]:
    """Quiet mode: the idle life (grumbles, songs, idle actions) says and does nothing while it's on."""
    original: dict = {}

    def quiet(on: bool) -> None:
        life = getattr(app, "idle", None)
        if life is None or not hasattr(life, "_blocked"):
            return
        original.setdefault("blocked", life._blocked)
        was = original["blocked"]
        life._blocked = (lambda: True) if on else was
    return quiet


def settings_function() -> Callable[[], None]:
    def open_settings() -> None:
        subprocess.Popen([sys.executable, "-m", "red", "app"], close_fds=True)      # the Red app, its own window
    return open_settings


def quit_function() -> Callable[[], None]:
    def quit_red() -> None:
        from PySide6.QtWidgets import QApplication
        instance = QApplication.instance()
        if instance is not None:
            instance.quit()               # run_with_overlay returns, and the voice loop shuts down cleanly
    return quit_red


def sync_mic_badge(overlay, get_listener, sleep=None, tries: int = 240) -> bool:
    """The microphone may have been left off by the last run (Listener remembers it): once the listener
    exists, show the crossed-out mic if so. Polls every half second for up to two minutes."""
    import time
    sleep = sleep or time.sleep
    for _ in range(tries):
        listener = get_listener()
        if listener is not None:
            if getattr(listener, "muted", False):
                overlay.window.mic_signal.emit(True)
                return True
            return False
        sleep(0.5)
    return False


def start_summon_hotkey(overlay, settings, starter=None):
    """Ctrl+Alt+H (RED_SUMMON_HOTKEY): show the companion, which waves, or hide it. The hotkey's own thread
    only emits a queued Qt signal. Returns the hotkey (stop() it), or None when it is off or can't start."""
    hotkey = getattr(settings, "summon_hotkey", None)
    if not hotkey:
        return None
    try:
        if starter is None:
            from ..chat_window import start_hotkey as starter
        window = overlay.window
        listener = starter(hotkey, window.summon_signal.emit)
        overlay.summon_hotkey = listener
        return listener
    except Exception:  # noqa: BLE001 - the menu's Hide still works
        log.exception("Couldn't start the summon hotkey %r", hotkey)
        return None


def wire_menu(overlay, app) -> MenuActions | None:
    """Give a CompanionOverlay its menu back end. Never raises: the menu just stays greyed out."""
    try:
        window = overlay.window
        try:
            from ..actions import remind              # lane 2's: the set_reminder tool, richer times
        except ImportError:
            remind = None
        actions = MenuActions(app.settings.home, talk=talk_function(lambda: app.listener),
                              music=music_function(app), remind=remind)
        window.actions = actions
        window.on_switch = switch_function(app)
        window.on_quiet = quiet_function(app)
        window.on_settings = settings_function()
        window.on_quit = quit_function()
        start_summon_hotkey(overlay, app.settings)
        if getattr(app.settings, "tray", "on"):
            from ..tray import attach_tray
            attach_tray(overlay)
        threading.Thread(target=sync_mic_badge, args=(overlay, lambda: app.listener), name="red-mic-badge",
                         daemon=True).start()
        return actions
    except Exception:  # noqa: BLE001 - the companion is only a display
        log.exception("Couldn't connect the companion's menu")
        return None
