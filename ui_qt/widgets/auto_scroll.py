"""Shared auto-scroll toggle for streaming output panels."""

from __future__ import annotations

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


def scroll_to_end(widget: QPlainTextEdit | QTextEdit, app) -> None:
    if not app.settings.get(SETTING_KEY, True):
        return
    sb = widget.verticalScrollBar()
    sb.setValue(sb.maximum())
