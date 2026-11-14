"""Small frameless dialogs for the companion's menu, in the glow look: frosted, milky, no outline.

- ReminderDialog: what to remind you of, and when (chips for the usual times, or type "15:30", "3pm",
  "in 20 minutes", "tomorrow 9am").
- TaskDialog: one line, Enter adds it to the to-do list.
- TodoDialog: the list, tick things off, remove them, add more.

They take a `MenuActions` (red/avatar/actions.py) and call `on_done(text)` with a line the companion can
show. They never block the Qt loop (`show()`, not `exec()`), take the keyboard while they are open, and go
on Esc. Dragging anywhere on the glass moves them.
"""

from __future__ import annotations

import functools
from typing import Callable

INK = "#1f1f26"
SOFT = "#6b6f7a"
ACCENT = "#e5484d"           # Red's colour: the listening dot
RADIUS = 18

STYLE = f"""
QLabel {{ color: {INK}; font: 10pt "Segoe UI"; background: transparent; }}
QLabel#title {{ font: 600 12pt "Segoe UI"; }}
QLabel#hint {{ color: {SOFT}; font: 9pt "Segoe UI"; }}
QLabel#error {{ color: {ACCENT}; font: 9pt "Segoe UI"; }}
QLineEdit {{ background: rgba(255,255,255,215); border: none; border-radius: 10px; padding: 8px 11px;
            color: {INK}; font: 10pt "Segoe UI"; selection-background-color: rgba(229,72,77,90); }}
QLineEdit:focus {{ background: rgba(255,255,255,255); }}
QPushButton {{ background: rgba(31,31,38,16); border: none; border-radius: 10px; padding: 7px 13px;
              color: {INK}; font: 9.5pt "Segoe UI"; }}
QPushButton:hover {{ background: rgba(31,31,38,30); }}
QPushButton#primary {{ background: {ACCENT}; color: white; font: 600 9.5pt "Segoe UI"; }}
QPushButton#primary:hover {{ background: #d13d42; }}
QPushButton#chip {{ padding: 5px 10px; font: 9pt "Segoe UI"; }}
QPushButton#remove {{ padding: 2px 8px; color: {SOFT}; background: transparent; }}
QPushButton#remove:hover {{ color: {ACCENT}; background: rgba(229,72,77,26); }}
QCheckBox {{ color: {INK}; font: 10pt "Segoe UI"; spacing: 9px; background: transparent; }}
QCheckBox::indicator {{ width: 17px; height: 17px; border-radius: 6px; background: rgba(255,255,255,230); }}
QCheckBox::indicator:checked {{ background: {ACCENT}; }}
QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
"""

CHIPS = (("10 min", "in 10 minutes"), ("30 min", "in 30 minutes"), ("1 hour", "in 1 hour"),
         ("Tomorrow 9am", "tomorrow 9am"))


@functools.cache
def _classes():
    from PySide6.QtCore import QPointF, QRectF, Qt
    from PySide6.QtGui import QColor, QGuiApplication, QLinearGradient, QPainter, QPainterPath
    from PySide6.QtWidgets import (QCheckBox, QDialog, QHBoxLayout, QLabel, QLineEdit, QPushButton,
                                   QScrollArea, QVBoxLayout, QWidget)

    class GlassDialog(QDialog):
        WIDTH = 340

        def __init__(self, title: str, on_done: Callable[[str], None] | None = None):
            super().__init__(None)
            self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
                                | Qt.WindowType.Tool)
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
            self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
            self.setStyleSheet(STYLE)
            self.setFixedWidth(self.WIDTH)
            self.on_done = on_done
            self._drag: QPointF | None = None
            self.column = QVBoxLayout(self)
            self.column.setContentsMargins(22, 20, 22, 18)
            self.column.setSpacing(9)
            head = QLabel(title)
            head.setObjectName("title")
            self.column.addWidget(head)

        # the glass: a soft milky gradient with a faint shadow, and no edge line
        def paintEvent(self, event):  # noqa: N802
            p = QPainter(self)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            body = QRectF(self.rect()).adjusted(10, 8, -10, -12)
            for i in range(7, 0, -1):                          # shadow: stacked, fading rounded rects
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(20, 20, 40, 5 + (7 - i)))
                p.drawRoundedRect(body.adjusted(-i, -i + 4, i, i + 4), RADIUS + i, RADIUS + i)
            gradient = QLinearGradient(body.topLeft(), body.bottomLeft())
            gradient.setColorAt(0.0, QColor(255, 255, 255, 244))
            gradient.setColorAt(1.0, QColor(240, 242, 249, 240))
            path = QPainterPath()
            path.addRoundedRect(body, RADIUS, RADIUS)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(gradient)
            p.drawPath(path)
            p.end()

        def mousePressEvent(self, event):  # noqa: N802
            if event.button() == Qt.MouseButton.LeftButton:
                self._drag = event.globalPosition() - QPointF(self.pos())

        def mouseMoveEvent(self, event):  # noqa: N802
            if self._drag is not None:
                self.move((event.globalPosition() - self._drag).toPoint())

        def mouseReleaseEvent(self, event):  # noqa: N802
            self._drag = None

        def keyPressEvent(self, event):  # noqa: N802
            if event.key() == Qt.Key.Key_Escape:
                self.close()
            else:
                super().keyPressEvent(event)

        def label(self, text: str, name: str = "") -> QLabel:
            label = QLabel(text)
            if name:
                label.setObjectName(name)
            label.setWordWrap(True)
            return label

        def buttons(self, ok_text: str, ok) -> tuple[QPushButton, QPushButton]:
            row = QHBoxLayout()
            row.setSpacing(8)
            row.addStretch(1)
            cancel = QPushButton("Cancel")
            cancel.clicked.connect(self.close)
            primary = QPushButton(ok_text)
            primary.setObjectName("primary")
            primary.setDefault(True)
            primary.clicked.connect(ok)
            row.addWidget(cancel)
            row.addWidget(primary)
            self.column.addLayout(row)
            return cancel, primary

        def finish(self, text: str) -> None:
            if self.on_done is not None:
                self.on_done(text)
            self.close()

        def show_near(self, anchor, area) -> None:
            """Open next to `anchor` (the companion's rectangle), kept inside `area` (the work area)."""
            self.adjustSize()
            w, h = self.width(), self.height()
            x = anchor.center().x() - w // 2
            y = anchor.top() - h - 6 if anchor.top() - h - 6 >= area.top() else anchor.bottom() + 6
            x = max(area.left(), min(x, area.right() - w))
            y = max(area.top(), min(y, area.bottom() - h))
            self.move(int(x), int(y))
            self.show()
            self.raise_()
            self.activateWindow()
            self.focus_first()

        def focus_first(self) -> None:
            pass

    class ReminderDialog(GlassDialog):
        def __init__(self, actions, on_done=None):
            super().__init__("Remind me", on_done)
            self.actions = actions
            self.what = QLineEdit()
            self.what.setPlaceholderText("What should I remind you about?")
            self.what.setMaxLength(200)
            self.when = QLineEdit()
            self.when.setPlaceholderText("When? 15:30, 3pm, in 20 minutes")
            self.column.addWidget(self.what)
            chips = QHBoxLayout()
            chips.setSpacing(6)
            for label, text in CHIPS:
                chip = QPushButton(label)
                chip.setObjectName("chip")
                chip.clicked.connect(functools.partial(self.when.setText, text))
                chips.addWidget(chip)
            self.column.addLayout(chips)
            self.column.addWidget(self.when)
            self.error = self.label("", "error")
            self.error.hide()
            self.column.addWidget(self.error)
            self.buttons("Set reminder", self.submit)
            self.what.returnPressed.connect(self.when.setFocus)
            self.when.returnPressed.connect(self.submit)

        def focus_first(self) -> None:
            self.what.setFocus()

        def submit(self) -> None:
            try:
                line = self.actions.remind(self.what.text(), self.when.text())
            except ValueError as e:
                self.error.setText(str(e))
                self.error.show()
                self.adjustSize()
                return
            self.finish(line)

    class TaskDialog(GlassDialog):
        def __init__(self, actions, on_done=None):
            super().__init__("Add a task", on_done)
            self.actions = actions
            self.text = QLineEdit()
            self.text.setPlaceholderText("What needs doing?")
            self.text.setMaxLength(200)
            self.column.addWidget(self.text)
            self.error = self.label("", "error")
            self.error.hide()
            self.column.addWidget(self.error)
            self.buttons("Add", self.submit)
            self.text.returnPressed.connect(self.submit)

        def focus_first(self) -> None:
            self.text.setFocus()

        def submit(self) -> None:
            try:
                task = self.actions.add_task(self.text.text())
            except ValueError as e:
                self.error.setText(str(e))
                self.error.show()
                return
            self.finish(f"Added to your list: {task.text}")

    class TodoDialog(GlassDialog):
        MAX_ROWS_HEIGHT = 260

        def __init__(self, actions, on_done=None):
            super().__init__("To-do", on_done)
            self.actions = actions
            self.new = QLineEdit()
            self.new.setPlaceholderText("Add a task and press Enter")
            self.new.setMaxLength(200)
            self.column.addWidget(self.new)
            self.holder = QWidget()
            self.rows = QVBoxLayout(self.holder)
            self.rows.setContentsMargins(2, 2, 2, 2)
            self.rows.setSpacing(4)
            self.scroll = QScrollArea()
            self.scroll.setWidgetResizable(True)
            self.scroll.setWidget(self.holder)
            self.scroll.setFrameShape(QScrollArea.Shape.NoFrame)
            self.column.addWidget(self.scroll)
            self.empty = self.label("Nothing to do. Add something above.", "hint")
            self.column.addWidget(self.empty)
            row = QHBoxLayout()
            clear = QPushButton("Clear done")
            clear.clicked.connect(self.clear_done)
            close = QPushButton("Close")
            close.setObjectName("primary")
            close.clicked.connect(self.close)
            row.addWidget(clear)
            row.addStretch(1)
            row.addWidget(close)
            self.column.addLayout(row)
            self.new.returnPressed.connect(self.add)
            self.refresh()

        def focus_first(self) -> None:
            self.new.setFocus()

        def refresh(self) -> None:
            while self.rows.count():
                item = self.rows.takeAt(0)
                if item.widget() is not None:
                    item.widget().deleteLater()
            tasks = self.actions.list_tasks()
            # open tasks first, then the finished ones
            for task in sorted(tasks, key=lambda t: t.done):
                line = QHBoxLayout()
                box = QCheckBox(task.text)
                box.setChecked(task.done)
                box.toggled.connect(functools.partial(self.tick, task.id))
                if task.done:
                    box.setStyleSheet(f"QCheckBox {{ color: {SOFT}; font: italic 10pt 'Segoe UI'; }}")
                remove = QPushButton("✕")
                remove.setObjectName("remove")
                remove.setToolTip("Remove")
                remove.clicked.connect(functools.partial(self.remove, task.id))
                line.addWidget(box, 1)
                line.addWidget(remove)
                cell = QWidget()
                cell.setLayout(line)
                self.rows.addWidget(cell)
            self.rows.addStretch(1)
            self.empty.setVisible(not tasks)
            self.scroll.setVisible(bool(tasks))
            self.scroll.setFixedHeight(min(self.MAX_ROWS_HEIGHT, 45 * len(tasks) + 10))
            self.adjustSize()

        def add(self) -> None:
            try:
                self.actions.add_task(self.new.text())
            except ValueError:
                return
            self.new.clear()
            self.refresh()

        def tick(self, task_id: str, done: bool) -> None:
            self.actions.set_done(task_id, done)
            self.refresh()

        def remove(self, task_id: str) -> None:
            self.actions.remove_task(task_id)
            self.refresh()

        def clear_done(self) -> None:
            self.actions.clear_done()
            self.refresh()

    return ReminderDialog, TaskDialog, TodoDialog


def reminder_dialog(actions, on_done=None):
    return _classes()[0](actions, on_done)


def task_dialog(actions, on_done=None):
    return _classes()[1](actions, on_done)


def todo_dialog(actions, on_done=None):
    return _classes()[2](actions, on_done)
