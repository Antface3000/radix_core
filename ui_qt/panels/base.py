"""Base panel mixin."""

from PySide6.QtWidgets import QWidget


class BasePanel(QWidget):
    title = "Panel"

    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app

    def on_show(self):
        pass

    def on_project_change(self):
        pass
