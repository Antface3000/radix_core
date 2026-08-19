"""Subtle busy indicator — pulsing dots for AI / streaming status."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QWidget


class ActivityIndicator(QWidget):
    """Three small dots that pulse in sequence."""

    _DOT_R = 2
    _GAP = 5
    _COLOR_DIM = QColor("#4A6040")
    _COLOR_LIT = QColor("#93BA00")

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._frame = 0
        self._active = False
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        width = self._DOT_R * 2 * 3 + self._GAP * 2 + 4
        self.setFixedSize(width, 14)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    def is_active(self) -> bool:
        return self._active

    def start(self) -> None:
        if self._active:
            return
        self._active = True
        self._frame = 0
        self.show()
        self._timer.start(380)
        self.update()

    def stop(self) -> None:
        if not self._active:
            return
        self._active = False
        self._timer.stop()
        self.hide()
        self.update()

    def _tick(self) -> None:
        self._frame = (self._frame + 1) % 3
        self.update()

    def paintEvent(self, _event) -> None:
        if not self._active:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        y = self.height() / 2
        x = 2.0
        for i in range(3):
            lit = (self._frame % 3) == i
            color = self._COLOR_LIT if lit else self._COLOR_DIM
            painter.setBrush(color)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(int(x - self._DOT_R), int(y - self._DOT_R),
                                self._DOT_R * 2, self._DOT_R * 2)
            x += self._DOT_R * 2 + self._GAP


class ActivityStatus(QWidget):
    """Muted status line with optional pulsing dots when work is in progress."""

    def __init__(self, idle_text: str = "", parent: QWidget | None = None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self._indicator = ActivityIndicator(self)
        self._label = QLabel(idle_text)
        self._label.setProperty("muted", True)
        layout.addWidget(self._indicator)
        layout.addWidget(self._label, 1)
        self._indicator.stop()
        if not idle_text:
            self.hide()

    def set_status(self, text: str, *, active: bool = False) -> None:
        self._label.setText(text)
        if active:
            self._indicator.start()
            self.show()
        else:
            self._indicator.stop()
            if text:
                self.show()
            else:
                self.hide()
