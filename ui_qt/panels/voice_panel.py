"""Qt Voice / TTS panel."""

from __future__ import annotations

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QComboBox,
)

import config
from ui_qt.panels.base import BasePanel


class _SpeakWorker(QThread):
    done = Signal(bool, str)

    def __init__(self, tts, text, play):
        super().__init__()
        self.tts = tts
        self.text = text
        self.play = play

    def run(self):
        try:
            result = self.tts.speak(self.text, play=self.play)
            self.done.emit(result is not None, "" if result else "TTS returned nothing")
        except Exception as exc:
            self.done.emit(False, str(exc))


class VoicePanel(BasePanel):
    title = "Voice"

    def __init__(self, app, parent=None):
        super().__init__(app, parent)
        self._worker: _SpeakWorker | None = None
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            "Listen to text via Piper or AllTalk. Set engine in Settings → Services."))
        row = QHBoxLayout()
        self.engine_combo = QComboBox()
        self.engine_combo.addItems(["off", "piper", "alltalk", "auto"])
        eng = app.settings.get("services.tts_engine", config.TTS_ENGINE)
        idx = self.engine_combo.findText(str(eng))
        if idx >= 0:
            self.engine_combo.setCurrentIndex(idx)
        row.addWidget(QLabel("Engine:"))
        row.addWidget(self.engine_combo)
        layout.addLayout(row)
        self.text = QPlainTextEdit()
        self.text.setPlaceholderText("Text to speak, or paste from manuscript...")
        layout.addWidget(self.text, 1)
        btn_row = QHBoxLayout()
        listen = QPushButton("Listen")
        listen.clicked.connect(self._listen)
        from_editor = QPushButton("From editor selection")
        from_editor.setProperty("secondary", True)
        from_editor.clicked.connect(self._from_editor)
        btn_row.addWidget(listen)
        btn_row.addWidget(from_editor)
        layout.addLayout(btn_row)
        self.status = QLabel("Ready.")
        self.status.setProperty("muted", True)
        layout.addWidget(self.status)

    def _from_editor(self):
        ed = self.app.editor
        if not ed:
            return
        sel = ed._selected_text()
        if sel:
            self.text.setPlainText(sel)
        else:
            self.text.setPlainText(ed.editor.toPlainText()[-2000:])

    def _listen(self):
        if self._worker and self._worker.isRunning():
            return
        text = self.text.toPlainText().strip()
        if not text:
            self.app.show_toast("Enter text to speak.", error=True)
            return
        self.app.settings.set("services.tts_engine", self.engine_combo.currentText())
        self.status.setText("Generating speech...")
        self._worker = _SpeakWorker(self.app.tts, text, play=True)
        self._worker.done.connect(self._on_done)
        self._worker.start()

    def _on_done(self, ok: bool, err: str):
        if ok:
            self.status.setText("Playback finished.")
        else:
            self.status.setText(f"Failed: {err}")
            self.app.show_toast(f"TTS failed: {err}", error=True)
