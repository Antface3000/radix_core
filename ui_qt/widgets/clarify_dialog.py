"""Single batched dialog for Liaison / ambiguity clarifying questions."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)


class ClarifyDialog(QDialog):
    """Shows all clarifying questions at once with a prominent skip option.

    Result states after exec():
        skipped   -> user chose "Run as-is" (proceed, no answers)
        accepted  -> proceed with whatever answers were given
        rejected  -> cancel the run entirely
    """

    def __init__(self, parent, questions: list[str], *,
                 title: str = "Liaison — clarify before running",
                 preamble: str = ""):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(480)
        self.skipped = False
        self._fields: list[tuple[str, QLineEdit]] = []
        self._freeform: QPlainTextEdit | None = None

        v = QVBoxLayout(self)
        if preamble:
            pre = QLabel(preamble)
            pre.setWordWrap(True)
            v.addWidget(pre)
        hint = QLabel(
            "Answer any of these to sharpen the result — or run as-is. "
            "Blank answers are simply skipped.")
        hint.setWordWrap(True)
        hint.setProperty("muted", True)
        v.addWidget(hint)

        if questions:
            form = QFormLayout()
            for q in questions:
                field = QLineEdit()
                label = QLabel(q)
                label.setWordWrap(True)
                form.addRow(label, field)
                self._fields.append((q, field))
            v.addLayout(form)
        else:
            self._freeform = QPlainTextEdit()
            self._freeform.setPlaceholderText("Your answer…")
            self._freeform.setMaximumHeight(120)
            v.addWidget(self._freeform)

        buttons = QDialogButtonBox()
        skip_btn = QPushButton("Run as-is")
        skip_btn.setToolTip("Proceed without answering")
        buttons.addButton(skip_btn, QDialogButtonBox.ActionRole)
        ok_btn = QPushButton("Answer && run")
        ok_btn.setDefault(True)
        buttons.addButton(ok_btn, QDialogButtonBox.AcceptRole)
        cancel_btn = QPushButton("Cancel run")
        cancel_btn.setProperty("secondary", True)
        buttons.addButton(cancel_btn, QDialogButtonBox.RejectRole)
        skip_btn.clicked.connect(self._on_skip)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        v.addWidget(buttons)

    def _on_skip(self):
        self.skipped = True
        self.accept()

    def answers(self) -> list[tuple[str, str]]:
        """(question, answer) pairs for non-blank answers."""
        if self.skipped:
            return []
        out = []
        for q, field in self._fields:
            text = field.text().strip()
            if text:
                out.append((q, text))
        if self._freeform is not None:
            text = self._freeform.toPlainText().strip()
            if text:
                out.append(("", text))
        return out

    def freeform_answer(self) -> str:
        """Single combined answer string (for ask_user callbacks)."""
        parts = [f"{q}: {a}" if q else a for q, a in self.answers()]
        return "\n".join(parts)


def ask_clarifications(parent, questions: list[str], *,
                       title: str = "Liaison — clarify before running",
                       preamble: str = "") -> tuple[bool, list[tuple[str, str]]]:
    """Show the batched dialog. Returns (proceed, answers)."""
    dlg = ClarifyDialog(parent, questions, title=title, preamble=preamble)
    if dlg.exec() != QDialog.Accepted:
        return False, []
    return True, dlg.answers()
