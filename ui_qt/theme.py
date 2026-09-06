"""Qt theme helpers."""

from pathlib import Path

from PySide6.QtWidgets import QFileDialog

import config

QSS_PATH = Path(config.ASSETS_DIR) / "theme" / "radix.qss"

BG_APP = "#080C08"
LIME = "#B8E800"
TEXT_MUTED = "#4A6040"
RED = "#E03A3A"

# Use Qt-styled file dialogs so they match the dark lime theme on Windows.
_FILE_OPTS = QFileDialog.Option.DontUseNativeDialog


def load_stylesheet() -> str:
    try:
        return QSS_PATH.read_text(encoding="utf-8")
    except OSError:
        return ""


def get_open_file_name(parent, caption, directory="", filter=""):
    return QFileDialog.getOpenFileName(
        parent, caption, directory, filter, options=_FILE_OPTS)


def get_save_file_name(parent, caption, directory="", filter=""):
    return QFileDialog.getSaveFileName(
        parent, caption, directory, filter, options=_FILE_OPTS)


def get_existing_directory(parent, caption, directory=""):
    return QFileDialog.getExistingDirectory(
        parent, caption, directory, options=_FILE_OPTS)
