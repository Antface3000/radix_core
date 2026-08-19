"""Review dialog for staged canon captures (approve / discard before write)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QVBoxLayout,
)

from src.capture_queue import CaptureQueue, describe_item, item_preview


class CaptureReviewDialog(QDialog):
    """Lists pending capture items; approve writes canon, discard drops."""

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.setWindowTitle("Pending canon — review before writing")
        self.resize(640, 440)
        self._items: dict[str, dict] = {}

        v = QVBoxLayout(self)
        hint = QLabel(
            "Agents proposed these canon updates. Approve to write them into "
            "the Lorebook / Story Bible / World State, or discard.")
        hint.setWordWrap(True)
        hint.setProperty("muted", True)
        v.addWidget(hint)

        split = QSplitter(Qt.Vertical)
        self.listing = QListWidget()
        self.listing.currentItemChanged.connect(self._on_select)
        split.addWidget(self.listing)
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setPlaceholderText("Select an item to preview its content.")
        split.addWidget(self.preview)
        split.setSizes([240, 160])
        v.addWidget(split, 1)

        row = QHBoxLayout()
        approve_btn = QPushButton("Approve selected")
        approve_btn.clicked.connect(self._approve_selected)
        row.addWidget(approve_btn)
        discard_btn = QPushButton("Discard selected")
        discard_btn.setProperty("secondary", True)
        discard_btn.clicked.connect(self._discard_selected)
        row.addWidget(discard_btn)
        row.addStretch()
        approve_all_btn = QPushButton("Approve all")
        approve_all_btn.clicked.connect(self._approve_all)
        row.addWidget(approve_all_btn)
        discard_all_btn = QPushButton("Discard all")
        discard_all_btn.setProperty("danger", True)
        discard_all_btn.clicked.connect(self._discard_all)
        row.addWidget(discard_all_btn)
        close_btn = QPushButton("Close")
        close_btn.setProperty("secondary", True)
        close_btn.clicked.connect(self.accept)
        row.addWidget(close_btn)
        v.addLayout(row)

        self.refresh()

    def _queue(self) -> CaptureQueue:
        return CaptureQueue(self.app.engine.paths)

    def refresh(self):
        self.listing.clear()
        self.preview.clear()
        self._items = {}
        for item in self._queue().load():
            item_id = item.get("id", "")
            self._items[item_id] = item
            lw = QListWidgetItem(describe_item(item))
            lw.setData(Qt.UserRole, item_id)
            self.listing.addItem(lw)
        if not self._items:
            self.preview.setPlaceholderText("No pending canon. All clear.")

    def _on_select(self, current, _previous=None):
        if current is None:
            self.preview.clear()
            return
        item = self._items.get(current.data(Qt.UserRole))
        self.preview.setPlainText(item_preview(item) if item else "")

    def _selected_id(self) -> str | None:
        current = self.listing.currentItem()
        return current.data(Qt.UserRole) if current else None

    def _after_change(self, toast: str = ""):
        self.refresh()
        if toast:
            self.app.show_toast(toast)
        self.app.refresh_canon_panels()
        if hasattr(self.app, "update_capture_chip"):
            self.app.update_capture_chip()

    def _approve_selected(self):
        item_id = self._selected_id()
        if not item_id:
            return
        applied = self._queue().approve(item_id)
        if applied:
            self._after_change("Canon written.")

    def _discard_selected(self):
        item_id = self._selected_id()
        if not item_id:
            return
        if self._queue().discard(item_id):
            self._after_change("Capture discarded.")

    def _approve_all(self):
        count = self._queue().approve_all()
        if count:
            self._after_change(f"Canon written ({count} items).")
        else:
            self._after_change()

    def _discard_all(self):
        self._queue().clear()
        self._after_change("All pending captures discarded.")
