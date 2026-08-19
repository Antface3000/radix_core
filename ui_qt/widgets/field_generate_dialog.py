"""Prompt dialog for Story Bible field Generate."""

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QPlainTextEdit, QHBoxLayout, QPushButton,
    QComboBox,
)

from src.story_bible_gen import MODE_LABELS
from ui_qt.widgets.spellcheck import install_spellcheck_subtree


class FieldGenerateDialog(QDialog):
    def __init__(self, parent, field_label: str, mode: str):
        super().__init__(parent)
        self.setWindowTitle(f"Generate — {field_label}")
        self.resize(480, 220)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"Field: {field_label}"))
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(MODE_LABELS)
        idx = self.mode_combo.findText(mode)
        if idx >= 0:
            self.mode_combo.setCurrentIndex(idx)
        layout.addWidget(self.mode_combo)
        layout.addWidget(QLabel("What should this field contain?"))
        self.prompt = QPlainTextEdit()
        self.prompt.setPlaceholderText("Describe what you want generated...")
        self.prompt.setMaximumHeight(80)
        layout.addWidget(self.prompt)
        row = QHBoxLayout()
        row.addStretch()
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        run = QPushButton("Run")
        run.setDefault(True)
        run.clicked.connect(self.accept)
        row.addWidget(cancel)
        row.addWidget(run)
        layout.addLayout(row)
        install_spellcheck_subtree(self)
        self.prompt.setFocus()

    def selected_mode(self) -> str:
        return self.mode_combo.currentText()

    def user_prompt(self) -> str:
        return self.prompt.toPlainText().strip()
