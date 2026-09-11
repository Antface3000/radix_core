"""Preview and apply canon fields extracted from manuscript chapters."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QPushButton, QStackedWidget, QTreeWidget, QTreeWidgetItem,
    QVBoxLayout, QWidget,
)

from src import chapters, manuscript_fill
from ui_qt.widgets.themed_dialog import ThemedDialog
from ui_qt.workers import ManuscriptFillWorker

_ROLE_BIBLE = "bible"
_ROLE_WORLD = "world"
_ROLE_CHAPTER = "chapter"
_ROLE_OUTLINE = "outline"
_ROLE_LORE = "lore"


class ManuscriptFillDialog(ThemedDialog):
    def __init__(self, parent, app, *, prefer_id: str | None = None):
        super().__init__(parent)
        self.app = app
        self.prefer_id = prefer_id
        self._worker: ManuscriptFillWorker | None = None
        self._payload = manuscript_fill.empty_payload()
        self._accepted: dict | None = None

        self.setWindowTitle("Fill from chapters")
        self.resize(620, 560)

        root = QVBoxLayout(self)
        self.stack = QStackedWidget()
        root.addWidget(self.stack, 1)
        self._build_pick()
        self._build_busy()
        self._build_preview()

    def result_payload(self) -> dict | None:
        return self._accepted

    def selected_chapter_id(self) -> str | None:
        ids = self._checked_chapter_ids()
        if self.prefer_id and self.prefer_id in ids:
            return self.prefer_id
        return ids[0] if len(ids) == 1 else self.prefer_id

    def replace_mode(self) -> bool:
        return self.replace_cb.isChecked()

    def _build_pick(self):
        page = QWidget()
        v = QVBoxLayout(page)
        v.addWidget(QLabel(
            "Read one or more chapters and propose Story Bible, World State, "
            "outline, chapter meta, and lore fields the text can support. "
            "Empty fields are filled; Replace overwrites existing text."))
        v.addWidget(QLabel("Chapters"))
        self.chapter_list = QListWidget()
        paths = self.app.engine.paths
        if paths:
            for ch in chapters.list_chapters(paths["chapters"]):
                item = QListWidgetItem(ch["name"])
                item.setData(Qt.ItemDataRole.UserRole, ch["id"])
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                checked = ch["id"] == self.prefer_id if self.prefer_id else False
                item.setCheckState(
                    Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
                self.chapter_list.addItem(item)
        if self.chapter_list.count() and not self.prefer_id:
            first = self.chapter_list.item(0)
            first.setCheckState(Qt.CheckState.Checked)
        v.addWidget(self.chapter_list, 1)
        sel = QHBoxLayout()
        current_btn = QPushButton("Current")
        current_btn.setProperty("secondary", True)
        current_btn.clicked.connect(self._select_current)
        all_btn = QPushButton("All")
        all_btn.setProperty("secondary", True)
        all_btn.clicked.connect(lambda: self._set_all(True))
        none_btn = QPushButton("None")
        none_btn.setProperty("secondary", True)
        none_btn.clicked.connect(lambda: self._set_all(False))
        sel.addWidget(current_btn)
        sel.addWidget(all_btn)
        sel.addWidget(none_btn)
        sel.addStretch()
        v.addLayout(sel)
        row = QHBoxLayout()
        row.addStretch()
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        run = QPushButton("Audit chapters")
        run.setDefault(True)
        run.clicked.connect(self._start)
        row.addWidget(cancel)
        row.addWidget(run)
        v.addLayout(row)
        self.stack.addWidget(page)

    def _build_busy(self):
        page = QWidget()
        v = QVBoxLayout(page)
        self.busy_label = QLabel("Reading the manuscript…")
        self.busy_label.setWordWrap(True)
        v.addWidget(self.busy_label)
        v.addStretch()
        row = QHBoxLayout()
        row.addStretch()
        stop = QPushButton("Stop")
        stop.setProperty("danger", True)
        stop.clicked.connect(lambda: self.app.engine.request_cancel())
        row.addWidget(stop)
        v.addLayout(row)
        self.stack.addWidget(page)

    def _build_preview(self):
        page = QWidget()
        v = QVBoxLayout(page)
        v.addWidget(QLabel("Uncheck anything you do not want applied."))
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Field", "Proposed value"])
        self.tree.setColumnWidth(0, 220)
        self.tree.itemChanged.connect(self._on_tree_item_changed)
        v.addWidget(self.tree, 1)
        self.replace_cb = QCheckBox(
            "Replace existing fields (otherwise fill blanks only)")
        v.addWidget(self.replace_cb)
        row = QHBoxLayout()
        back = QPushButton("Back")
        back.setProperty("secondary", True)
        back.clicked.connect(lambda: self.stack.setCurrentIndex(0))
        row.addWidget(back)
        row.addStretch()
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        apply_btn = QPushButton("Apply")
        apply_btn.setDefault(True)
        apply_btn.clicked.connect(self._apply)
        row.addWidget(cancel)
        row.addWidget(apply_btn)
        v.addLayout(row)
        self.stack.addWidget(page)

    def _set_all(self, checked: bool):
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        for i in range(self.chapter_list.count()):
            self.chapter_list.item(i).setCheckState(state)

    def _select_current(self):
        self._set_all(False)
        if not self.prefer_id:
            if self.chapter_list.count():
                self.chapter_list.item(0).setCheckState(Qt.CheckState.Checked)
            return
        for i in range(self.chapter_list.count()):
            item = self.chapter_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == self.prefer_id:
                item.setCheckState(Qt.CheckState.Checked)
                return

    def _checked_chapter_ids(self) -> list[str]:
        ids = []
        for i in range(self.chapter_list.count()):
            item = self.chapter_list.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                cid = item.data(Qt.ItemDataRole.UserRole)
                if cid:
                    ids.append(cid)
        return ids

    def _start(self):
        ids = self._checked_chapter_ids()
        if not ids:
            self.app.show_toast("Select at least one chapter.", error=True)
            return
        self.app.engine.clear_cancel()
        self.busy_label.setText("Extracting definite fields from the manuscript…")
        self.stack.setCurrentIndex(1)
        self._worker = ManuscriptFillWorker(self.app, ids, prefer_id=self.prefer_id)
        self._worker.finished_ok.connect(self._on_done)
        self._worker.start()

    def _on_done(self, cancelled: bool, payload):
        self._worker = None
        if not self.isVisible():
            return
        if cancelled:
            self.stack.setCurrentIndex(0)
            return
        self._payload = payload or manuscript_fill.empty_payload()
        if not manuscript_fill.payload_has_proposals(self._payload):
            self.app.show_toast(
                "Nothing definite enough to fill. Add more chapter text or try more chapters.",
                error=True)
            self.stack.setCurrentIndex(0)
            return
        self._fill_tree()
        self.stack.setCurrentIndex(2)

    def _add_section(self, title: str, role: str, fields: dict, extra=None):
        if not fields:
            return
        parent = QTreeWidgetItem([title, ""])
        parent.setFlags(
            parent.flags() | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsAutoTristate)
        parent.setCheckState(0, Qt.CheckState.Checked)
        parent.setData(0, Qt.ItemDataRole.UserRole, (role, extra))
        for key, value in fields.items():
            label = manuscript_fill.FIELD_LABELS.get(key, key)
            shown = manuscript_fill.format_value(value)
            if len(shown) > 240:
                shown = shown[:237] + "…"
            child = QTreeWidgetItem([label, shown])
            child.setFlags(child.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            child.setCheckState(0, Qt.CheckState.Checked)
            child.setData(0, Qt.ItemDataRole.UserRole, (role, key, extra))
            child.setToolTip(1, manuscript_fill.format_value(value))
            parent.addChild(child)
        self.tree.addTopLevelItem(parent)
        parent.setExpanded(True)

    def _fill_tree(self):
        self.tree.blockSignals(True)
        self.tree.clear()
        p = self._payload
        self._add_section("Story Bible", _ROLE_BIBLE, p.get("bible") or {})
        self._add_section("World State", _ROLE_WORLD, p.get("world") or {})
        cid = self.selected_chapter_id()
        name = ""
        paths = self.app.engine.paths
        if paths and cid:
            try:
                name = chapters.read(paths["chapters"], cid).get("name") or ""
            except ValueError:
                name = ""
        suffix = f" ({name})" if name else ""
        self._add_section("Chapter meta" + suffix, _ROLE_CHAPTER, p.get("chapter") or {})
        self._add_section("Outline" + suffix, _ROLE_OUTLINE, p.get("outline") or {})
        for entry in p.get("lore") or []:
            et = entry.get("entryType") or "character"
            title = f"Lore — {entry.get('name')} [{et}]"
            fields = {k: v for k, v in entry.items() if k not in ("name", "entryType")}
            if not fields and entry.get("name"):
                fields = {"keywords": [entry.get("name")]}
            self._add_section(title, _ROLE_LORE, fields, extra=entry.get("name"))
        self.tree.blockSignals(False)

    def _on_tree_item_changed(self, item, column):
        if column != 0:
            return
        self.tree.blockSignals(True)
        state = item.checkState(0)
        for i in range(item.childCount()):
            item.child(i).setCheckState(0, state)
        self.tree.blockSignals(False)

    def _checked_payload(self) -> dict:
        out = manuscript_fill.empty_payload()
        src = self._payload
        lore_by_name = {e.get("name"): dict(e) for e in (src.get("lore") or [])}
        for i in range(self.tree.topLevelItemCount()):
            parent = self.tree.topLevelItem(i)
            role_data = parent.data(0, Qt.ItemDataRole.UserRole) or (None, None)
            role = role_data[0]
            extra = role_data[1] if len(role_data) > 1 else None
            for j in range(parent.childCount()):
                child = parent.child(j)
                if child.checkState(0) != Qt.CheckState.Checked:
                    continue
                data = child.data(0, Qt.ItemDataRole.UserRole)
                if not data:
                    continue
                _role, key = data[0], data[1]
                if _role == _ROLE_LORE:
                    name = extra or (data[2] if len(data) > 2 else None)
                    base = lore_by_name.get(name)
                    if not base:
                        continue
                    bucket = next((e for e in out["lore"] if e.get("name") == name), None)
                    if bucket is None:
                        bucket = {"name": base.get("name"), "entryType": base.get("entryType")}
                        out["lore"].append(bucket)
                    if key in base:
                        bucket[key] = base[key]
                else:
                    section = src.get(_role) or {}
                    if key in section:
                        out[_role][key] = section[key]
        return out

    def _apply(self):
        self._accepted = self._checked_payload()
        if not manuscript_fill.payload_has_proposals(self._accepted):
            self.app.show_toast("Nothing selected to apply.", error=True)
            return
        self.accept()

    def reject(self):
        if self._worker and self._worker.isRunning():
            self.app.engine.request_cancel()
        super().reject()


def run_manuscript_fill(parent, app, *, prefer_id: str | None = None) -> bool:
    """Open the dialog, apply to disk, refresh open panels. True if applied."""
    from PySide6.QtWidgets import QDialog
    from src.plugins import is_enabled

    if not app.engine.paths:
        app.show_toast("Open a project first.", error=True)
        return False
    if not is_enabled(app.settings, "llm"):
        app.show_toast("Enable the Local LLM pack in Add Ons.", error=True)
        return False
    bible = app._panels.get("Story Bible") if hasattr(app, "_panels") else None
    if bible and hasattr(bible, "flush_if_dirty"):
        bible.flush_if_dirty()
    if not prefer_id:
        editor = getattr(app, "editor", None)
        prefer_id = getattr(editor, "_chapter_id", None) if editor else None
    dlg = ManuscriptFillDialog(parent, app, prefer_id=prefer_id)
    if dlg.exec() != QDialog.DialogCode.Accepted:
        return False
    payload = dlg.result_payload() or manuscript_fill.empty_payload()
    counts = manuscript_fill.apply_payload(
        app.engine.paths, payload, replace=dlg.replace_mode(),
        chapter_id=dlg.selected_chapter_id())
    if bible and hasattr(bible, "reload"):
        bible.reload()
    editor = getattr(app, "editor", None)
    if editor and hasattr(editor, "refresh_chapters"):
        editor.refresh_chapters()
    draft = app._panels.get("Draft") if hasattr(app, "_panels") else None
    if draft and hasattr(draft, "on_show"):
        draft.on_show()
        if hasattr(draft, "_prefill_craft"):
            draft._prefill_craft(force=True)
    parts = [f"{n} {k}" for k, n in counts.items() if n]
    app.show_toast("Filled from chapters: " + (", ".join(parts) if parts else "no changes"))
    return True
