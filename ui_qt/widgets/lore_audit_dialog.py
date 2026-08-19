"""Dialog: lore re-audit results with optional auto-fix."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QPushButton, QComboBox, QMessageBox,
)

from src import lore_audit


class LoreAuditDialog(QDialog):
    def __init__(self, parent, app, issues: list[lore_audit.AuditIssue]):
        super().__init__(parent)
        self.app = app
        self._issues = list(issues)
        self.setWindowTitle("Lore re-audit")
        self.resize(560, 420)

        layout = QVBoxLayout(self)
        fixable = lore_audit.fixable_issues(self._issues)
        n_err = sum(1 for i in self._issues if i.severity == "error")
        n_warn = sum(1 for i in self._issues if i.severity == "warning")
        layout.addWidget(QLabel(
            f"{len(self._issues)} issue(s) — {n_err} errors, {n_warn} warnings. "
            f"{len(fixable)} can be fixed automatically."))

        row = QHBoxLayout()
        self.filter_combo = QComboBox()
        self.filter_combo.addItems(["All", "Fixable only", "Errors", "Warnings"])
        self.filter_combo.currentIndexChanged.connect(self._populate)
        row.addWidget(QLabel("Show:"))
        row.addWidget(self.filter_combo)
        row.addStretch()
        layout.addLayout(row)

        self.issue_list = QListWidget()
        self.issue_list.itemDoubleClicked.connect(self._jump)
        layout.addWidget(self.issue_list, 1)

        btn_row = QHBoxLayout()
        self.fix_btn = QPushButton(f"Apply fixes ({len(fixable)})")
        self.fix_btn.setEnabled(bool(fixable))
        self.fix_btn.clicked.connect(self._apply_fixes)
        btn_row.addWidget(self.fix_btn)
        rerun = QPushButton("Re-audit")
        rerun.setProperty("secondary", True)
        rerun.clicked.connect(self._rerun)
        btn_row.addWidget(rerun)
        btn_row.addStretch()
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

        self._populate()

    @property
    def issues(self) -> list[lore_audit.AuditIssue]:
        return self._issues

    def _filtered(self) -> list[lore_audit.AuditIssue]:
        mode = self.filter_combo.currentText()
        if mode == "Fixable only":
            return lore_audit.fixable_issues(self._issues)
        if mode == "Errors":
            return [i for i in self._issues if i.severity == "error"]
        if mode == "Warnings":
            return [i for i in self._issues if i.severity == "warning"]
        return self._issues

    def _populate(self):
        self.issue_list.clear()
        for issue in self._filtered():
            fix_tag = " [fix]" if issue.fix_action else ""
            text = f"[{issue.severity.upper()}]{fix_tag} {issue.message}"
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, issue)
            tip = issue.fix_detail or issue.fix_hint
            if tip:
                item.setToolTip(tip)
            self.issue_list.addItem(item)

    def _jump(self, item: QListWidgetItem):
        issue = item.data(Qt.ItemDataRole.UserRole)
        if issue and issue.entry_id:
            self.app.open_lore_entry(issue.entry_id)

    def _apply_fixes(self):
        paths = self.app.engine.paths
        if not paths:
            return
        to_fix = lore_audit.fixable_issues(self._issues)
        if not to_fix:
            return
        preview = "\n".join(
            f"• {i.message} → {i.fix_detail or i.fix_action}"
            for i in to_fix[:15])
        if len(to_fix) > 15:
            preview += f"\n… and {len(to_fix) - 15} more"
        ans = QMessageBox.question(
            self, "Apply lore fixes",
            f"Apply {len(to_fix)} automatic fix(es)?\n\n{preview}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if ans != QMessageBox.StandardButton.Yes:
            return
        report = lore_audit.apply_fixes(paths, to_fix)
        self.app.show_toast(
            f"Applied {report.applied} fix(es), skipped {report.skipped}.")
        self.app.refresh_canon_panels()
        self._rerun(silent=True)

    def _rerun(self, silent: bool = False):
        paths = self.app.engine.paths
        if not paths:
            return
        orphan = self.app.settings.get("lore.audit_orphan_scan", True)
        self._issues = lore_audit.audit_lore(paths, orphan_scan=orphan)
        fixable = lore_audit.fixable_issues(self._issues)
        self.fix_btn.setText(f"Apply fixes ({len(fixable)})")
        self.fix_btn.setEnabled(bool(fixable))
        self._populate()
        if not silent:
            n_err = sum(1 for i in self._issues if i.severity == "error")
            n_warn = sum(1 for i in self._issues if i.severity == "warning")
            self.app.show_toast(
                f"Re-audit: {len(self._issues)} issue(s) "
                f"({n_err} errors, {n_warn} warnings, {len(fixable)} fixable)")


def run_lore_audit_dialog(parent, app) -> list[lore_audit.AuditIssue]:
    paths = app.engine.paths
    if not paths:
        app.show_toast("No project loaded.", error=True)
        return []
    orphan = app.settings.get("lore.audit_orphan_scan", True)
    issues = lore_audit.audit_lore(paths, orphan_scan=orphan)
    dlg = LoreAuditDialog(parent, app, issues)
    dlg.exec()
    return dlg.issues
