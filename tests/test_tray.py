"""The tray icon: the companion's menu, one click away. Offscreen, with a fake tray (no real tray icon)."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

QtWidgets = pytest.importorskip("PySide6.QtWidgets")

from red import tray as tray_mod  # noqa: E402
from test_avatar import FakeActions, window, app, menu_labels  # noqa: E402,F401


class FakeTray:
    """A stand-in for QSystemTrayIcon that records what the code does to it."""

    created = []

    def __init__(self):
        from PySide6.QtCore import QObject, Signal

        class Sig(QObject):
            activated = Signal(object)
        self._sig = Sig()
        self.activated = self._sig.activated
        self.icon = None
        self.tip = ""
        self.menu = None
        self.visible = False
        FakeTray.created.append(self)

    def setIcon(self, icon):  # noqa: N802
        self.icon = icon

    def setToolTip(self, text):  # noqa: N802
        self.tip = text

    def setContextMenu(self, menu):  # noqa: N802
        self.menu = menu

    def show(self):
        self.visible = True

    def hide(self):
        self.visible = False


def test_the_icon_is_drawn_and_changes_when_the_mic_is_off(app):
    on, off = tray_mod.draw_icon(False), tray_mod.draw_icon(True)
    assert not on.isNull() and not off.isNull()
    assert on.pixmap(64, 64).toImage() != off.pixmap(64, 64).toImage()


def test_the_tray_menu_is_the_companions_menu(app, window, tmp_path):
    w = window.window
    w.actions = FakeActions(tmp_path).real
    w.on_settings = lambda: None
    icon = tray_mod.TrayIcon(w, tray_class=FakeTray)
    assert icon.tray.menu is icon.menu and icon.tray.tip == "Red"
    assert menu_labels(icon.menu) == menu_labels(w.build_menu())
    assert "Talk" in menu_labels(icon.menu) and "Quit Red" in menu_labels(icon.menu)
    w.muted = True
    icon.rebuild()
    assert icon.tray.tip == "Red (microphone off)"
    assert "Microphone on" in menu_labels(icon.menu)             # always current when it opens


def test_clicking_the_tray_icon_shows_or_hides_the_companion_and_double_click_opens_chat(app, window, tmp_path):
    from PySide6.QtWidgets import QSystemTrayIcon
    w = window.window
    opened = []
    icon = tray_mod.TrayIcon(w, tray_class=FakeTray, open_chat=lambda: opened.append("chat"))
    assert w.isVisible()
    icon._activated(QSystemTrayIcon.ActivationReason.Trigger)
    assert not w.isVisible()                                     # a click hides it...
    icon._activated(QSystemTrayIcon.ActivationReason.Trigger)
    assert w.isVisible()                                         # ...and brings it back, waving
    icon._activated(QSystemTrayIcon.ActivationReason.DoubleClick)
    assert opened == ["chat"]
    icon._activated(QSystemTrayIcon.ActivationReason.Context)    # right click: the menu, nothing else
    assert opened == ["chat"] and w.isVisible()


def test_attach_tray_needs_a_tray_and_closes_with_the_overlay(app, window):
    assert tray_mod.attach_tray(window, available=lambda: False, tray_class=FakeTray) is None
    icon = tray_mod.attach_tray(window, available=lambda: True, tray_class=FakeTray)
    assert icon is not None and icon.tray.visible and window.tray is icon
    window.close()
    assert not icon.tray.visible


def test_the_tray_setting(tmp_path, monkeypatch):
    from red.config import load_settings
    for key in [k for k in os.environ if k.startswith("RED_")]:
        monkeypatch.delenv(key)
    assert load_settings(tmp_path).tray == "on"
    monkeypatch.setenv("RED_TRAY", "off")
    assert load_settings(tmp_path).tray is None
