"""Shared dialog base so popups always paint with the app theme."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog


class ThemedDialog(QDialog):
    """QDialog that reliably draws the dark QSS background on Windows."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setObjectName("ThemedDialog")
