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
    typeChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._field_widgets: dict[str, QLineEdit | QPlainTextEdit] = {}
        self._building = False
        self._stash: dict = {}
        self._generate_cb = None

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
        self._stash_widgets()
        et = self.entry_type.currentData()
        self._rebuild_fields(et)
        self._apply_stash()
        self._emit_changed()
        self.typeChanged.emit()

    def _rebuild_fields(self, entry_type: str):
        was_building = self._building
        self._building = True
        self._clear_dynamic_fields()
        for key, label, multiline in lore_types.fields_for_entry_type(entry_type):
            if multiline:
                w = QPlainTextEdit()
                w.setMinimumHeight(64)
                w.setMaximumHeight(140)
                w.textChanged.connect(self._emit_changed)
            else:
                w = QLineEdit()
                w.textChanged.connect(self._emit_changed)
            self._field_widgets[key] = w
            self._form.addRow(label, w)
        self._apply_generate_menu()
        self._building = was_building

    def _read_widget(self, key: str, widget) -> object:
        if isinstance(widget, QPlainTextEdit):
            val = widget.toPlainText().strip()
        else:
            val = widget.text().strip()
        if key in ("keywords", "aliases", "tags", "groups"):
            return _comma_split(val)
        if key == "relationships":
            return lore_types.parse_relationships(val)
        return val

    def _write_widget(self, key: str, widget, val) -> None:
        if key in ("keywords", "aliases", "tags", "groups"):
            text = _comma_join(val)
        elif key == "relationships":
            text = lore_types.format_relationships(val)
        else:
            text = str(val or "")
        if isinstance(widget, QPlainTextEdit):
            widget.setPlainText(text)
        else:
            widget.setText(text)

    def _stash_widgets(self):
        for key, widget in self._field_widgets.items():
            self._stash[key] = self._read_widget(key, widget)
        self._stash["name"] = self.name.text().strip()
        self._stash["pinned"] = self.pinned.isChecked()
        self._stash["alwaysInclude"] = self.always_include.isChecked()
        self._stash["priority"] = self.priority.value()
        self._stash["entryType"] = self.entry_type.currentData()

    def _apply_stash(self):
        self._building = True
        self.name.setText(self._stash.get("name") or self.name.text())
        if "pinned" in self._stash:
            self.pinned.setChecked(bool(self._stash.get("pinned")))
        if "alwaysInclude" in self._stash:
            self.always_include.setChecked(bool(self._stash.get("alwaysInclude")))
        try:
            self.priority.setValue(int(self._stash.get("priority") or 0))
        except (TypeError, ValueError):
            pass
        for key, widget in self._field_widgets.items():
            if key in self._stash:
                self._write_widget(key, widget, self._stash.get(key))
        self._building = False

    def load_entry(self, entry: dict | None):
        self._building = True
        entry = entry or {}
        self._stash = dict(entry)
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
            self._write_widget(key, widget, entry.get(key))
        self._building = False

    def to_entry_dict(self, base: dict | None = None) -> dict:
        self._stash_widgets()
        base = dict(base or {})
        out = {**base, **self._stash}
        if base.get("id"):
            out["id"] = base["id"]
        et = self.entry_type.currentData() or "character"
        storage = lore_types.storage_for_entry_type(et)
        out.update({
            "name": self.name.text().strip() or "Untitled",
            "entryType": et,
            "type": storage,
            "pinned": self.pinned.isChecked(),
            "alwaysInclude": self.always_include.isChecked(),
            "priority": self.priority.value(),
        })
        for key, widget in self._field_widgets.items():
            out[key] = self._read_widget(key, widget)
        if out.get("notes"):
            out["description"] = out["notes"]
        return out

    def wire_generate_menu(self, callback):
        """Right-click Generate on all multiline fields."""
        self._generate_cb = callback
        self._apply_generate_menu()

    def _apply_generate_menu(self):
        if not self._generate_cb:
            return
        for key, widget in self._field_widgets.items():
            if isinstance(widget, QPlainTextEdit):
                self._generate_cb(widget, f"Lore — {key}")
