"""Manuscript binder: drag-reorder chapters with status metadata."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QListWidget, QListWidgetItem, QAbstractItemView


class BinderWidget(QListWidget):
    chapter_selected = Signal(str)
    reordered = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragDropMode(QAbstractItemView.InternalMove)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setMinimumWidth(160)
        self.setMaximumWidth(280)
        self.currentItemChanged.connect(self._emit_selected)
        self.model().rowsMoved.connect(self._emit_order)

    def reload(self, items: list[dict], current_id: str | None = None):
        self.blockSignals(True)
        self.clear()
        current = None
        for ch in items:
            status = ch.get("status") or "draft"
            label = f"{ch['name']}  [{status}]"
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, ch["id"])
            self.addItem(item)
            if ch["id"] == current_id:
                current = item
        if current:
            self.setCurrentItem(current)
        self.blockSignals(False)

    def select_id(self, chapter_id: str | None):
        if not chapter_id:
            return
        for i in range(self.count()):
            item = self.item(i)
            if item.data(Qt.UserRole) == chapter_id:
                self.blockSignals(True)
                self.setCurrentItem(item)
                self.blockSignals(False)
                return

    def ordered_ids(self) -> list[str]:
        return [self.item(i).data(Qt.UserRole) for i in range(self.count())]

    def _emit_selected(self, current, _previous):
        if current:
            self.chapter_selected.emit(current.data(Qt.UserRole))

    def _emit_order(self, *_args):
        self.reordered.emit(self.ordered_ids())
