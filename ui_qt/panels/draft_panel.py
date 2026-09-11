"""Draft lightbox — generate editable chapter beats, then Plan Draft prose."""

from __future__ import annotations

from PySide6.QtCore import QEvent
from PySide6.QtWidgets import (
    QComboBox, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit,
    QPushButton, QVBoxLayout,
)

from src import chapters, draft_engine, outline, story_bible
from src.plugins import is_enabled
from ui_qt.panels.base import BasePanel
from ui_qt.widgets.activity_indicator import ActivityStatus
from ui_qt.workers import EditorAiWorker


class DraftPanel(BasePanel):
    title = "Draft"

    def __init__(self, app, parent=None):
        super().__init__(app, parent)
        self._chapter_id: str | None = None
        self._scenes_worker: EditorAiWorker | None = None
        self._scenes_buffer = ""
        self._loading = False

        layout = QVBoxLayout(self)

        ch_row = QHBoxLayout()
        ch_row.addWidget(QLabel("Chapter"))
        self.chapter_combo = QComboBox()
        self.chapter_combo.currentIndexChanged.connect(self._on_chapter_changed)
        ch_row.addWidget(self.chapter_combo, 1)
        layout.addLayout(ch_row)

        self.summary_box = QGroupBox("Chapter outline")
        self.summary_box.setCheckable(True)
        self.summary_box.setChecked(False)
        self.summary_box.setToolTip("Expand to read or edit the chapter summary")
        sum_v = QVBoxLayout(self.summary_box)
        self.summary_preview = QLabel("")
        self.summary_preview.setWordWrap(True)
        self.summary_preview.setProperty("muted", True)
        sum_v.addWidget(self.summary_preview)
        self.summary_edit = QPlainTextEdit()
        self.summary_edit.setPlaceholderText("Chapter outline summary…")
        self.summary_edit.setMaximumHeight(90)
        self.summary_edit.hide()
        self.summary_edit.textChanged.connect(self._on_summary_edited)
        sum_v.addWidget(self.summary_edit)
        self.summary_box.toggled.connect(self._toggle_summary)
        layout.addWidget(self.summary_box)

        layout.addWidget(QLabel("Scenes / beats (one per line)"))
        self.scenes = QPlainTextEdit()
        self.scenes.setPlaceholderText(
            "Each line is a scene beat.\n"
            "Generate Scenes fills this from the chapter outline, Focus brain dump, "
            "and scored lore — then edit freely.")
        self.scenes.textChanged.connect(self._mark_dirty)
        layout.addWidget(self.scenes, 1)

        gen_row = QHBoxLayout()
        self.gen_btn = QPushButton("Generate Scenes")
        self.gen_btn.setToolTip(
            "Draft beats from this chapter's outline, Focus research (parking lot), "
            "and relevant lore")
        self.gen_btn.clicked.connect(self._generate_scenes)
        gen_row.addWidget(self.gen_btn)
        save_btn = QPushButton("Save scenes")
        save_btn.setProperty("secondary", True)
        save_btn.clicked.connect(self._save_beats)
        gen_row.addWidget(save_btn)
        fill_ch = QPushButton("Fill from chapter…")
        fill_ch.setProperty("secondary", True)
        fill_ch.setToolTip(
            "Audit this chapter and fill definite POV, tense, bible, world, "
            "outline, and lore fields")
        fill_ch.clicked.connect(self._fill_from_chapters)
        gen_row.addWidget(fill_ch)
        gen_row.addStretch()
        layout.addLayout(gen_row)

        self.extra_box = QGroupBox("Extra instructions")
        self.extra_box.setCheckable(True)
        self.extra_box.setChecked(False)
        extra_v = QVBoxLayout(self.extra_box)
        self.extra = QPlainTextEdit()
        self.extra.setPlaceholderText("Optional direction for Generate Scenes and Plan Draft…")
        self.extra.setMaximumHeight(80)
        extra_v.addWidget(self.extra)
        self.extra_box.toggled.connect(
            lambda on: self.extra.setVisible(on))
        self.extra.setVisible(False)
        layout.addWidget(self.extra_box)

        craft = QHBoxLayout()
        self.pov = QLineEdit()
        self.pov.setPlaceholderText("POV")
        self.tense = QLineEdit()
        self.tense.setPlaceholderText("Tense")
        self.perspective = QComboBox()
        self.perspective.setEditable(True)
        if self.perspective.lineEdit() is not None:
            self.perspective.lineEdit().setPlaceholderText("Perspective character")
        craft.addWidget(QLabel("POV"))
        craft.addWidget(self.pov)
        craft.addWidget(QLabel("Character"))
        craft.addWidget(self.perspective, 1)
        craft.addWidget(QLabel("Tense"))
        craft.addWidget(self.tense)
        layout.addLayout(craft)

        foot = QHBoxLayout()
        self.plan_btn = QPushButton("Plan Draft")
        self.plan_btn.setToolTip(
            "Write one prose passage covering every scene and send it to the "
            "manuscript draft bar")
        self.plan_btn.clicked.connect(self._plan_draft)
        foot.addWidget(self.plan_btn)
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setProperty("danger", True)
        self.stop_btn.clicked.connect(self._stop)
        self.stop_btn.hide()
        foot.addWidget(self.stop_btn)
        foot.addStretch()
        layout.addLayout(foot)

        self.status = ActivityStatus("")
        layout.addWidget(self.status)
        self.scenes.installEventFilter(self)

    def eventFilter(self, obj, event):
        if obj is self.scenes and event.type() == QEvent.Type.FocusOut:
            if not self._loading:
                self._save_beats(silent=True)
        return super().eventFilter(obj, event)

    def on_show(self):
        self._reload()

    def on_project_change(self):
        self._reload()

    def _llm_ready(self) -> bool:
        if not self.app.engine.paths:
            self.app.show_toast("Open a project first.", error=True)
            return False
        if not is_enabled(self.app.settings, "llm"):
            self.app.show_toast("Enable the Local LLM pack in Add Ons.", error=True)
            return False
        return True

    def _busy(self) -> bool:
        editor = getattr(self.app, "editor", None)
        if editor and getattr(editor, "_ai_worker", None) and editor._ai_worker.isRunning():
            return True
        return bool(self._scenes_worker and self._scenes_worker.isRunning())

    def _reload(self):
        paths = self.app.engine.paths
        self._loading = True
        self._reload_chapters()
        self._prefill_craft()
        self._load_chapter()
        self._loading = False
        if not paths:
            self.summary_preview.setText("Open a project to plan a chapter draft.")

    def _reload_chapters(self):
        paths = self.app.engine.paths
        editor = getattr(self.app, "editor", None)
        current = None
        if editor:
            current = getattr(editor, "_chapter_id", None)
        self.chapter_combo.blockSignals(True)
        self.chapter_combo.clear()
        if paths:
            for ch in chapters.list_chapters(paths["chapters"]):
                self.chapter_combo.addItem(ch["name"], ch["id"])
        if current:
            idx = self.chapter_combo.findData(current)
            if idx >= 0:
                self.chapter_combo.setCurrentIndex(idx)
        self.chapter_combo.blockSignals(False)
        self._chapter_id = self.chapter_combo.currentData()

    def _prefill_craft(self, force: bool = False):
        paths = self.app.engine.paths
        pov = tense = ""
        if paths:
            bible = story_bible.read(paths["bible"])
            pov = (bible.get("pointOfView") or "").strip()
            tense = (bible.get("tense") or "").strip()
        if force or not self.pov.text().strip():
            self.pov.setText(pov)
        if force or not self.tense.text().strip():
            self.tense.setText(tense)
        names = draft_engine._character_names(paths) if paths else []
        current = self.perspective.currentText()
        chapter_pov = ""
        if paths and self._chapter_id:
            try:
                chapter_pov = (chapters.read(
                    paths["chapters"], self._chapter_id).get("pov") or "").strip()
            except ValueError:
                chapter_pov = ""
        pick = current
        if force or not pick:
            pick = chapter_pov or current
        self.perspective.blockSignals(True)
        self.perspective.clear()
        self.perspective.addItem("")
        for name in names:
            self.perspective.addItem(name)
        if pick:
            idx = self.perspective.findText(pick)
            if idx >= 0:
                self.perspective.setCurrentIndex(idx)
            else:
                self.perspective.setEditText(pick)
        self.perspective.blockSignals(False)

    def _fill_from_chapters(self):
        from ui_qt.widgets.manuscript_fill_dialog import run_manuscript_fill
        run_manuscript_fill(self, self.app, prefer_id=self._chapter_id)

    def _load_chapter(self):
        paths = self.app.engine.paths
        cid = self.chapter_combo.currentData()
        self._chapter_id = cid
        if not paths or not cid:
            self.scenes.clear()
            self.summary_edit.clear()
            self.summary_preview.setText("Select a chapter.")
            return
        data = outline.read_chapter(paths["outlines"], cid)
        summary = (data.get("summary") or "").strip()
        beats = [draft_engine._beat_text(b) for b in (data.get("beats") or [])]
        self.summary_edit.blockSignals(True)
        self.summary_edit.setPlainText(summary)
        self.summary_edit.blockSignals(False)
        self.summary_preview.setText(summary or "(no outline summary yet)")
        self.scenes.blockSignals(True)
        self.scenes.setPlainText("\n".join(b for b in beats if b))
        self.scenes.blockSignals(False)

    def _toggle_summary(self, expanded: bool):
        self.summary_preview.setVisible(not expanded)
        self.summary_edit.setVisible(expanded)

    def _on_summary_edited(self):
        if self._loading:
            return
        self.summary_preview.setText(
            self.summary_edit.toPlainText().strip() or "(no outline summary yet)")

    def _on_chapter_changed(self):
        if self._loading:
            return
        self._save_beats(silent=True)
        cid = self.chapter_combo.currentData()
        editor = getattr(self.app, "editor", None)
        if editor and cid and cid != getattr(editor, "_chapter_id", None):
            editor._select_chapter_id(cid)
        self._load_chapter()

    def _mark_dirty(self):
        pass

    def _beat_lines(self) -> list[str]:
        return [ln.strip() for ln in self.scenes.toPlainText().splitlines() if ln.strip()]

    def _flush_parking(self) -> str:
        focus = self.app._panels.get("Focus") if hasattr(self.app, "_panels") else None
        if focus and hasattr(focus, "_save_parking"):
            try:
                focus._save_parking(silent=True)
            except Exception:
                pass
        return draft_engine.read_parking_lot(self.app.engine.paths)

    def _save_beats(self, silent: bool = False) -> bool:
        paths = self.app.engine.paths
        cid = self._chapter_id or self.chapter_combo.currentData()
        if not paths or not cid:
            return False
        summary = self.summary_edit.toPlainText().strip()
        draft_engine.write_chapter_beats(
            paths, cid, self._beat_lines(), summary=summary)
        panel = self.app._panels.get("Story Bible") if hasattr(self.app, "_panels") else None
        if panel and hasattr(panel, "_reload_outline"):
            try:
                panel._reload_outline()
            except Exception:
                pass
        if not silent:
            self.app.show_toast("Chapter scenes saved to the outline.")
        return True

    def _set_gen_busy(self, busy: bool, status: str = ""):
        self.gen_btn.setEnabled(not busy)
        self.plan_btn.setEnabled(not busy)
        self.stop_btn.setVisible(busy)
        self.status.set_status(status, active=busy)

    def _generate_scenes(self):
        if not self._llm_ready():
            return
        if self._busy():
            self.app.show_toast("AI is busy — try again after the current run.", error=True)
            return
        cid = self.chapter_combo.currentData()
        if not cid:
            self.app.show_toast("Select a chapter first.", error=True)
            return
        self._save_beats(silent=True)
        parking = self._flush_parking()
        self.app.engine.clear_cancel()
        self._scenes_buffer = ""
        self.scenes.clear()
        self._set_gen_busy(True, "Generating scenes…")

        def stream_fn():
            yield from draft_engine.stream_generate_scenes(
                self.app.engine, self.app.engine.paths, cid,
                extra=self.extra.toPlainText(),
                pov=self.pov.text(),
                tense=self.tense.text(),
                perspective=self.perspective.currentText(),
                parking=parking)

        self._scenes_worker = EditorAiWorker(self.app.engine, stream_fn)
        self._scenes_worker.delta.connect(self._on_scenes_delta)
        self._scenes_worker.finished_ok.connect(self._on_scenes_done)
        self._scenes_worker.start()

    def _on_scenes_delta(self, text: str):
        self._scenes_buffer += text
        self.scenes.setPlainText(self._scenes_buffer)

    def _on_scenes_done(self, cancelled: bool):
        self._scenes_worker = None
        self._set_gen_busy(False)
        if cancelled:
            self.app.show_toast("Scene generation stopped.")
            return
        lines = draft_engine.parse_scene_lines(self._scenes_buffer)
        self.scenes.setPlainText("\n".join(lines))
        if lines:
            self._save_beats(silent=True)
            self.app.show_toast(f"Generated {len(lines)} scenes — edit, then Plan Draft.")
        else:
            self.app.show_toast("No scenes came back. Try a clearer outline or brain dump.",
                                error=True)

    def _plan_draft(self):
        if not self._llm_ready():
            return
        if self._busy():
            self.app.show_toast("AI is busy — try again after the current run.", error=True)
            return
        beats = self._beat_lines()
        if not beats:
            self.app.show_toast("Add or generate scenes first.", error=True)
            return
        self._save_beats(silent=True)
        parking = self._flush_parking()
        editor = getattr(self.app, "editor", None)
        if editor is None:
            self.app.show_toast("Editor is not ready.", error=True)
            return
        cid = self._chapter_id or self.chapter_combo.currentData()
        if cid:
            editor._select_chapter_id(cid)
        editor.plan_draft(
            beats,
            extra=self.extra.toPlainText(),
            pov=self.pov.text(),
            tense=self.tense.text(),
            perspective=self.perspective.currentText(),
            parking=parking)
        self.status.set_status("Plan Draft running in the editor…", active=False)

    def _stop(self):
        self.app.engine.request_cancel()
        self.status.set_status("Stopping…", active=True)
