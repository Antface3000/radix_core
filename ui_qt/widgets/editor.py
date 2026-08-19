"""Main manuscript editor with chapters, AI dock, spellcheck, find, and export."""

from __future__ import annotations

import config
from PySide6.QtCore import QEvent, Qt, QTimer, Signal
from PySide6.QtGui import (
    QAction, QColor, QFont, QKeySequence, QShortcut, QTextCharFormat,
    QTextCursor, QTextDocument,
)
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QCheckBox,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from src import chapters, export as export_mod, story_context
from src.plugins import is_enabled
from ui_qt.ambiguity_gate import run_ambiguity_gate
from ui_qt.stream_throttle import StreamThrottler
from ui_qt.widgets.spellcheck import SpellCheckService, SpellReplaceBar, skip_spellcheck
from ui_qt.widgets.binder import BinderWidget
from ui_qt.widgets.activity_indicator import ActivityStatus
from ui_qt.widgets.auto_scroll import make_auto_scroll_checkbox, scroll_to_end
from ui_qt.ai_workflow import EDITOR_AI_SUBTITLE, EDITOR_MODE_TIPS
from ui_qt.workers import EditorAiWorker, EditorPipelineWorker


def _resolve_editor_font_size(settings) -> int:
    raw = settings.get("editor.font_size", config.EDITOR_FONT_SIZE)
    try:
        size = int(raw)
    except (TypeError, ValueError):
        size = config.EDITOR_FONT_SIZE
    return max(8, min(size, 72))


def _resolve_editor_font_family(settings) -> str:
    family = settings.get("editor.font_family", config.EDITOR_FONT_FAMILY)
    return str(family or config.EDITOR_FONT_FAMILY)


class EditorWidget(QWidget):
    word_count_changed = Signal(int, int)

    def __init__(self, app):
        super().__init__()
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.app = app
        self._chapter_id: str | None = None
        self._dirty = False
        self._ai_worker: EditorAiWorker | None = None
        self._ai_buffer = ""
        self._chat_history: list[tuple[str, str]] = []
        self._pending_draft: str | None = None
        self._stage_drafts: list[tuple[str, str]] = []
        self._refine_note = ""
        self._ghost_active = False
        self._ghost_start_cur: QTextCursor | None = None
        self._ghost_end_cur: QTextCursor | None = None
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.timeout.connect(self._autosave)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.toolbar = QToolBar()
        layout.addWidget(self.toolbar)

        self.chapter_combo = QComboBox()
        self.chapter_combo.setMinimumWidth(160)
        self.chapter_combo.currentIndexChanged.connect(self._on_chapter_changed)
        self.toolbar.addWidget(QLabel("Chapter:"))
        self.toolbar.addWidget(self.chapter_combo)

        new_act = QAction("New", self)
        new_act.setToolTip("Create a new chapter")
        new_act.triggered.connect(self._new_chapter)
        self.toolbar.addAction(new_act)

        rename_act = QAction("Rename", self)
        rename_act.setToolTip("Rename the current chapter")
        rename_act.triggered.connect(self._rename_chapter)
        self.toolbar.addAction(rename_act)

        del_act = QAction("Delete", self)
        del_act.setToolTip("Delete the current chapter")
        del_act.triggered.connect(self._delete_chapter)
        self.toolbar.addAction(del_act)

        self.toolbar.addSeparator()
        self.find_entry = QLineEdit()
        self.find_entry.setPlaceholderText("Find...")
        self.find_entry.setMaximumWidth(140)
        self.find_entry.returnPressed.connect(self._find_next)
        self.toolbar.addWidget(self.find_entry)
        self.find_case = QCheckBox("Aa")
        self.find_case.setToolTip("Match case")
        self.find_case.toggled.connect(self._sync_find_settings)
        self.toolbar.addWidget(self.find_case)
        self.find_whole = QCheckBox("Word")
        self.find_whole.setToolTip("Whole words only")
        self.find_whole.toggled.connect(self._sync_find_settings)
        self.toolbar.addWidget(self.find_whole)
        self.find_regex = QCheckBox(".*")
        self.find_regex.setToolTip("Regular expression")
        self.find_regex.toggled.connect(self._sync_find_settings)
        self.toolbar.addWidget(self.find_regex)
        self._load_find_settings()
        find_prev = QAction("◀", self)
        find_prev.setToolTip("Previous match")
        find_prev.triggered.connect(self._find_prev)
        self.toolbar.addAction(find_prev)
        find_next = QAction("▶", self)
        find_next.setToolTip("Next match")
        find_next.triggered.connect(self._find_next)
        self.toolbar.addAction(find_next)

        self.toolbar.addSeparator()
        self.font_size_spin = QSpinBox()
        self.font_size_spin.setRange(8, 72)
        self.font_size_spin.setValue(_resolve_editor_font_size(self.app.settings))
        self.font_size_spin.setToolTip("Editor font size")
        self.font_size_spin.valueChanged.connect(self._on_font_size)
        self.toolbar.addWidget(QLabel("Size:"))
        self.toolbar.addWidget(self.font_size_spin)

        export_menu = QMenu("Export", self)
        export_ch = export_menu.addAction("Export current chapter...")
        export_ch.triggered.connect(self._export_chapter)
        export_all = export_menu.addAction("Compile full manuscript (txt/md)...")
        export_all.triggered.connect(self._compile_manuscript)
        export_std = export_menu.addAction("Standard manuscript (txt)...")
        export_std.triggered.connect(self._compile_standard)
        export_docx = export_menu.addAction("Compile DOCX...")
        export_docx.triggered.connect(self._compile_docx)
        export_epub = export_menu.addAction("Compile EPUB...")
        export_epub.triggered.connect(self._compile_epub)
        export_bible = export_menu.addAction("Production bible (markdown)...")
        export_bible.triggered.connect(self._export_production_bible)
        export_btn = QPushButton("Export ▾")
        export_btn.setMenu(export_menu)
        self.toolbar.addWidget(export_btn)

        search_act = QAction("Search", self)
        search_act.setToolTip("Search the whole project")
        search_act.triggered.connect(self._open_project_search)
        self.toolbar.addAction(search_act)
        import_act = QAction("Import", self)
        import_act.setToolTip("Import Markdown or DOCX as a chapter")
        import_act.triggered.connect(self._import_doc)
        self.toolbar.addAction(import_act)
        snap_act = QAction("Snapshots", self)
        snap_act.triggered.connect(self._open_snapshots)
        self.toolbar.addAction(snap_act)
        notes_act = QAction("Notes", self)
        notes_act.setToolTip("Fix-later notes — not sent to the LLM unless you opt in")
        notes_act.triggered.connect(self._open_notes)
        self.toolbar.addAction(notes_act)

        self.toolbar.addSeparator()
        self.act_brainstorm = QAction("Brainstorm", self)
        self.act_brainstorm.triggered.connect(self._run_brainstorm)
        self.toolbar.addAction(self.act_brainstorm)
        self.act_ask = QAction("Ask Agent", self)
        self.act_ask.triggered.connect(self._ask_agent)
        self.toolbar.addAction(self.act_ask)
        self.act_visualize = QAction("Visualize", self)
        self.act_visualize.triggered.connect(self._visualize)
        self.toolbar.addAction(self.act_visualize)
        self.act_listen = QAction("Listen", self)
        self.act_listen.triggered.connect(self._listen)
        self.toolbar.addAction(self.act_listen)

        summarize_act = QAction("Summarize", self)
        summarize_act.setToolTip(
            "Store a compact recap of this chapter; it feeds the PREVIOUSLY "
            "section when writing later chapters")
        summarize_act.triggered.connect(self._summarize_chapter)
        self.toolbar.addAction(summarize_act)

        self.editor = QPlainTextEdit()
        font = QFont(
            _resolve_editor_font_family(self.app.settings),
            _resolve_editor_font_size(self.app.settings),
        )
        self.editor.setFont(font)
        self.editor.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        self.editor.textChanged.connect(self._on_text_changed)
        self.editor.cursorPositionChanged.connect(self._on_cursor)

        self.lore_footer = QLabel("")
        self.lore_footer.setProperty("muted", True)
        self.lore_footer.setWordWrap(True)

        self._build_ai_dock()
        self.editor.installEventFilter(self)
        svc = SpellCheckService.instance()
        self.spell = svc.attach(self.editor)
        svc.attach(self.author_note)
        svc.attach(self.ai_prompt)
        skip_spellcheck(self.ai_output)

        self.spell_bar = SpellReplaceBar(self.editor, self)
        layout.addWidget(self.spell_bar)

        self.include_notes_cb = QCheckBox("Include notes in AI")
        self.include_notes_cb.setToolTip(
            "Margin notes are excluded from Write/Chat unless this is checked.")
        self.include_notes_cb.setChecked(
            bool(self.app.settings.get("editor.include_notes_in_ai", False)))
        self.include_notes_cb.toggled.connect(
            lambda on: self.app.settings.set("editor.include_notes_in_ai", bool(on)))

        meta = QWidget()
        meta_l = QHBoxLayout(meta)
        meta_l.setContentsMargins(4, 0, 4, 0)
        self.status_combo = QComboBox()
        self.status_combo.addItems(["draft", "revise", "done"])
        self.status_combo.currentTextChanged.connect(self._save_chapter_meta)
        self.pov_edit = QLineEdit()
        self.pov_edit.setPlaceholderText("POV")
        self.pov_edit.editingFinished.connect(self._save_chapter_meta)
        self.loc_edit = QLineEdit()
        self.loc_edit.setPlaceholderText("Location")
        self.loc_edit.editingFinished.connect(self._save_chapter_meta)
        self.date_edit = QLineEdit()
        self.date_edit.setPlaceholderText("Story date")
        self.date_edit.editingFinished.connect(self._save_chapter_meta)
        self.split_combo = QComboBox()
        self.split_combo.addItems(["Split: off", "Split: Story Bible", "Split: Lore", "Split: other chapter"])
        try:
            self.split_combo.setCurrentIndex(int(self.app.settings.get("editor.split_mode", 0) or 0))
        except (TypeError, ValueError):
            pass
        self.split_combo.currentIndexChanged.connect(self._apply_split)
        self.split_combo.currentIndexChanged.connect(
            lambda i: self.app.settings.set("editor.split_mode", int(i)))
        meta_l.addWidget(QLabel("Status"))
        meta_l.addWidget(self.status_combo)
        meta_l.addWidget(self.pov_edit)
        meta_l.addWidget(self.loc_edit)
        meta_l.addWidget(self.date_edit)
        meta_l.addWidget(self.split_combo)
        meta_l.addWidget(self.include_notes_cb)
        meta_l.addStretch()

        manuscript = QWidget()
        mv = QVBoxLayout(manuscript)
        mv.setContentsMargins(0, 0, 0, 0)
        mv.addWidget(meta)
        mv.addWidget(self.editor, 1)

        self.split_pane = QPlainTextEdit()
        self.split_pane.setReadOnly(True)
        self.split_pane.hide()

        self.binder = BinderWidget(self)
        self.binder.chapter_selected.connect(self._select_chapter_id)
        self.binder.reordered.connect(self._on_binder_reorder)

        self.continuity_list = QListWidget()
        self.continuity_list.setMaximumHeight(72)
        self.continuity_list.setToolTip("Live continuity (lore audit). Double-click to jump.")
        self.continuity_list.itemDoubleClicked.connect(self._jump_continuity)
        self.continuity_list.hide()

        split = QSplitter(Qt.Horizontal)
        split.addWidget(self.binder)
        split.addWidget(manuscript)
        split.addWidget(self.split_pane)
        split.addWidget(self.ai_dock)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 3)
        split.setStretchFactor(2, 2)
        split.setStretchFactor(3, 1)
        self._studio_split = split
        self.ai_dock.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout.addWidget(split, 1)
        layout.addWidget(self.continuity_list)
        layout.addWidget(self.lore_footer)

        self._build_draft_bar(layout)
        self._build_shortcuts()
        self._ai_throttle = StreamThrottler(self._append_ai_chunk, interval_ms=80, parent=self)
        self.refresh_chapters()

        self._lore_timer = QTimer(self)
        self._lore_timer.timeout.connect(self._refresh_lore_footer)
        if self.app.settings.get("editor.lore_autoscan", True):
            self._lore_timer.start(
                int(self.app.settings.get("editor.lore_scan_interval_ms", 5000)))
        self._start_snapshot_timer()
        self.apply_qol()
        self.apply_plugin_chrome()

    def _build_draft_bar(self, layout):
        self.draft_bar = QWidget()
        row = QHBoxLayout(self.draft_bar)
        row.setContentsMargins(4, 2, 4, 2)
        self.draft_label = QLabel("AI draft pending")
        self.draft_label.setProperty("muted", True)
        row.addWidget(self.draft_label, 1)
        self.draft_changes_btn = QPushButton("View changes")
        self.draft_changes_btn.setProperty("secondary", True)
        self.draft_changes_btn.setToolTip(
            "Compare the initial draft against each critic revision")
        self.draft_changes_btn.clicked.connect(self._show_draft_diff)
        self.draft_changes_btn.hide()
        row.addWidget(self.draft_changes_btn)
        self.refine_entry = QLineEdit()
        self.refine_entry.setPlaceholderText("Refine: e.g. less dialogue, slower pace…")
        self.refine_entry.setMaximumWidth(240)
        self.refine_entry.returnPressed.connect(self._refine_ai)
        row.addWidget(self.refine_entry)
        refine_btn = QPushButton("Refine")
        refine_btn.setProperty("secondary", True)
        refine_btn.setToolTip("Re-run with the note applied to this draft")
        refine_btn.clicked.connect(self._refine_ai)
        row.addWidget(refine_btn)
        retry_btn = QPushButton("Retry")
        retry_btn.setProperty("secondary", True)
        retry_btn.setToolTip("Re-run the same request for a fresh draft")
        retry_btn.clicked.connect(self._retry_ai)
        row.addWidget(retry_btn)
        accept_btn = QPushButton("Accept draft")
        accept_btn.clicked.connect(self._accept_draft)
        reject_btn = QPushButton("Reject")
        reject_btn.setProperty("secondary", True)
        reject_btn.clicked.connect(self._reject_draft)
        row.addWidget(accept_btn)
        row.addWidget(reject_btn)
        self.draft_bar.hide()
        layout.addWidget(self.draft_bar)

    def _build_shortcuts(self):
        """Editor-wide keyboard shortcuts for the AI workflow."""
        def add(seq: str, slot):
            sc = QShortcut(QKeySequence(seq), self)
            sc.setContext(Qt.WidgetWithChildrenShortcut)
            sc.activated.connect(slot)
            return sc

        add("Ctrl+Return", self._run_ai)
        add("Ctrl+Enter", self._run_ai)
        esc = QShortcut(QKeySequence("Esc"), self)
        esc.setContext(Qt.WidgetWithChildrenShortcut)
        esc.activated.connect(self._on_escape)
        add("Ctrl+Shift+A", self._accept_draft)
        add("Ctrl+Shift+X", self._reject_draft)
        add("Ctrl+Shift+R", self._retry_ai)

        self.ai_run.setToolTip("Run the AI (Ctrl+Enter)")
        self.ai_stop.setToolTip("Stop generation (Esc)")

    def _on_escape(self):
        """Esc: stop a running generation; otherwise dismiss ghost text / draft."""
        if self._ai_worker and self._ai_worker.isRunning():
            self._stop_ai()
        elif self._ghost_active:
            self._ghost_reject()
        elif self._pending_draft is not None:
            self._reject_draft()

    # ----------------------- ghost text (inline continuation) ---------------
    _GHOST_COLOR = "#8A9A80"

    def eventFilter(self, obj, event):
        if obj is self.editor and event.type() == QEvent.KeyPress:
            if event.key() in (Qt.Key_Space, Qt.Key_Return, Qt.Key_Enter):
                self._maybe_autocorrect()
            if (self._ghost_active
                    and event.key() in (Qt.Key_Tab, Qt.Key_Backtab)):
                self._ghost_accept()
                return True
            if self._ghost_active and event.key() == Qt.Key_Escape:
                if self._ai_worker and self._ai_worker.isRunning():
                    self._stop_ai()
                else:
                    self._ghost_reject()
                return True
        return super().eventFilter(obj, event)

    def _ghost_format(self) -> QTextCharFormat:
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(self._GHOST_COLOR))
        fmt.setFontItalic(True)
        return fmt

    def _ghost_begin(self):
        """Anchor a provisional region at the cursor (or manuscript end)."""
        cursor = self.editor.textCursor()
        cursor.clearSelection()
        doc = self.editor.document()
        start = QTextCursor(doc)
        start.setPosition(cursor.position())
        start.setKeepPositionOnInsert(True)
        end = QTextCursor(doc)
        end.setPosition(cursor.position())
        end.setKeepPositionOnInsert(False)
        self._ghost_start_cur = start
        self._ghost_end_cur = end
        self._ghost_active = True
        text_before = self.editor.toPlainText()[:cursor.position()]
        if text_before.strip() and not text_before.endswith("\n\n"):
            self._ghost_append("\n\n")

    def _ghost_append(self, text: str):
        if not self._ghost_active or not text:
            return
        self._ghost_end_cur.insertText(text, self._ghost_format())
        self.editor.ensureCursorVisible()

    def _ghost_selection(self) -> QTextCursor | None:
        if not self._ghost_active:
            return None
        cur = QTextCursor(self.editor.document())
        cur.setPosition(self._ghost_start_cur.position())
        cur.setPosition(self._ghost_end_cur.position(), QTextCursor.KeepAnchor)
        return cur

    def _ghost_set_text(self, text: str):
        """Replace the streamed region with the final (sanitized) passage."""
        cur = self._ghost_selection()
        if cur is None:
            return
        cur.insertText(text, self._ghost_format())
        self._ghost_end_cur.setPosition(
            self._ghost_start_cur.position() + len(text))

    def _ghost_accept(self):
        cur = self._ghost_selection()
        self._ghost_active = False
        if cur is not None and cur.hasSelection():
            cur.setCharFormat(QTextCharFormat())
            self.editor.setTextCursor(
                self._cursor_at(cur.selectionEnd()))
        self._ghost_start_cur = self._ghost_end_cur = None
        self.ai_status.set_status("", active=False)
        self._autosave()

    def _ghost_reject(self):
        cur = self._ghost_selection()
        self._ghost_active = False
        if cur is not None and cur.hasSelection():
            cur.removeSelectedText()
        self._ghost_start_cur = self._ghost_end_cur = None
        self.ai_status.set_status("", active=False)

    def _cursor_at(self, position: int) -> QTextCursor:
        cur = QTextCursor(self.editor.document())
        cur.setPosition(position)
        return cur

    def _build_ai_dock(self):
        self.ai_dock = QWidget()
        v = QVBoxLayout(self.ai_dock)
        v.addWidget(QLabel("AI Assistant"))
        subtitle = QLabel(EDITOR_AI_SUBTITLE)
        subtitle.setWordWrap(True)
        subtitle.setProperty("secondary", True)
        v.addWidget(subtitle)
        self.ai_mode = QComboBox()
        self.ai_mode.addItems(["Write", "Chat", "Query / blurb"])
        self.ai_mode.currentTextChanged.connect(self._on_ai_mode_changed)
        v.addWidget(self.ai_mode)
        self.style_preset = QComboBox()
        self.style_preset.addItems(["My Style", "Alt Style", "Neutral"])
        preset = self.app.settings.get("editor.voice_preset", "my")
        preset_map = {"my": 0, "alt": 1, "neutral": 2}
        self.style_preset.setCurrentIndex(preset_map.get(preset, 0))
        self.style_preset.setToolTip("Voice/style preset for Write mode")
        v.addWidget(self.style_preset)
        self.ghost_cb = QCheckBox("Ghost text (inline)")
        self.ghost_cb.setToolTip(
            "Stream the Write result directly into the manuscript as grey "
            "provisional text — Tab to accept, Esc to dismiss.")
        self.ghost_cb.setChecked(
            bool(self.app.settings.get("editor.ghost_text", False)))
        self.ghost_cb.toggled.connect(
            lambda on: self.app.settings.set("editor.ghost_text", bool(on)))
        v.addWidget(self.ghost_cb)
        self._on_ai_mode_changed(self.ai_mode.currentText())
        v.addWidget(QLabel("Author's note (persistent guidance)"))
        self.author_note = QPlainTextEdit()
        self.author_note.setPlaceholderText("Tone, POV, things the AI should always respect...")
        self.author_note.setMaximumHeight(60)
        v.addWidget(self.author_note)
        v.addWidget(QLabel("Instructions for this run"))
        self.ai_prompt = QPlainTextEdit()
        self.ai_prompt.setPlaceholderText("Instructions for the AI...")
        self.ai_prompt.setMaximumHeight(60)
        v.addWidget(self.ai_prompt)
        self.ai_output = QPlainTextEdit()
        self.ai_output.setReadOnly(True)
        v.addWidget(self.ai_output, 1)
        scroll_row = QHBoxLayout()
        scroll_row.addStretch()
        scroll_row.addWidget(make_auto_scroll_checkbox(self.app, self))
        v.addLayout(scroll_row)
        self.ai_status = ActivityStatus("")
        v.addWidget(self.ai_status)
        row = QHBoxLayout()
        self.ai_run = QPushButton("Run")
        self.ai_run.clicked.connect(self._run_ai)
        self.ai_stop = QPushButton("Stop")
        self.ai_stop.setProperty("danger", True)
        self.ai_stop.clicked.connect(self._stop_ai)
        self.ai_stop.setEnabled(False)
        self.ai_accept = QPushButton("Insert")
        self.ai_accept.setProperty("secondary", True)
        self.ai_accept.setToolTip("Insert at cursor or append as draft")
        self.ai_accept.clicked.connect(self._accept_ai)
        self.team_btn = QPushButton("Open Team…")
        self.team_btn.setProperty("secondary", True)
        self.team_btn.setToolTip("Open Team panel with your instructions pre-filled")
        self.team_btn.clicked.connect(self._open_team_panel)
        row.addWidget(self.ai_run)
        row.addWidget(self.ai_stop)
        row.addWidget(self.ai_accept)
        row.addWidget(self.team_btn)
        v.addLayout(row)

    def _on_ai_mode_changed(self, mode: str):
        self.ai_mode.setToolTip(EDITOR_MODE_TIPS.get(mode, ""))
        self.style_preset.setVisible(mode == "Write")
        if hasattr(self, "ghost_cb"):
            self.ghost_cb.setVisible(mode == "Write")

    def refresh_chapters(self):
        paths = self.app.engine.paths
        if not paths:
            return
        current = self._chapter_id
        self.chapter_combo.blockSignals(True)
        self.chapter_combo.clear()
        items = chapters.list_chapters(paths["chapters"])
        for ch in items:
            self.chapter_combo.addItem(ch["name"], ch["id"])
        if items:
            idx = 0
            if current:
                for i, ch in enumerate(items):
                    if ch["id"] == current:
                        idx = i
                        break
            self.chapter_combo.setCurrentIndex(idx)
            self._load_chapter(items[idx]["id"])
        else:
            created = chapters.create(paths["chapters"], "Chapter 1")
            self.chapter_combo.addItem(created["name"], created["id"])
            self._load_chapter(created["id"])
        self.chapter_combo.blockSignals(False)
        if hasattr(self, "binder"):
            self.binder.reload(chapters.list_chapters(paths["chapters"]), self._chapter_id)
        self._maybe_restore_crash()
        self.apply_plugin_chrome()

    def _load_chapter(self, chapter_id: str):
        paths = self.app.engine.paths
        if not paths:
            return
        if self._ghost_active:
            self._ghost_reject()
        data = chapters.read(paths["chapters"], chapter_id)
        self._chapter_id = chapter_id
        self._dirty = False
        self._reject_draft()
        self.editor.blockSignals(True)
        self.editor.setPlainText(data["content"])
        self.editor.blockSignals(False)
        self._load_chapter_meta(data)
        if hasattr(self, "binder"):
            self.binder.select_id(chapter_id)
        self._emit_counts()
        self._refresh_lore_footer()
        self._refresh_continuity()
        self._apply_split()

    def _on_chapter_changed(self, index: int):
        if index < 0:
            return
        cid = self.chapter_combo.itemData(index)
        if cid and cid != self._chapter_id:
            prev_id = self._chapter_id
            prev_chars = len(self.editor.toPlainText())
            self._autosave()
            self._load_chapter(cid)
            self._maybe_offer_summary_refresh(prev_id, prev_chars)

    def _maybe_offer_summary_refresh(self, chapter_id: str | None, chars: int):
        """When leaving a heavily edited chapter, offer to refresh its recap."""
        paths = self.app.engine.paths
        if not paths or not chapter_id:
            return
        try:
            from src import chapter_summaries
            entry = chapter_summaries.get(paths["chapter_summaries"], chapter_id)
            if not chapter_summaries.is_stale(entry, chars):
                return
        except Exception:
            return
        name = chapter_id
        for ch in chapters.list_chapters(paths["chapters"]):
            if ch["id"] == chapter_id:
                name = ch["name"]
                break
        if QMessageBox.question(
                self, "Refresh chapter recap",
                f"\"{name}\" changed since its recap was generated. "
                "Refresh the summary now?") == QMessageBox.Yes:
            self._summarize_chapter(chapter_id=chapter_id)

    def _new_chapter(self):
        paths = self.app.engine.paths
        if not paths:
            return
        n = len(chapters.list_chapters(paths["chapters"])) + 1
        created = chapters.create(paths["chapters"], f"Chapter {n}")
        self.refresh_chapters()
        for i in range(self.chapter_combo.count()):
            if self.chapter_combo.itemData(i) == created["id"]:
                self.chapter_combo.setCurrentIndex(i)
                break

    def _rename_chapter(self):
        paths = self.app.engine.paths
        if not paths or not self._chapter_id:
            return
        current = self.chapter_combo.currentText()
        name, ok = QInputDialog.getText(self, "Rename chapter", "Chapter name:", text=current)
        if not ok or not name.strip():
            return
        chapters.rename(paths["chapters"], self._chapter_id, name.strip())
        self.refresh_chapters()

    def _delete_chapter(self):
        paths = self.app.engine.paths
        if not paths or not self._chapter_id:
            return
        items = chapters.list_chapters(paths["chapters"])
        if len(items) <= 1:
            QMessageBox.warning(self, "Delete chapter", "Cannot delete the only chapter.")
            return
        if QMessageBox.question(
                self, "Delete chapter",
                f"Delete \"{self.chapter_combo.currentText()}\" permanently?") != QMessageBox.Yes:
            return
        chapters.delete(paths["chapters"], self._chapter_id)
        try:
            from src import chapter_summaries
            chapter_summaries.remove(paths["chapter_summaries"], self._chapter_id)
        except Exception:
            pass
        self._chapter_id = None
        self.refresh_chapters()

    def _on_font_size(self, size: int):
        font = self.editor.font()
        font.setPointSize(size)
        self.editor.setFont(font)
        self.app.settings.set("editor.font_size", size)

    def _on_text_changed(self):
        self._dirty = True
        self._emit_counts()
        self._save_timer.start(1500)
        paths = self.app.engine.paths
        if paths and self._chapter_id:
            from src import snapshots
            snapshots.write_crash_buffer(
                paths, self._chapter_id, self.editor.toPlainText())

    def _emit_counts(self):
        text = self.editor.toPlainText()
        words = len(text.split()) if text.strip() else 0
        chars = len(text)
        self.word_count_changed.emit(words, chars)

    def _autosave(self):
        if not self._dirty or not self._chapter_id:
            return
        if self._ghost_active:
            return  # never persist provisional ghost text
        paths = self.app.engine.paths
        if not paths:
            return
        chapters.write(paths["chapters"], self._chapter_id, self.editor.toPlainText())
        self._dirty = False

    def flush(self):
        self._autosave()

    def _selected_text(self) -> str:
        cursor = self.editor.textCursor()
        if cursor.hasSelection():
            return cursor.selectedText().replace("\u2029", "\n")
        return ""

    def _voice_preset_key(self) -> str:
        return ("my", "alt", "neutral")[self.style_preset.currentIndex()]

    def _find_next(self):
        self._run_find(forward=True)

    def _find_prev(self):
        self._run_find(forward=False)

    def _load_find_settings(self):
        s = self.app.settings
        self.find_case.setChecked(s.get("editor.find_case_sensitive", False))
        self.find_whole.setChecked(s.get("editor.find_whole_words", False))
        self.find_regex.setChecked(s.get("editor.find_regex", False))

    def _sync_find_settings(self):
        s = self.app.settings
        s.set("editor.find_case_sensitive", self.find_case.isChecked(), save=True)
        s.set("editor.find_whole_words", self.find_whole.isChecked(), save=True)
        s.set("editor.find_regex", self.find_regex.isChecked(), save=True)

    def apply_settings(self):
        """Live-apply settings after Settings panel save."""
        from ui_qt.widgets.spellcheck import set_spellcheck_enabled, install_spellcheck_subtree
        set_spellcheck_enabled(self.app.settings.get("editor.spellcheck", True))
        install_spellcheck_subtree(self)
        self._load_find_settings()
        interval = int(self.app.settings.get("editor.lore_scan_interval_ms", 3000))
        if self.app.settings.get("editor.lore_autoscan", True):
            self._lore_timer.start(interval)
        else:
            self._lore_timer.stop()
            self.lore_footer.setText("")
        self.include_notes_cb.setChecked(
            bool(self.app.settings.get("editor.include_notes_in_ai", False)))
        self.apply_qol()
        self.apply_plugin_chrome()

    def _run_find(self, forward: bool = True):
        needle = self.find_entry.text()
        if not needle:
            return
        flags = QTextDocument.FindFlag(0)
        if not forward:
            flags |= QTextDocument.FindBackward
        if self.find_case.isChecked():
            flags |= QTextDocument.FindCaseSensitively
        if self.find_whole.isChecked():
            flags |= QTextDocument.FindWholeWords
        if self.find_regex.isChecked():
            flags |= QTextDocument.FindRegularExpression
        try:
            found = self.editor.find(needle, flags)
        except Exception:
            self.app.show_toast("Invalid regular expression.", error=True)
            return
        if not found:
            cursor = self.editor.textCursor()
            if forward:
                cursor.movePosition(QTextCursor.Start)
            else:
                cursor.movePosition(QTextCursor.End)
            self.editor.setTextCursor(cursor)
            try:
                self.editor.find(needle, flags)
            except Exception:
                pass

    def _export_chapter(self):
        paths = self.app.engine.paths
        if not paths or not self._chapter_id:
            return
        self.flush()
        path, _filt = QFileDialog.getSaveFileName(
            self, "Export chapter", "", "Text (*.txt);;Markdown (*.md)")
        if not path:
            return
        fmt = "md" if path.lower().endswith(".md") else "txt"
        content = export_mod.export_chapter(paths, self._chapter_id, fmt)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        self.app.show_toast(f"Exported chapter to {path}")

    def _compile_manuscript(self):
        paths = self.app.engine.paths
        if not paths:
            return
        self.flush()
        path, _filt = QFileDialog.getSaveFileName(
            self, "Compile manuscript", "", "Text (*.txt);;Markdown (*.md)")
        if not path:
            return
        fmt = "md" if path.lower().endswith(".md") else "txt"
        content = export_mod.compile_manuscript(paths, fmt)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        self.app.show_toast(f"Compiled manuscript to {path}")

    def _compile_standard(self):
        paths = self.app.engine.paths
        if not paths:
            return
        self.flush()
        path, _f = QFileDialog.getSaveFileName(
            self, "Standard manuscript", "", "Text (*.txt)")
        if not path:
            return
        proj = self.app.engine.active_project() or {}
        text = export_mod.compile_standard_manuscript(
            paths, title=proj.get("name") or "Manuscript")
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        self.app.show_toast(f"Saved {path}")

    def _compile_docx(self):
        paths = self.app.engine.paths
        if not paths:
            return
        self.flush()
        path, _f = QFileDialog.getSaveFileName(
            self, "Compile DOCX", "", "Word (*.docx)")
        if not path:
            return
        proj = self.app.engine.active_project() or {}
        data = export_mod.compile_docx_bytes(paths, title=proj.get("name") or "Manuscript")
        with open(path, "wb") as f:
            f.write(data)
        self.app.show_toast(f"Saved {path}")

    def _compile_epub(self):
        paths = self.app.engine.paths
        if not paths:
            return
        self.flush()
        path, _f = QFileDialog.getSaveFileName(
            self, "Compile EPUB", "", "EPUB (*.epub)")
        if not path:
            return
        proj = self.app.engine.active_project() or {}
        data = export_mod.compile_epub_bytes(
            paths, title=proj.get("name") or "Manuscript")
        with open(path, "wb") as f:
            f.write(data)
        self.app.show_toast(f"Saved {path}")

    def _export_production_bible(self):
        paths = self.app.engine.paths
        if not paths:
            return
        path, _f = QFileDialog.getSaveFileName(
            self, "Production bible", "", "Markdown (*.md)")
        if not path:
            return
        proj = self.app.engine.active_project() or {}
        text = export_mod.export_production_bible(
            paths, project_name=proj.get("name") or "Project")
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        self.app.show_toast(f"Saved {path}")

    def _refresh_lore_footer(self):
        paths = self.app.engine.paths
        if not paths or not self.app.settings.get("editor.lore_autoscan", True):
            self.lore_footer.setText("")
            self._refresh_continuity()
            return
        try:
            ranked = story_context.rank_active_lore(
                paths,
                self.editor.toPlainText(),
                max_cards=int(self.app.settings.get("editor.lore_max_cards", 5)),
                match_mode=self.app.settings.get("editor.lore_match_mode", "substring"),
            )
            if ranked:
                chips = ", ".join(e.get("name", "?") for e in ranked[:5])
                self.lore_footer.setText(f"Active lore: {chips}")
            else:
                self.lore_footer.setText("")
        except Exception:
            self.lore_footer.setText("")
        self._refresh_continuity()

    def _run_ai(self):
        if self._ai_worker and self._ai_worker.isRunning():
            return
        prompt = self.ai_prompt.toPlainText().strip()
        mode = self.ai_mode.currentText().lower()
        check_prompt = prompt or f"Editor {mode} on current chapter"
        proceed, enriched = run_ambiguity_gate(self, self.app, check_prompt)
        if not proceed:
            return
        if enriched != check_prompt and prompt:
            prompt = enriched

        self.app.engine.clear_cancel()
        self.ai_output.clear()
        self._ai_buffer = ""
        self._stage_drafts = []
        self._ai_throttle.flush_now()
        self._lore_timer.stop()
        self.ai_run.setEnabled(False)
        self.ai_stop.setEnabled(True)
        mode_label = self.ai_mode.currentText()
        self.ai_status.set_status(f"{mode_label}…", active=True)
        selection = self._selected_text()
        author_note = self.author_note.toPlainText().strip()
        if self.include_notes_cb.isChecked() and self._chapter_id:
            from src import chapter_notes
            extra = chapter_notes.format_for_prompt(
                chapter_notes.load(self.app.engine.paths, self._chapter_id))
            if extra:
                author_note = (author_note + "\n\n" + extra).strip() if author_note else extra
        combined_note = author_note
        if prompt:
            combined_note = (author_note + "\n\n" + prompt).strip() if author_note else prompt
        if self._refine_note:
            note = "Revision note from the author: " + self._refine_note
            combined_note = (combined_note + "\n\n" + note).strip() if combined_note else note
            self._refine_note = ""

        self.app.settings.set("editor.voice_preset", self._voice_preset_key())

        mode = self.ai_mode.currentText().lower()
        text = self.editor.toPlainText()
        cid = self._chapter_id or ""

        if mode.startswith("query"):
            kind, ok = QInputDialog.getItem(
                self, "Query / blurb", "Job type:",
                ["query", "synopsis", "blurb"], 2, False)
            if not ok:
                self.ai_run.setEnabled(True)
                self.ai_stop.setEnabled(False)
                self.ai_status.set_status("", active=False)
                return

            def pipeline_fn():
                yield from self.app.writing.editor_query_blurb(
                    kind, extra=prompt, show_think=False)

            self._ai_worker = EditorPipelineWorker(self.app.engine, pipeline_fn)
            self._ai_worker.event.connect(
                self._on_pipeline_event, Qt.ConnectionType.QueuedConnection)
            self._ai_worker.finished_ok.connect(
                self._on_ai_done, Qt.ConnectionType.QueuedConnection)
            self._ai_worker.start()
            return

        if mode == "write":
            self._pipeline_step = 0
            before = text
            if selection:
                idx = text.find(selection)
                if idx >= 0:
                    before = text[:idx + len(selection)]
            if self._ghost_active:
                self._ghost_reject()
            if self.ghost_cb.isChecked():
                self._ghost_begin()

            def pipeline_fn():
                yield from self.app.writing.editor_write(
                    before, cid, author_note=combined_note, show_think=False)

            self._ai_worker = EditorPipelineWorker(self.app.engine, pipeline_fn)
            self._ai_worker.event.connect(
                self._on_pipeline_event, Qt.ConnectionType.QueuedConnection)
            self._ai_worker.finished_ok.connect(
                self._on_ai_done, Qt.ConnectionType.QueuedConnection)
            self._ai_worker.start()
            return

        def stream_fn():
            paths = self.app.engine.paths
            chat_persona = self.app.engine._resolve_persona(
                self.app.settings.get("editor.chat_persona", "quest_architect"))
            system = story_context.build_chat_system(
                paths, manuscript_text=text, chapter_id=cid,
                author_note=author_note,
                persona_system_prompt=chat_persona.get("system_prompt", ""))
            history = list(self._chat_history)
            yield from self.app.writing.editor_chat(
                system, history, prompt or "Let's discuss the project.",
                show_think=False)

        self._ai_worker = EditorAiWorker(self.app.engine, stream_fn)
        self._ai_worker.delta.connect(self._on_ai_delta, Qt.ConnectionType.QueuedConnection)
        self._ai_worker.finished_ok.connect(self._on_ai_done, Qt.ConnectionType.QueuedConnection)
        self._ai_worker.start()

    def _on_pipeline_event(self, kind, a, b):
        if kind == "step":
            persona = a if isinstance(a, dict) else {}
            msg = b or "Working…"
            if self._pipeline_step > 0:
                self._ai_buffer = ""
                self.ai_output.clear()
                self._ai_throttle.flush_now()
            self._pipeline_step += 1
            name = persona.get("display_name", "Agent")
            self.ai_status.set_status(f"{name}: {msg}", active=True)
        elif kind == "delta":
            text = b or ""
            self._ai_buffer += text
            self._ai_throttle.append(text)
            if self._ghost_active and self._pipeline_step <= 1:
                self._ghost_append(text)
            words = len(self._ai_buffer.split()) if self._ai_buffer.strip() else 0
            persona = a if isinstance(a, dict) else {}
            name = persona.get("display_name", "")
            label = f"{name}…  {words} words" if name else f"Streaming…  {words} words"
            self.ai_status.set_status(label, active=True)
        elif kind == "plan":
            lines = [
                f"  {i + 1}. {s['persona']['display_name']} → {s['instruction']}"
                for i, s in enumerate(a or [])
            ]
            self.ai_output.setPlainText("Team plan:\n" + ("\n".join(lines) or "(empty)"))
            self._ai_buffer = self.ai_output.toPlainText()
            scroll_to_end(self.ai_output, self.app)
        elif kind == "final":
            self._ai_throttle.flush_now()
            self.ai_output.setPlainText(a or "")
            self._ai_buffer = a or ""
            scroll_to_end(self.ai_output, self.app)
            if self._ghost_active:
                self._ghost_set_text(a or "")
        elif kind == "stage_draft":
            persona = a if isinstance(a, dict) else {}
            self._stage_drafts.append(
                (persona.get("display_name", "Agent"), b or ""))
        elif kind == "step_done":
            persona = a if isinstance(a, dict) else {}
            name = persona.get("display_name", "Agent")
            self.ai_status.set_status(f"{name} finished.", active=True)

    def _summarize_chapter(self, *, chapter_id: str | None = None):
        """Run the Session Summarizer on a chapter and store the recap."""
        if self._ai_worker and self._ai_worker.isRunning():
            self.app.show_toast("AI is busy — try again after the current run.", error=True)
            return
        if getattr(self, "_summary_worker", None) and self._summary_worker.isRunning():
            return
        paths = self.app.engine.paths
        if not paths:
            return
        cid = chapter_id or self._chapter_id
        if not cid:
            return
        if cid == self._chapter_id:
            text = self.editor.toPlainText().strip()
        else:
            try:
                text = chapters.read(paths["chapters"], cid)["content"].strip()
            except Exception:
                return
        if not text:
            self.app.show_toast("Chapter is empty — nothing to summarize.", error=True)
            return

        persona = self.app.engine._resolve_persona("chat_historian") or {}
        model_key = persona.get("model_key", "operator")
        system = (
            "You are a story archivist. Summarize the chapter you are given "
            "into a compact recap of 4-8 sentences: key events, character "
            "developments, reveals, and unresolved threads. Plain prose, no "
            "headers, no markers, no commentary.")
        user = "CHAPTER TEXT:\n" + text[:16000] + "\n\nWrite the recap now."
        source_chars = len(text)

        def stream_fn():
            yield from self.app.engine.stream_prompt(
                model_key, system, user, temperature=0.3, max_tokens=500)

        self._summary_buffer = ""
        self.ai_status.set_status("Summarizing chapter…", active=True)
        self._summary_worker = EditorAiWorker(self.app.engine, stream_fn)
        self._summary_worker.delta.connect(
            self._on_summary_delta, Qt.ConnectionType.QueuedConnection)
        self._summary_worker.finished_ok.connect(
            lambda cancelled, c=cid, n=source_chars: self._on_summary_done(
                cancelled, c, n),
            Qt.ConnectionType.QueuedConnection)
        self._summary_worker.start()

    def _on_summary_delta(self, text: str):
        self._summary_buffer += text

    def _on_summary_done(self, cancelled: bool, chapter_id: str, source_chars: int):
        self.ai_status.set_status("", active=False)
        summary = self._summary_buffer.strip()
        if cancelled or not summary:
            self.app.show_toast("Chapter summary was not generated.", error=True)
            return
        paths = self.app.engine.paths
        if not paths:
            return
        from src import chapter_summaries
        chapter_summaries.set_summary(
            paths["chapter_summaries"], chapter_id, summary, source_chars)
        self.app.show_toast("Chapter recap saved — it will appear in PREVIOUSLY.")

    def _open_team_panel(self):
        prompt = self.ai_prompt.toPlainText().strip()
        if hasattr(self.app, "open_team"):
            self.app.open_team(initial_message=prompt, mode="single")
        elif hasattr(self.app, "open_agents"):
            self.app.open_agents(initial_message=prompt, mode="single")

    def insert_ai_draft(self, text: str, *, sanitize: bool = True):
        """Insert agent output into the manuscript (from Agents handoff)."""
        if not text or not text.strip():
            return
        body = text.strip()
        if sanitize:
            before = self.editor.toPlainText()
            body = story_context.sanitize_write_output(body, story_tail=before)
        if body:
            self._insert_text(body)

    def _append_ai_chunk(self, text: str):
        self.ai_output.moveCursor(QTextCursor.End)
        self.ai_output.insertPlainText(text)
        scroll_to_end(self.ai_output, self.app)

    def _stop_ai(self):
        self.app.engine.request_cancel()
        self.ai_status.set_status("Stopping…", active=True)

    def _on_ai_delta(self, text: str):
        self._ai_buffer += text
        self._ai_throttle.append(text)
        words = len(self._ai_buffer.split()) if self._ai_buffer.strip() else 0
        self.ai_status.set_status(f"Streaming…  {words} words", active=True)

    def _on_ai_done(self, cancelled: bool):
        self._ai_throttle.flush_now()
        self.ai_status.set_status("", active=False)
        if self.app.settings.get("editor.lore_autoscan", True):
            self._lore_timer.start(
                int(self.app.settings.get("editor.lore_scan_interval_ms", 5000)))
        self.ai_run.setEnabled(True)
        self.ai_stop.setEnabled(False)
        if cancelled:
            if self._ghost_active:
                self._ghost_reject()
            self.ai_output.appendPlainText("\n[Cancelled]")
            self.ai_status.set_status("Cancelled", active=False)
            return
        text = self.ai_output.toPlainText().strip()
        if text and self.ai_mode.currentText().lower() == "chat":
            user_msg = self.ai_prompt.toPlainText().strip() or "Let's discuss the project."
            self._chat_history.append(("user", user_msg))
            self._chat_history.append(("assistant", text))
        if self._ghost_active:
            if not text:
                self._ghost_reject()
            else:
                self.editor.setFocus()
                self.ai_status.set_status(
                    "Ghost text ready — Tab to accept, Esc to dismiss",
                    active=False)
            return
        if text:
            self._show_draft(text)

    def _show_draft(self, text: str):
        self._pending_draft = text
        self.draft_bar.show()
        self.draft_label.setText(f"AI draft ready ({len(text.split())} words)")
        self.draft_changes_btn.setVisible(len(self._stage_drafts) >= 2)
        self.refine_entry.clear()

    def _accept_draft(self):
        if self._pending_draft:
            self._insert_text(self._pending_draft)
            self._append_voice_lock(self._pending_draft)
            self._reject_draft()

    def _reject_draft(self):
        self._pending_draft = None
        self.draft_bar.hide()

    def _show_draft_diff(self):
        if len(self._stage_drafts) < 2:
            return
        from ui_qt.widgets.draft_diff_dialog import DraftDiffDialog
        DraftDiffDialog(self, list(self._stage_drafts)).exec()

    def _retry_ai(self):
        if self._ai_worker and self._ai_worker.isRunning():
            return
        self._reject_draft()
        self._run_ai()

    def _refine_ai(self):
        if self._ai_worker and self._ai_worker.isRunning():
            return
        note = self.refine_entry.text().strip()
        if not note:
            self._retry_ai()
            return
        self._refine_note = note
        self._reject_draft()
        self._run_ai()

    def _accept_ai(self):
        text = self.ai_output.toPlainText().strip()
        if not text:
            return
        self._insert_text(text)
        self.ai_output.clear()
        self._reject_draft()

    def _insert_text(self, text: str):
        cursor = self.editor.textCursor()
        if cursor.hasSelection():
            cursor.insertText(text)
        elif cursor.position() < len(self.editor.toPlainText()):
            cursor.insertText(text)
        else:
            if self.editor.toPlainText().strip():
                cursor.insertText("\n\n")
            cursor.insertText(text)
        self.editor.setTextCursor(cursor)

    def on_project_change(self):
        self._chat_history.clear()
        self.refresh_chapters()
        self._start_snapshot_timer()
        self.apply_plugin_chrome()
        self.apply_qol()

    def _start_snapshot_timer(self):
        if getattr(self, "_snap_timer", None) is None:
            self._snap_timer = QTimer(self)
            self._snap_timer.timeout.connect(self._timed_snapshot)
        self._snap_timer.start(5 * 60 * 1000)

    def _timed_snapshot(self):
        paths = self.app.engine.paths
        if not paths or not self._chapter_id:
            return
        from src import snapshots
        snapshots.take_snapshot(
            paths, self._chapter_id, self.editor.toPlainText(), reason="auto")

    def _maybe_restore_crash(self):
        paths = self.app.engine.paths
        if not paths:
            return
        from src import snapshots
        buf = snapshots.load_crash_buffer(paths)
        if not buf:
            return
        cid = buf.get("chapterId")
        if cid != self._chapter_id:
            return
        saved = self.editor.toPlainText()
        crashed = buf.get("content") or ""
        if crashed and crashed != saved:
            if QMessageBox.question(
                    self, "Recover unsaved text",
                    "A crash buffer has newer text for this chapter. Restore it?"
                    ) == QMessageBox.Yes:
                self.editor.setPlainText(crashed)
                self._dirty = True
        snapshots.clear_crash_buffer(paths)

    def _load_chapter_meta(self, data: dict):
        self._meta_loading = True
        idx = self.status_combo.findText(data.get("status") or "draft")
        self.status_combo.setCurrentIndex(max(0, idx))
        self.pov_edit.setText(data.get("pov") or "")
        self.loc_edit.setText(data.get("location") or "")
        self.date_edit.setText(data.get("storyDate") or "")
        self._meta_loading = False

    def _save_chapter_meta(self, *_args):
        if getattr(self, "_meta_loading", False):
            return
        paths = self.app.engine.paths
        if not paths or not self._chapter_id:
            return
        chapters.update_meta(
            paths["chapters"], self._chapter_id,
            status=self.status_combo.currentText(),
            pov=self.pov_edit.text().strip(),
            location=self.loc_edit.text().strip(),
            storyDate=self.date_edit.text().strip())
        self.binder.reload(chapters.list_chapters(paths["chapters"]), self._chapter_id)

    def _select_chapter_id(self, cid: str):
        if not cid or cid == self._chapter_id:
            return
        for i in range(self.chapter_combo.count()):
            if self.chapter_combo.itemData(i) == cid:
                self.chapter_combo.setCurrentIndex(i)
                return

    def _on_binder_reorder(self, ids: list):
        paths = self.app.engine.paths
        if paths:
            chapters.reorder(paths["chapters"], ids)
            self.refresh_chapters()

    def _apply_split(self, *_args):
        mode = self.split_combo.currentIndex()
        paths = self.app.engine.paths
        if mode == 0 or not paths:
            self.split_pane.hide()
            return
        self.split_pane.show()
        if mode == 1:
            from src import story_bible
            data = story_bible.read(paths["bible"])
            self.split_pane.setPlainText(
                "\n".join(f"{k}: {v}" for k, v in (data or {}).items() if v))
        elif mode == 2:
            from src import lore
            book = lore.read(paths["lore"])
            lines = []
            for section in ("characters", "world"):
                for e in book.get(section) or []:
                    lines.append(f"{e.get('name')}: {(e.get('notes') or '')[:200]}")
            self.split_pane.setPlainText("\n\n".join(lines))
        else:
            items = chapters.list_chapters(paths["chapters"])
            other = next((c for c in items if c["id"] != self._chapter_id), None)
            if other:
                data = chapters.read(paths["chapters"], other["id"])
                self.split_pane.setPlainText(
                    f"# {data['name']}\n\n{data.get('content') or ''}")
            else:
                self.split_pane.setPlainText("(no other chapter)")

    def _on_cursor(self):
        self.spell_bar.refresh(self.app.settings)
        if self.app.settings.get("editor.typewriter", False):
            self.editor.centerCursor()

    def _maybe_autocorrect(self):
        if not self.app.settings.get("editor.autocorrect", False):
            return
        svc = SpellCheckService.instance()
        word, cursor = svc.word_at_cursor(self.editor)
        repl = svc.autocorrect_candidate(word)
        if repl and repl != word:
            svc._replace_word(cursor, repl)

    def apply_qol(self):
        focus = bool(self.app.settings.get("editor.focus_mode", False))
        llm = is_enabled(self.app.settings, "llm")
        if hasattr(self, "ai_dock"):
            self.ai_dock.setVisible(llm and not focus)

    def apply_plugin_chrome(self):
        s = self.app.settings
        llm = is_enabled(s, "llm")
        image = is_enabled(s, "image")
        audio = is_enabled(s, "audio")
        self.act_brainstorm.setVisible(llm)
        self.act_ask.setVisible(llm)
        self.act_visualize.setVisible(image)
        self.act_listen.setVisible(audio)
        self.ai_dock.setVisible(llm and not s.get("editor.focus_mode", False))
        self.team_btn.setVisible(llm)
        self.continuity_list.setVisible(llm)
        for act in self.toolbar.actions():
            if act.text() == "Summarize":
                act.setVisible(llm)

    def _refresh_continuity(self):
        if not is_enabled(self.app.settings, "llm"):
            self.continuity_list.hide()
            return
        paths = self.app.engine.paths
        if not paths:
            return
        from src import lore_audit
        from PySide6.QtWidgets import QListWidgetItem
        issues = lore_audit.audit_lore(paths)[:12]
        self.continuity_list.clear()
        for issue in issues:
            item = QListWidgetItem(f"[{issue.severity}] {issue.message}")
            item.setData(256, issue)
            self.continuity_list.addItem(item)
        self.continuity_list.setVisible(bool(issues))

    def _jump_continuity(self, item):
        issue = item.data(256)
        entry_id = getattr(issue, "entry_id", None)
        if not entry_id:
            entry_id = getattr(issue, "id", None)
        if entry_id:
            self.app.open_lore_entry(str(entry_id))

    def _open_project_search(self):
        from ui_qt.widgets.studio_dialogs import ProjectSearchDialog
        ProjectSearchDialog(self.app, self).exec()

    def _open_snapshots(self):
        if not self._chapter_id:
            return
        from ui_qt.widgets.studio_dialogs import SnapshotDialog
        SnapshotDialog(self.app, self._chapter_id, self).exec()

    def _open_notes(self):
        if not self._chapter_id:
            return
        from ui_qt.widgets.studio_dialogs import NotesDialog
        NotesDialog(self.app, self._chapter_id, self).exec()

    def _import_doc(self):
        paths = self.app.engine.paths
        if not paths:
            return
        path, _f = QFileDialog.getOpenFileName(
            self, "Import chapter", "",
            "Documents (*.md *.markdown *.txt *.docx)")
        if not path:
            return
        from src import import_docs
        created = import_docs.import_file(paths["chapters"], path)
        self.refresh_chapters()
        self._select_chapter_id(created["id"])
        self.app.show_toast(f"Imported {created['name']}")

    def _run_brainstorm(self):
        if not is_enabled(self.app.settings, "llm"):
            return
        if self._ai_worker and self._ai_worker.isRunning():
            return
        prompt = self.ai_prompt.toPlainText().strip()
        recent = self.editor.toPlainText()[-2000:]
        selection = self._selected_text()
        self.ai_output.clear()
        self.ai_run.setEnabled(False)
        self.ai_stop.setEnabled(True)
        self.ai_status.set_status("Brainstorm…", active=True)

        def pipeline_fn():
            yield from self.app.writing.editor_brainstorm(
                recent, selection=selection, instruction=prompt)

        self._ai_worker = EditorPipelineWorker(self.app.engine, pipeline_fn)
        self._ai_worker.event.connect(
            self._on_pipeline_event, Qt.ConnectionType.QueuedConnection)
        self._ai_worker.finished_ok.connect(
            self._on_ai_done, Qt.ConnectionType.QueuedConnection)
        self._ai_worker.start()

    def _ask_agent(self):
        if not is_enabled(self.app.settings, "llm"):
            return
        text = self._selected_text() or self.ai_prompt.toPlainText().strip()
        self.app.open_team(text or "Help me with this scene.", mode="single")

    def _visualize(self):
        if not is_enabled(self.app.settings, "image"):
            self.app.show_toast("Enable the Image pack in Add Ons.", error=True)
            return
        text = self._selected_text() or self.editor.toPlainText()[-800:]
        if not text.strip():
            return
        self.app.show_feature("Image Gen")
        panel = self.app._panels.get("Image Gen")
        if panel and hasattr(panel, "prompt"):
            panel.prompt.setPlainText(text.strip())
        self.app.show_toast("Image Gen ready — review the prompt and generate.")

    def _listen(self):
        if not is_enabled(self.app.settings, "audio"):
            self.app.show_toast("Enable the Audio pack in Add Ons.", error=True)
            return
        text = self._selected_text() or self.editor.toPlainText()[-1200:]
        if not text.strip():
            return
        try:
            self.app.tts.speak(text)
            self.app.show_toast("Speaking…")
        except Exception as exc:
            self.app.show_toast(str(exc), error=True)

    def _append_voice_lock(self, text: str):
        paths = self.app.engine.paths
        if not paths or not text:
            return
        import os
        path = os.path.join(paths["root"], "voice_lock.txt")
        try:
            with open(path, "a", encoding="utf-8") as fh:
                fh.write("\n\n" + text[-2000:])
        except OSError:
            pass

