"""PySide6 application entry."""

import sys

from PySide6.QtWidgets import QApplication, QStyleFactory

import config
from src.logutil import get_logger
from ui_qt.main_window import MainWindow
from ui_qt.theme import load_stylesheet

log = get_logger("app")


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(config.APP_TITLE)
    app.setApplicationVersion(config.APP_VERSION)
    # Fusion + app-wide QSS so dialogs, lightboxes, and menus match the shell
    # (widget-only stylesheets do not reliably reach top-level popups).
    if "Fusion" in QStyleFactory.keys():
        app.setStyle(QStyleFactory.create("Fusion"))
    app.setStyleSheet(load_stylesheet())
    log.info("Starting %s v%s", config.APP_TITLE, config.APP_VERSION)
    window = MainWindow()
    window.show()
    code = app.exec()
    log.info("Exit code %s", code)
    return code
