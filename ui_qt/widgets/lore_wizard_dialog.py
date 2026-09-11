"""Multi-step Story Bible / lore generation wizard."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit,
    QPushButton, QStackedWidget, QVBoxLayout, QWidget,
)

from src import lore_types, lore_wizard
from ui_qt.widgets.flow_layout import FlowLayout
from ui_qt.widgets.spellcheck import install_spellcheck_subtree
from ui_qt.widgets.themed_dialog import ThemedDialog
from ui_qt.workers import LoreWizardWorker

# Keep cancelled QThreads alive until run() returns (dialog close must not
# destroy a worker still inside llama.cpp).
_ORPHAN_WORKERS: list = []


def _orphan_worker(worker: LoreWizardWorker | None) -> None:
    if worker is None or worker in _ORPHAN_WORKERS:
        return
    _ORPHAN_WORKERS.append(worker)

    def _drop():
        if worker in _ORPHAN_WORKERS:
            _ORPHAN_WORKERS.remove(worker)

    worker.finished.connect(_drop)
    worker.finished.connect(worker.deleteLater)


class LoreWizardDialog(ThemedDialog):
    """Interview chips + text, then preview generated fields."""

    PAGE_INTRO = 0
    PAGE_BUSY = 1
    PAGE_QUESTION = 2
    PAGE_PREVIEW = 3

    def __init__(self, parent, app, kind: str = "character", existing=None,
                 seed: str = "", *, pick_type: bool = False, title: str = ""):
        super().__init__(parent)
        self.app = app
        self.kind = lore_wizard.normalize_kind(kind)
        self.existing = dict(existing or {})
        self._pick_type = pick_type
        self._questions: list[dict] = []
        self._answers: dict[str, dict] = {}
        self._index = 0
        self._generated: dict = {}
        self._worker: LoreWizardWorker | None = None
        self._result: dict | None = None
        self._chip_buttons: list = []

        self.setWindowTitle(title or f"{lore_wizard.kind_label(self.kind)} wizard")
        self.resize(560, 540)

        root = QVBoxLayout(self)
        self.stack = QStackedWidget()
        root.addWidget(self.stack, 1)

        self._build_intro()
        self._build_busy()
        self._build_question()
        self._build_preview()

        install_spellcheck_subtree(self)
        self.stack.setCurrentIndex(self.PAGE_INTRO)
        if seed:
            self.seed_edit.setText(seed)

    def result_fields(self) -> dict:
        return dict(self._result or {})

    def replace_mode(self) -> bool:
        return self.replace_cb.isChecked()

    def selected_kind(self) -> str:
        return self.kind

    def _build_intro(self):
        page = QWidget()
        v = QVBoxLayout(page)
        self.intro_label = QLabel(
            "Answer a short interview, then preview the generated card. "
            "Empty fields are filled; checked Replace overwrites existing text.")
        self.intro_label.setWordWrap(True)
        v.addWidget(self.intro_label)
        if self._pick_type:
            self.type_combo = QComboBox()
            for key, label, _bucket in lore_types.ENTRY_TYPES:
                self.type_combo.addItem(label, key)
            idx = self.type_combo.findData(self.kind)
            if idx >= 0:
                self.type_combo.setCurrentIndex(idx)
            self.type_combo.currentIndexChanged.connect(self._on_type_picked)
            v.addWidget(QLabel("Entry type"))
            v.addWidget(self.type_combo)
        v.addWidget(QLabel("Name or seed idea"))
        self.seed_edit = QLineEdit()
        self.seed_edit.setPlaceholderText("Ada Voss — reluctant scout…")
        if self.existing.get("name"):
            self.seed_edit.setText(str(self.existing.get("name")))
        v.addWidget(self.seed_edit)
        v.addWidget(QLabel("Optional notes for the model"))
        self.notes_edit = QPlainTextEdit()
        self.notes_edit.setPlaceholderText("Anything the interview should know…")
        self.notes_edit.setMaximumHeight(90)
        v.addWidget(self.notes_edit)
        v.addStretch()
        row = QHBoxLayout()
        row.addStretch()
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        start = QPushButton("Start interview")
        start.setDefault(True)
        start.clicked.connect(self._start_questions)
        row.addWidget(cancel)
        row.addWidget(start)
        v.addLayout(row)
        self.stack.addWidget(page)

    def _build_busy(self):
        page = QWidget()
        v = QVBoxLayout(page)
        self.busy_label = QLabel("Talking to the model…")
        self.busy_label.setWordWrap(True)
        v.addWidget(self.busy_label)
        v.addStretch()
        row = QHBoxLayout()
        row.addStretch()
        stop = QPushButton("Stop")
        stop.setProperty("danger", True)
        stop.clicked.connect(self._cancel_worker)
        row.addWidget(stop)
        v.addLayout(row)
        self.stack.addWidget(page)

    def _build_question(self):
        page = QWidget()
        v = QVBoxLayout(page)
        self.step_label = QLabel("")
        self.step_label.setProperty("muted", True)
        v.addWidget(self.step_label)
        self.question_label = QLabel("")
        self.question_label.setWordWrap(True)
        v.addWidget(self.question_label)
        self.chip_host = QWidget()
        self.chip_layout = FlowLayout(self.chip_host, hspacing=6, vspacing=4)
        v.addWidget(self.chip_host)
        self.answer_edit = QPlainTextEdit()
        self.answer_edit.setPlaceholderText("Your answer (chips add to this)…")
        self.answer_edit.setMaximumHeight(120)
        v.addWidget(self.answer_edit)
        v.addStretch()
        row = QHBoxLayout()
        self.back_btn = QPushButton("Back")
        self.back_btn.clicked.connect(self._back)
        self.skip_btn = QPushButton("Skip")
        self.skip_btn.setProperty("secondary", True)
        self.skip_btn.clicked.connect(self._skip)
        self.next_btn = QPushButton("Next")
        self.next_btn.setDefault(True)
        self.next_btn.clicked.connect(self._next)
        row.addWidget(self.back_btn)
        row.addStretch()
        row.addWidget(self.skip_btn)
        row.addWidget(self.next_btn)
        v.addLayout(row)
        self.stack.addWidget(page)

    def _build_preview(self):
        page = QWidget()
        v = QVBoxLayout(page)
        v.addWidget(QLabel("Preview — apply these fields to the card."))
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        v.addWidget(self.preview, 1)
        self.replace_cb = QCheckBox("Replace existing fields (otherwise fill blanks only)")
        self.replace_cb.toggled.connect(self._refresh_preview)
        v.addWidget(self.replace_cb)
        row = QHBoxLayout()
        back = QPushButton("Back to interview")
        back.setProperty("secondary", True)
        back.clicked.connect(self._return_to_questions)
        row.addWidget(back)
        row.addStretch()
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        self.apply_btn = QPushButton("Apply")
        self.apply_btn.setDefault(True)
        self.apply_btn.clicked.connect(self._apply)
        row.addWidget(cancel)
        row.addWidget(self.apply_btn)
        v.addLayout(row)
        self.stack.addWidget(page)

    def _on_type_picked(self):
        self.kind = self.type_combo.currentData() or "character"
        self.setWindowTitle(f"{lore_wizard.kind_label(self.kind)} wizard")

    def _seed_text(self) -> str:
        seed = self.seed_edit.text().strip()
        extra = self.notes_edit.toPlainText().strip()
        if extra:
            seed = (seed + "\n\n" + extra).strip() if seed else extra
        return seed

    def _start_questions(self):
        if self._pick_type:
            self.kind = self.type_combo.currentData() or self.kind
        self._set_busy("Drafting interview questions…")
        self._run_worker("questions")

    def _run_worker(self, phase: str):
        if self._worker and self._worker.isRunning():
            return
        self.app.engine.clear_cancel()
        self._worker = LoreWizardWorker(
            self.app, phase, self.kind, seed=self._seed_text(),
            existing=self.existing, answers=dict(self._answers))
        self._worker.finished_ok.connect(
            self._on_worker_done, Qt.ConnectionType.QueuedConnection)
        self._worker.finished.connect(self._worker.deleteLater)
        self._worker.start()

    def _on_worker_done(self, cancelled: bool, payload):
        self._worker = None
        try:
            self._finish_worker(cancelled, payload)
        except Exception:
            from src.logutil import get_logger
            get_logger("lore_wizard").exception("Wizard UI failed after interview")
            self.stack.setCurrentIndex(self.PAGE_INTRO)
            if self.app:
                self.app.show_toast("Wizard interview failed. Try again.", error=True)

    def _finish_worker(self, cancelled: bool, payload):
        if not self.isVisible():
            return
        if cancelled:
            self.stack.setCurrentIndex(self.PAGE_INTRO)
            return
        if self.stack.currentIndex() != self.PAGE_BUSY:
            return
        if isinstance(payload, list):
            self._questions = [
                q for q in payload if isinstance(q, dict) and q.get("prompt")
            ] or lore_wizard.fallback_questions(self.kind)
            self._index = 0
            self._show_question()
        elif isinstance(payload, dict):
            self._generated = payload
            self._refresh_preview()
            self.stack.setCurrentIndex(self.PAGE_PREVIEW)
        else:
            self.stack.setCurrentIndex(self.PAGE_INTRO)

    def _set_busy(self, message: str):
        self.busy_label.setText(message)
        self.stack.setCurrentIndex(self.PAGE_BUSY)

    def _cancel_worker(self):
        self.app.engine.request_cancel()

    def _show_question(self):
        try:
            self._show_question_body()
        except Exception:
            from src.logutil import get_logger
            get_logger("lore_wizard").exception("Wizard question page failed")
            self.stack.setCurrentIndex(self.PAGE_INTRO)
            if self.app:
                self.app.show_toast("Wizard interview failed. Try again.", error=True)

    def _show_question_body(self):
        if not self._questions:
            self._questions = lore_wizard.fallback_questions(self.kind)
        if self._index >= len(self._questions):
            self._set_busy("Filling the card from your answers…")
            self._run_worker("fill")
            return
        q = self._questions[self._index]
        prompt = str(q.get("prompt") or "").strip() or "Continue?"
        qid = str(q.get("id") or f"q{self._index + 1}")
        self.step_label.setText(f"Question {self._index + 1} of {len(self._questions)}")
        self.question_label.setText(prompt)
        self.back_btn.setEnabled(self._index > 0)
        last = self._index == len(self._questions) - 1
        self.next_btn.setText("Fill card" if last else "Next")
        saved = self._answers.get(qid, {})
        self.answer_edit.setPlainText(str(saved.get("text") or ""))
        chips = saved.get("chips") if isinstance(saved.get("chips"), list) else []
        self._rebuild_chips(q, chips)
        self.stack.setCurrentIndex(self.PAGE_QUESTION)

    def _rebuild_chips(self, question: dict, selected: list):
        while self.chip_layout.count():
            item = self.chip_layout.takeAt(0)
            if item is None:
                break
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
        self._chip_buttons = []
        raw_chips = question.get("chips") or []
        if not isinstance(raw_chips, list):
            raw_chips = [raw_chips]
        selected_l = {str(s).strip().lower() for s in (selected or [])}
        for label in raw_chips:
            text = str(label).strip()
            if not text:
                continue
            btn = QPushButton(text, self.chip_host)
            btn.setCheckable(True)
            btn.setProperty("secondary", True)
            if text.lower() in selected_l:
                btn.setChecked(True)
            btn.toggled.connect(lambda checked, b=btn: self._on_chip_toggled(b, checked))
            self.chip_layout.addWidget(btn)
            self._chip_buttons.append(btn)

    def _question_multi(self) -> bool:
        if 0 <= self._index < len(self._questions):
            return bool(self._questions[self._index].get("multi"))
        return False

    def _set_answer_text(self, text: str):
        self.answer_edit.setPlainText(text)

    def _on_chip_toggled(self, btn, checked: bool):
        label = btn.text().strip()
        if not label:
            return
        if checked and not self._question_multi():
            for other in self._chip_buttons:
                if other is btn or not other.isChecked():
                    continue
                other.blockSignals(True)
                other.setChecked(False)
                other.blockSignals(False)
                self._set_answer_text(
                    lore_wizard.remove_chip_phrase(
                        self.answer_edit.toPlainText(), other.text()))
        current = self.answer_edit.toPlainText()
        if checked:
            self._set_answer_text(lore_wizard.insert_chip_phrase(current, label))
        else:
            self._set_answer_text(lore_wizard.remove_chip_phrase(current, label))

    def _store_answer(self, skipped: bool = False):
        if self._index < 0 or self._index >= len(self._questions):
            return
        q = self._questions[self._index]
        qid = str(q.get("id") or f"q{self._index + 1}")
        chips = [b.text() for b in self._chip_buttons if b.isChecked()]
        text = "" if skipped else self.answer_edit.toPlainText().strip()
        if skipped:
            chips = []
        self._answers[qid] = {
            "id": qid,
            "prompt": str(q.get("prompt") or ""),
            "chips": chips,
            "text": text,
        }

    def _back(self):
        self._store_answer()
        if self._index > 0:
            self._index -= 1
            self._show_question()

    def _skip(self):
        self._store_answer(skipped=True)
        self._index += 1
        self._show_question()

    def _next(self):
        self._store_answer()
        self._index += 1
        self._show_question()

    def _return_to_questions(self):
        if self._questions:
            self._index = max(0, len(self._questions) - 1)
            self._show_question()
        else:
            self.stack.setCurrentIndex(self.PAGE_INTRO)

    def _merged_preview(self) -> dict:
        return lore_wizard.merge_without_clobber(
            self.existing, self._generated, replace=self.replace_cb.isChecked())

    def _refresh_preview(self):
        generated = lore_wizard.fill_has_content(self._generated)
        merged = self._merged_preview()
        text = lore_wizard.preview_fields(merged) if generated else ""
        if not generated:
            text = (
                "Nothing usable came back from the model. "
                "Go back and add more interview answers, then fill again."
            )
        self.preview.setPlainText(text)
        self.apply_btn.setEnabled(generated)

    def _apply(self):
        if not lore_wizard.fill_has_content(self._generated):
            if self.app:
                self.app.show_toast(
                    "Wizard produced no fields to apply.", error=True)
            return
        self._result = self._merged_preview()
        self.accept()

    def reject(self):
        worker = self._worker
        if worker is not None and worker.isRunning():
            self.app.engine.request_cancel()
            try:
                worker.finished_ok.disconnect(self._on_worker_done)
            except (RuntimeError, TypeError):
                pass
            _orphan_worker(worker)
        self._worker = None
        super().reject()
