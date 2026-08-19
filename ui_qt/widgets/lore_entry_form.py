"""Dynamic lore entry editor — fields change by entry type (person, place, creature…)."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QFormLayout, QLineEdit, QPlainTextEdit,
    QComboBox, QCheckBox, QHBoxLayout, QSpinBox, QLabel, QScrollArea,
)

from src import lore_types


def _comma_join(value) -> str:
    if isinstance(value, list):
        return ", ".join(str(v) for v in value if v)
    return str(value or "")


def _comma_split(text: str) -> list[str]:
    return [p.strip() for p in (text or "").split(",") if p.strip()]


class LoreEntryForm(QWidget):
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._field_widgets: dict[str, QLineEdit | QPlainTextEdit] = {}
        self._building = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        inner = QWidget()
        self._form = QFormLayout(inner)
        self._form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)

        self.entry_type = QComboBox()
        for key, label, _bucket in lore_types.ENTRY_TYPES:
            self.entry_type.addItem(label, key)
        self.entry_type.currentIndexChanged.connect(self._on_type_changed)

        self.name = QLineEdit()
        self.name.textChanged.connect(self._emit_changed)

        self.pinned = QCheckBox("Pinned")
        self.always_include = QCheckBox("Always include in SETTING")
        self.priority = QSpinBox()
        self.priority.setRange(0, 10)
        self.priority.setToolTip("Higher = more likely in context when space is tight")

        self._form.addRow("Entry type", self.entry_type)
        self._form.addRow("Name", self.name)

        flag_row = QHBoxLayout()
        flag_row.addWidget(self.pinned)
        flag_row.addWidget(self.always_include)
        flag_row.addStretch()
        self._form.addRow("Flags", flag_row)
        self._form.addRow("Priority", self.priority)

        self._dynamic_start = self._form.rowCount()
        scroll.setWidget(inner)
        outer.addWidget(scroll)

        self._on_type_changed()

    def _emit_changed(self, *_args):
        if not self._building:
            self.changed.emit()

    def _clear_dynamic_fields(self):
        while self._form.rowCount() > self._dynamic_start:
            self._form.removeRow(self._dynamic_start)
        self._field_widgets.clear()

    def _on_type_changed(self):
        if self._building:
            return
        et = self.entry_type.currentData()
        self._rebuild_fields(et)
        self._emit_changed()

    def _rebuild_fields(self, entry_type: str):
        self._building = True
        self._clear_dynamic_fields()
        for key, label, multiline in lore_types.fields_for_entry_type(entry_type):
            if multiline:
                w = QPlainTextEdit()
                w.setMaximumHeight(72)
                w.textChanged.connect(self._emit_changed)
            else:
                w = QLineEdit()
                w.textChanged.connect(self._emit_changed)
            self._field_widgets[key] = w
            self._form.addRow(label, w)
        self._building = False

    def load_entry(self, entry: dict | None):
        self._building = True
        entry = entry or {}
        et = entry.get("entryType") or "character"
        idx = self.entry_type.findData(et)
        if idx >= 0:
            self.entry_type.setCurrentIndex(idx)
        self._rebuild_fields(et)
        self.name.setText(entry.get("name") or "")
        self.pinned.setChecked(bool(entry.get("pinned")))
        self.always_include.setChecked(bool(entry.get("alwaysInclude")))
        try:
            self.priority.setValue(int(entry.get("priority") or 0))
        except (TypeError, ValueError):
            self.priority.setValue(0)
        for key, widget in self._field_widgets.items():
            val = entry.get(key)
            if key in ("keywords", "aliases", "tags"):
                text = _comma_join(val)
            elif key == "relationships":
                text = lore_types.format_relationships(val)
            else:
                text = str(val or "")
            if isinstance(widget, QPlainTextEdit):
                widget.setPlainText(text)
            else:
                widget.setText(text)
        self._building = False

    def to_entry_dict(self, base: dict | None = None) -> dict:
        base = dict(base or {})
        et = self.entry_type.currentData() or "character"
        storage = lore_types.storage_for_entry_type(et)
        out = {
            **base,
            "name": self.name.text().strip() or "Untitled",
            "entryType": et,
            "type": storage,
            "pinned": self.pinned.isChecked(),
            "alwaysInclude": self.always_include.isChecked(),
            "priority": self.priority.value(),
        }
        for key, widget in self._field_widgets.items():
            if isinstance(widget, QPlainTextEdit):
                val = widget.toPlainText().strip()
            else:
                val = widget.text().strip()
            if key in ("keywords", "aliases", "tags"):
                out[key] = _comma_split(val)
            elif key == "relationships":
                out[key] = lore_types.parse_relationships(val)
            else:
                out[key] = val
        if out.get("notes"):
            out["description"] = out["notes"]
        return out

    def wire_generate_menu(self, callback):
        """Right-click Generate on all multiline fields."""
        for key, widget in self._field_widgets.items():
            if isinstance(widget, QPlainTextEdit):
                callback(widget, f"Lore — {key}")
