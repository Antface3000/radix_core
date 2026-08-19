"""Qt Image Gen panel — ComfyUI integration."""

from __future__ import annotations

import base64
import io

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton,
    QComboBox, QProgressBar,
)

from ui_qt.panels.base import BasePanel


class _RenderWorker(QThread):
    done = Signal(object)  # base64 png or None
    error = Signal(str)
    progress = Signal(str)

    def __init__(self, comfy, text, lore_context, world_state, options):
        super().__init__()
        self.comfy = comfy
        self.text = text
        self.lore_context = lore_context
        self.world_state = world_state
        self.options = options

    def run(self):
        try:
            result = {"data": None}

            def on_image(b64, _pid):
                result["data"] = b64

            def on_progress(msg):
                self.progress.emit(str(msg))

            def on_error(msg):
                self.error.emit(str(msg))

            self.comfy.render(
                self.text,
                lore_context=self.lore_context,
                world_state=self.world_state,
                render_options=self.options,
                on_progress=on_progress,
                on_image=on_image,
                on_error=on_error,
            )
            self.done.emit(result["data"])
        except Exception as exc:
            self.error.emit(str(exc))


class ImageGenPanel(BasePanel):
    title = "Image Gen"

    def __init__(self, app, parent=None):
        super().__init__(app, parent)
        self._worker: _RenderWorker | None = None
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            "Generate images via local ComfyUI. Configure paths in Add Ons → Services."))
        self.prompt = QPlainTextEdit()
        self.prompt.setPlaceholderText("Describe the scene or paste selected manuscript text...")
        self.prompt.setMaximumHeight(100)
        layout.addWidget(self.prompt)
        row = QHBoxLayout()
        self.mode = QComboBox()
        self.mode.addItems(["background", "character"])
        row.addWidget(QLabel("Subject:"))
        row.addWidget(self.mode)
        layout.addLayout(row)
        btn_row = QHBoxLayout()
        self.gen_btn = QPushButton("Generate")
        self.gen_btn.clicked.connect(self._generate)
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setProperty("danger", True)
        self.stop_btn.setEnabled(False)
        btn_row.addWidget(self.gen_btn)
        btn_row.addWidget(self.stop_btn)
        layout.addLayout(btn_row)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.hide()
        layout.addWidget(self.progress)
        self.preview = QLabel("No image yet")
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setMinimumHeight(240)
        self.preview.setProperty("muted", True)
        layout.addWidget(self.preview, 1)
        self.status = QLabel("Ready.")
        self.status.setProperty("muted", True)
        layout.addWidget(self.status)

    def _generate(self):
        if self._worker and self._worker.isRunning():
            return
        text = self.prompt.toPlainText().strip()
        if not text:
            self.app.show_toast("Enter a prompt.", error=True)
            return
        paths = self.app.engine.paths
        lore_ctx = ""
        ws = {}
        if paths:
            from src import world_state as ws_mod
            ws_raw = ws_mod.read(paths["world_state"])
            ws = {
                "location": ws_raw.get("currentLocation", ""),
                "time": ws_raw.get("currentDate", ""),
            }
        options = {"mode": self.mode.currentText(), "subjectKind": self.mode.currentText()}
        self.gen_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.progress.show()
        self.status.setText("Submitting to ComfyUI...")
        self._worker = _RenderWorker(self.app.comfy, text, lore_ctx, ws, options)
        self._worker.progress.connect(lambda m: self.status.setText(m))
        self._worker.error.connect(self._on_error)
        self._worker.done.connect(self._on_done)
        self._worker.start()

    def _on_error(self, msg: str):
        self.progress.hide()
        self.gen_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.status.setText(f"Error: {msg}")
        self.app.show_toast(f"Image gen failed: {msg}", error=True)

    def _on_done(self, b64):
        self.progress.hide()
        self.gen_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        if not b64:
            self.status.setText("No image returned.")
            return
        try:
            raw = base64.b64decode(b64)
            pix = QPixmap()
            pix.loadFromData(raw)
            self.preview.setPixmap(pix.scaled(
                self.preview.width(), self.preview.height(),
                Qt.KeepAspectRatio, Qt.SmoothTransformation))
            self.status.setText("Image ready.")
        except Exception as exc:
            self.status.setText(f"Could not decode image: {exc}")
