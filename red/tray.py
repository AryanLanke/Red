"""Red's tray icon: the same menu as right-clicking the companion, always one click away.

It is how you get a hidden companion back (click the icon), and it works for people who run Red without a
companion picture. The menu is the companion window's own (`build_menu()`), rebuilt each time it opens, so
the two never drift apart: Talk, reminders and tasks, music, move, switch companion, size, sleep, quiet,
microphone, settings, hide and quit.

- left click: show the companion (it waves) or hide it
- double click: open the chat window
- the icon is drawn here (a red disc with an R); it gets a slash when the microphone is off
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)

TOOLTIP = "Red"


def draw_icon(muted: bool = False, size: int = 64):
    """A Qt icon: a red disc with a white R, crossed out when the microphone is off."""
    from PySide6.QtCore import QPointF, QRectF, Qt
    from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPen, QPixmap
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("#e5484d"))
    p.drawEllipse(QRectF(3, 3, size - 6, size - 6))
    font = QFont("Segoe UI", int(size * 0.42))
    font.setBold(True)
    p.setFont(font)
    p.setPen(QColor("white"))
    p.drawText(QRectF(0, 0, size, size * 0.96), Qt.AlignmentFlag.AlignCenter, "R")
    if muted:
        p.setPen(QPen(QColor(30, 30, 38), size * 0.1, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(QPointF(size * 0.2, size * 0.2), QPointF(size * 0.8, size * 0.8))
        p.setPen(QPen(QColor("white"), size * 0.04, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(QPointF(size * 0.25, size * 0.15), QPointF(size * 0.85, size * 0.75))
    p.end()
    return QIcon(pm)


class TrayIcon:
    """The tray icon for a companion window (red/avatar/window.py's CompanionWindow)."""

    def __init__(self, window, *, tray_class=None, open_chat=None):
        from PySide6.QtWidgets import QMenu, QSystemTrayIcon
        self.window = window
        self.open_chat = open_chat
        self.tray = (tray_class or QSystemTrayIcon)()
        self.tray.setIcon(draw_icon(window.muted))
        self.tray.setToolTip(TOOLTIP)
        self.menu = QMenu()
        self._built = None
        self.menu.aboutToShow.connect(self.rebuild)
        self.tray.setContextMenu(self.menu)
        self.tray.activated.connect(self._activated)
        self.rebuild()

    def rebuild(self) -> None:
        """The companion's menu, fresh: its checkmarks and enabled items are always current."""
        self._built = self.window.build_menu()            # keeps its actions alive while the tray menu shows them
        self.menu.clear()
        for action in self._built.actions():
            self.menu.addAction(action)
        self.tray.setIcon(draw_icon(self.window.muted))
        self.tray.setToolTip(TOOLTIP + (" (microphone off)" if self.window.muted else ""))

    def _activated(self, reason) -> None:
        from PySide6.QtWidgets import QSystemTrayIcon
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.window.summon()
        elif reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            chat = self.open_chat or self.window.on_click
            if chat is not None:
                try:
                    chat()
                except Exception:  # noqa: BLE001 - the tray must survive a broken callback
                    log.exception("Tray double-click failed")

    def show(self) -> None:
        self.tray.show()

    def close(self) -> None:
        try:
            self.tray.hide()
        except RuntimeError:
            pass


def attach_tray(overlay, *, available=None, tray_class=None):
    """Give a CompanionOverlay a tray icon. None when the desktop has no tray (or it is turned off)."""
    try:
        from PySide6.QtWidgets import QSystemTrayIcon
        if (available or QSystemTrayIcon.isSystemTrayAvailable)() is False:
            return None
        tray = TrayIcon(overlay.window, tray_class=tray_class)
        tray.show()
        overlay.tray = tray
        return tray
    except Exception:  # noqa: BLE001 - the tray is a convenience
        log.exception("Couldn't make the tray icon")
        return None
