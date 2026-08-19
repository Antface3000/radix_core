"""PySide6 application entry."""

import sys

from PySide6.QtWidgets import QApplication

import config
from src.logutil import get_logger
from ui_qt.main_window import MainWindow

log = get_logger("app")


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(config.APP_TITLE)
    app.setApplicationVersion(config.APP_VERSION)
    log.info("Starting %s v%s", config.APP_TITLE, config.APP_VERSION)
    window = MainWindow()
    window.show()
    code = app.exec()
    log.info("Exit code %s", code)
    return code
