"""Studio dialogs: snapshots, project search, chapter notes."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QPushButton, QLineEdit, QLabel, QPlainTextEdit, QCheckBox, QMessageBox,
)

from src import snapshots, project_search, chapter_notes, chapters


class SnapshotDialog(QDialog):
    def __init__(self, app, chapter_id: str, parent=None):
        super().__init__(parent)
        self.app = app
        self.chapter_id = chapter_id
        self.setWindowTitle("Chapter snapshots")
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Timed copies of this chapter. Restore replaces the buffer."))
        self.list = QListWidget()
        layout.addWidget(self.list, 1)
        row = QHBoxLayout()
        now = QPushButton("Snapshot now")
        now.clicked.connect(self._take)
        row.addWidget(now)
        restore = QPushButton("Restore selected")
        restore.clicked.connect(self._restore)
        row.addWidget(restore)
        layout.addLayout(row)
        self._reload()

    def _reload(self):
        self.list.clear()
        paths = self.app.engine.paths
        if not paths or not self.chapter_id:
            return
        for item in snapshots.list_snapshots(paths, self.chapter_id):
            label = f"{item.get('stamp')}  ({item.get('reason', 'auto')})"
            row = QListWidgetItem(label)
            row.setData(256, item.get("stamp"))
            self.list.addItem(row)

    def _take(self):
        editor = self.app.editor
        if not editor or not self.chapter_id:
            return
        snapshots.take_snapshot(
            self.app.engine.paths, self.chapter_id,
            editor.editor.toPlainText(), reason="manual")
        self._reload()

    def _restore(self):
        item = self.list.currentItem()
        if not item:
            return
        stamp = item.data(256)
        text = snapshots.read_snapshot(
            self.app.engine.paths, self.chapter_id, stamp)
        self.app.editor.editor.setPlainText(text)
        self.app.editor._dirty = True
        self.app.show_toast("Snapshot restored.")
        self.accept()


class ProjectSearchDialog(QDialog):
    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        self.setWindowTitle("Project search")
        self.resize(640, 420)
        layout = QVBoxLayout(self)
        self.query = QLineEdit()
        self.query.setPlaceholderText("Search chapters, lore, and Story Bible…")
        self.query.returnPressed.connect(self._search)
        layout.addWidget(self.query)
        opts = QHBoxLayout()
        self.case = QCheckBox("Match case")
        self.regex = QCheckBox("Regex")
        opts.addWidget(self.case)
        opts.addWidget(self.regex)
        opts.addStretch()
        go = QPushButton("Search")
        go.clicked.connect(self._search)
        opts.addWidget(go)
        layout.addLayout(opts)
        replace_row = QHBoxLayout()
        self.repl = QLineEdit()
        self.repl.setPlaceholderText("Replace in chapters only")
        replace_row.addWidget(self.repl)
        do_repl = QPushButton("Replace all in chapters")
        do_repl.clicked.connect(self._replace)
        replace_row.addWidget(do_repl)
        layout.addLayout(replace_row)
        self.hits = QListWidget()
        self.hits.itemDoubleClicked.connect(self._jump)
        layout.addWidget(self.hits, 1)

    def _search(self):
        self.hits.clear()
        paths = self.app.engine.paths
        if not paths:
            return
        for hit in project_search.search(
                paths, self.query.text(),
                case=self.case.isChecked(), regex=self.regex.isChecked()):
            label = f"[{hit['kind']}] {hit.get('name')} — {hit.get('snippet', '')[:80]}"
            item = QListWidgetItem(label)
            item.setData(256, hit)
            self.hits.addItem(item)

    def _replace(self):
        paths = self.app.engine.paths
        if not paths or not self.query.text():
            return
        n = project_search.replace_in_chapters(
            paths, self.query.text(), self.repl.text(),
            case=self.case.isChecked(), regex=self.regex.isChecked())
        self.app.editor.refresh_chapters()
        self.app.show_toast(f"Replaced {n} match(es) in chapters.")
        self._search()

    def _jump(self, item):
        hit = item.data(256) or {}
        if hit.get("kind") == "chapter" and self.app.editor:
            self.app.editor._select_chapter_id(hit.get("id"))
        elif hit.get("kind") == "lore":
            self.app.open_lore_entry(hit.get("id") or "")
        elif hit.get("kind") == "bible":
            self.app.show_feature("Story Bible")
        self.accept()


class NotesDialog(QDialog):
    def __init__(self, app, chapter_id: str, parent=None):
        super().__init__(parent)
        self.app = app
        self.chapter_id = chapter_id
        self.setWindowTitle("Fix-later notes")
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            "These notes never go to Write/Chat unless Settings → include notes in AI."))
        self.list = QListWidget()
        layout.addWidget(self.list, 1)
        self.entry = QPlainTextEdit()
        self.entry.setMaximumHeight(80)
        self.entry.setPlaceholderText("New note…")
        layout.addWidget(self.entry)
        row = QHBoxLayout()
        add = QPushButton("Add")
        add.clicked.connect(self._add)
        row.addWidget(add)
        done = QPushButton("Mark done")
        done.clicked.connect(self._done)
        row.addWidget(done)
        layout.addLayout(row)
        self._reload()

    def _reload(self):
        self.list.clear()
        paths = self.app.engine.paths
        if not paths or not self.chapter_id:
            return
        for n in chapter_notes.load(paths, self.chapter_id):
            flag = n.get("status", "open")
            item = QListWidgetItem(f"[{flag}] {n.get('text', '')}")
            item.setData(256, n)
            self.list.addItem(item)

    def _add(self):
        text = self.entry.toPlainText().strip()
        if not text or not self.chapter_id:
            return
        editor = self.app.editor.editor
        cur = editor.textCursor()
        chapter_notes.add(
            self.app.engine.paths, self.chapter_id, text,
            offset=cur.selectionStart(), length=max(0, cur.selectionEnd() - cur.selectionStart()))
        self.entry.clear()
        self._reload()

    def _done(self):
        item = self.list.currentItem()
        if not item:
            return
        note = dict(item.data(256) or {})
        notes = chapter_notes.load(self.app.engine.paths, self.chapter_id)
        for n in notes:
            if n.get("id") == note.get("id"):
                n["status"] = "done"
        chapter_notes.save(self.app.engine.paths, self.chapter_id, notes)
        self._reload()
