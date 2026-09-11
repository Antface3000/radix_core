"""Shared auto-scroll toggle for streaming output panels."""

from __future__ import annotations

from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QCheckBox, QPlainTextEdit, QTextEdit, QWidget

SETTING_KEY = "ui.panel_auto_scroll"


def make_auto_scroll_checkbox(app, parent: QWidget | None = None) -> QCheckBox:
    cb = QCheckBox("Auto-scroll to end", parent)
    cb.setToolTip("Keep streaming output scrolled to the latest text")
    cb.setChecked(app.settings.get(SETTING_KEY, True))
    cb.toggled.connect(lambda checked: set_auto_scroll(app, checked))
    _register_checkbox(app, cb)
    return cb


def _register_checkbox(app, cb: QCheckBox) -> None:
    boxes: list[QCheckBox] = getattr(app, "_auto_scroll_checkboxes", None)
    if boxes is None:
        boxes = []
        app._auto_scroll_checkboxes = boxes
    if cb not in boxes:
        boxes.append(cb)


def set_auto_scroll(app, enabled: bool) -> None:
    app.settings.set(SETTING_KEY, bool(enabled), save=True)
    for cb in getattr(app, "_auto_scroll_checkboxes", []):
        if cb.isChecked() != enabled:
            cb.blockSignals(True)
            cb.setChecked(enabled)
            cb.blockSignals(False)


def is_auto_scroll(app) -> bool:
    return bool(app.settings.get(SETTING_KEY, True))


def scroll_to_end(widget: QPlainTextEdit | QTextEdit, app) -> None:
    if not is_auto_scroll(app):
        return
    sb = widget.verticalScrollBar()
    sb.setValue(sb.maximum())


def append_without_forced_scroll(widget: QPlainTextEdit | QTextEdit, text: str,
                                 app) -> None:
    """Insert at the document end. Jump the viewport only if auto-scroll is on.

    Moving the widget's text cursor to End always reveals that position in Qt,
    which ignored the Auto-scroll checkbox.
    """
    if not text:
        return
    cur = QTextCursor(widget.document())
    cur.movePosition(QTextCursor.MoveOperation.End)
    cur.insertText(text)
    scroll_to_end(widget, app)
