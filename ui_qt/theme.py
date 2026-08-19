"""Qt theme helpers."""

from pathlib import Path

import config

QSS_PATH = Path(config.ASSETS_DIR) / "theme" / "radix.qss"

BG_APP = "#080C08"
LIME = "#B8E800"
TEXT_MUTED = "#4A6040"
RED = "#E03A3A"


def load_stylesheet() -> str:
    try:
        return QSS_PATH.read_text(encoding="utf-8")
    except OSError:
        return ""
