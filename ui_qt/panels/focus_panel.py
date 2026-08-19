"""Focus panel — Quick Add, Parking Lot, Canon Audit, Pre-Flight."""

from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QTabWidget, QWidget, QPlainTextEdit,
    QPushButton, QLabel, QComboBox, QFormLayout, QListWidget, QListWidgetItem,
    QGroupBox, QCheckBox,
)

from src import lore_types, lore_quick_add, lore_audit, lore_migrate
from ui_qt.panels.base import BasePanel
from ui_qt.widgets.lore_audit_dialog import run_lore_audit_dialog


def _parking_lot_path(paths) -> str | None:
    if not paths:
        return None
    return os.path.join(paths["root"], "parking_lot.txt")


class FocusPanel(BasePanel):
    title = "Focus"

    def __init__(self, app, parent=None):
        super().__init__(app, parent)
        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)
        self._build_quick_add_tab()
        self._build_parking_tab()
        self._build_audit_tab()
        self._build_preflight_tab()

    def _paths(self):
        return self.app.engine.paths

    def _build_quick_add_tab(self):
        tab = QWidget()
        v = QVBoxLayout(tab)
        v.addWidget(QLabel(
            "One entry per line. Prefix with type (creature:, place:, faction:, …) "
            "or use Name: notes. Pipe fields: creature: Smaug | type: dragon | notes: …"))
        self.quick_input = QPlainTextEdit()
        self.quick_input.setPlaceholderText(
            "# Examples:\n"
            "Alice: brave scout from the marshes\n"
            "creature: Ash Wyrm | type: dragon | notes: ancient hoard guardian\n"
            "place: The Undercity | territory: coastal ruins\n"
            "world: Old Mill: abandoned windmill on the ridge")
        v.addWidget(self.quick_input, 1)

        form = QFormLayout()
        self.quick_default_type = QComboBox()
        for key, label, _bucket in lore_types.ENTRY_TYPES:
            self.quick_default_type.addItem(label, key)
        form.addRow("Default type (no prefix)", self.quick_default_type)
        self.quick_mode = QComboBox()
        self.quick_mode.addItem("Add new entries", "add")
        self.quick_mode.addItem("Upsert by name", "upsert")
        form.addRow("Import mode", self.quick_mode)
        v.addLayout(form)

        row = QHBoxLayout()
        add_btn = QPushButton("Add to Lorebook")
        add_btn.clicked.connect(self._run_quick_add)
        row.addWidget(add_btn)
        row.addStretch()
        self.quick_status = QLabel("")
        self.quick_status.setProperty("muted", True)
        row.addWidget(self.quick_status)
        v.addLayout(row)
        self.tabs.addTab(tab, "Quick Add")

    def _run_quick_add(self):
        paths = self._paths()
        if not paths:
            self.app.show_toast("No project loaded.", error=True)
            return
        text = self.quick_input.toPlainText()
        default = self.quick_default_type.currentData() or "character"
        mode = self.quick_mode.currentData() or "add"
        capture = self.app.settings.get("context.capture_bible_mode", "empty")
        summary = lore_quick_add.apply_quick_add(
            paths["lore"], text, default_type=default, mode=mode, capture_mode=capture)
        parts = []
        if summary["added"]:
            parts.append(f"{summary['added']} added")
        if summary["updated"]:
            parts.append(f"{summary['updated']} updated")
        if summary["skipped"]:
            parts.append(f"{summary['skipped']} skipped")
        msg = ", ".join(parts) if parts else "No lines parsed"
        self.quick_status.setText(msg)
        self.app.show_toast(f"Quick Add: {msg}")
        self.app.refresh_canon_panels()

    def _build_parking_tab(self):
        tab = QWidget()
        v = QVBoxLayout(tab)
        v.addWidget(QLabel(
            "Research parking lot — not canon. Capture never reads this pad. "
            "Move facts into Lorebook or Story Bible when you are ready."))
        self.parking_edit = QPlainTextEdit()
        v.addWidget(self.parking_edit, 1)
        save_btn = QPushButton("Save parking lot")
        save_btn.clicked.connect(self._save_parking)
        v.addWidget(save_btn)
        self.tabs.addTab(tab, "Research (not canon)")

    def _load_parking(self):
        path = _parking_lot_path(self._paths())
        if not path:
            self.parking_edit.clear()
            return
        try:
            with open(path, "r", encoding="utf-8") as fh:
                self.parking_edit.setPlainText(fh.read())
        except OSError:
            self.parking_edit.clear()

    def _save_parking(self):
        path = _parking_lot_path(self._paths())
        if not path:
            return
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(self.parking_edit.toPlainText())
        self.app.show_toast("Parking lot saved.")

    def _build_audit_tab(self):
        tab = QWidget()
        v = QVBoxLayout(tab)
        row = QHBoxLayout()
        run_btn = QPushButton("Re-audit…")
        run_btn.setToolTip("Read lore, check entries make sense, offer to fix")
        run_btn.clicked.connect(self._run_audit)
        row.addWidget(run_btn)
        self.audit_filter = QComboBox()
        self.audit_filter.addItems(["All", "Errors", "Warnings", "Info"])
        self.audit_filter.currentIndexChanged.connect(self._filter_audit_list)
        row.addWidget(QLabel("Show:"))
        row.addWidget(self.audit_filter)
        row.addStretch()
        migrate_btn = QPushButton("Preview legacy upgrade…")
        migrate_btn.setProperty("secondary", True)
        migrate_btn.clicked.connect(self._preview_migrate)
        row.addWidget(migrate_btn)
        v.addLayout(row)

        self.audit_list = QListWidget()
        self.audit_list.itemDoubleClicked.connect(self._jump_to_audit_entry)
        v.addWidget(self.audit_list, 1)
        self._audit_issues = []
        self.tabs.addTab(tab, "Canon Audit")

    def _run_audit(self):
        paths = self._paths()
        if not paths:
            return
        self._audit_issues = run_lore_audit_dialog(self, self.app)
        self._populate_audit_list()
        self.app.refresh_canon_panels()

    def _populate_audit_list(self):
        filt = self.audit_filter.currentText().lower()
        self.audit_list.clear()
        for issue in self._audit_issues:
            if filt == "errors" and issue.severity != "error":
                continue
            if filt == "warnings" and issue.severity != "warning":
                continue
            if filt == "info" and issue.severity != "info":
                continue
            text = f"[{issue.severity.upper()}]"
            if issue.fix_action:
                text += " [fix]"
            text += f" {issue.message}"
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, issue.entry_id)
            item.setToolTip(issue.fix_hint or "")
            self.audit_list.addItem(item)

    def _filter_audit_list(self):
        if self._audit_issues:
            self._populate_audit_list()

    def _jump_to_audit_entry(self, item: QListWidgetItem):
        eid = item.data(Qt.ItemDataRole.UserRole)
        if eid:
            self.app.open_lore_entry(eid)

    def _preview_migrate(self):
        paths = self._paths()
        if not paths:
            return
        report = lore_migrate.migrate_lore(paths, dry_run=True)
        if report.changed == 0:
            self.app.show_toast("No legacy entries need upgrading.")
            return
        from PySide6.QtWidgets import QMessageBox
        preview = "\n".join(report.details[:20])
        if len(report.details) > 20:
            preview += f"\n… and {len(report.details) - 20} more"
        ans = QMessageBox.question(
            self, "Upgrade legacy entries",
            f"{report.changed} of {report.total} entries would be updated.\n\n{preview}\n\nApply?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if ans == QMessageBox.StandardButton.Yes:
            lore_migrate.migrate_lore(paths, dry_run=False)
            self.app.show_toast(f"Upgraded {report.changed} lore entries.")
            self.app.refresh_canon_panels()
            self._run_audit()

    def _build_preflight_tab(self):
        tab = QWidget()
        v = QVBoxLayout(tab)
        self.preflight_list = QListWidget()
        v.addWidget(self.preflight_list, 1)
        row = QHBoxLayout()
        recheck = QPushButton("Re-check readiness")
        recheck.clicked.connect(self._run_preflight)
        row.addWidget(recheck)
        row.addStretch()
        v.addLayout(row)
        self.tabs.addTab(tab, "Pre-Flight")

    def _run_preflight(self):
        paths = self._paths()
        self.preflight_list.clear()
        rows = lore_audit.preflight_checklist(paths, self.app.settings)
        for label, ok, detail in rows:
            mark = "✓" if ok else "✗"
            item = QListWidgetItem(f"{mark}  {label} — {detail}")
            if not ok:
                item.setForeground(Qt.GlobalColor.yellow)
            self.preflight_list.addItem(item)

    def on_show(self):
        self._load_parking()
        if self.app.settings.get("lore.audit_on_project_open", False):
            self._run_audit()
        self._run_preflight()

    def on_project_change(self):
        self._load_parking()
        self._audit_issues = []
        self.audit_list.clear()
        self._run_preflight()
