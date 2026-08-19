"""Qt Help panel."""

import config
from PySide6.QtWidgets import QVBoxLayout, QPlainTextEdit
from ui_qt.panels.base import BasePanel


class HelpPanel(BasePanel):
    title = "Help"

    def __init__(self, app, parent=None):
        super().__init__(app, parent)
        layout = QVBoxLayout(self)
        box = QPlainTextEdit()
        box.setReadOnly(True)
        try:
            with open(config.USER_GUIDE_PATH, "r", encoding="utf-8") as fh:
                box.setPlainText(fh.read())
        except OSError:
            box.setPlainText("USER_GUIDE.txt not found.")
        layout.addWidget(box)
