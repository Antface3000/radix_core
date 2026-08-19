"""Stub panel for deferred parity features."""

from PySide6.QtWidgets import QVBoxLayout, QLabel
from ui_qt.panels.base import BasePanel


class StubPanel(BasePanel):
    def __init__(self, app, title: str, message: str, parent=None):
        super().__init__(app, parent)
        self.title = title
        layout = QVBoxLayout(self)
        lbl = QLabel(message)
        lbl.setWordWrap(True)
        lbl.setProperty("muted", True)
        layout.addWidget(lbl)
        layout.addStretch()
