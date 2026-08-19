"""Add Ons — enable packs and install them from this panel."""

from __future__ import annotations

import os

from PySide6.QtGui import QDesktopServices
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import (
    QVBoxLayout, QLabel, QPushButton, QFormLayout, QLineEdit,
    QGroupBox, QWidget, QCheckBox, QHBoxLayout, QFileDialog,
    QPlainTextEdit, QScrollArea,
)

from src.plugins import extra_paths, is_enabled
from src import pack_install
from ui_qt.panels.base import BasePanel
from ui_qt.workers import PackInstallWorker


COMFY_HELP = "https://github.com/comfyanonymous/ComfyUI?tab=readme-ov-file#installing"


class AddOnsPanel(BasePanel):
    title = "Add Ons"

    def __init__(self, app, parent=None):
        super().__init__(app, parent)
        self._worker: PackInstallWorker | None = None
        outer = QVBoxLayout(self)
        intro = QLabel(
            "The writing studio works without these. Turn a pack on, then use "
            "the Install buttons on that card. Downloads stay on this machine.")
        intro.setWordWrap(True)
        outer.addWidget(intro)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        body = QWidget()
        layout = QVBoxLayout(body)

        layout.addWidget(self._build_llm_card())
        layout.addWidget(self._build_image_card())
        layout.addWidget(self._build_audio_card())
        layout.addWidget(self._build_extra_card())
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(140)
        self.log.setPlaceholderText("Install progress appears here…")
        layout.addWidget(QLabel("Progress"))
        layout.addWidget(self.log)
        layout.addStretch()
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)
        self.refresh_status()

    def _build_llm_card(self) -> QWidget:
        box = QGroupBox("Local LLM — Write, Chat, Team")
        v = QVBoxLayout(box)
        self.llm_enable = QCheckBox("Enable Local LLM pack")
        self.llm_enable.toggled.connect(lambda on: self._toggle("llm", on))
        v.addWidget(self.llm_enable)
        self.llm_status = QLabel("")
        self.llm_status.setWordWrap(True)
        v.addWidget(self.llm_status)
        row = QHBoxLayout()
        llama_btn = QPushButton("1. Install inference engine")
        llama_btn.setToolTip("Installs a prebuilt llama-cpp-python wheel (GPU if NVIDIA, else CPU).")
        llama_btn.clicked.connect(lambda: self._run_install("llama"))
        row.addWidget(llama_btn)
        models_btn = QPushButton("2. Download writing models (~15 GB)")
        models_btn.setToolTip("Downloads all three GGUF files into models/. Needs the pack enabled.")
        models_btn.clicked.connect(lambda: self._run_install("models"))
        row.addWidget(models_btn)
        v.addLayout(row)
        row2 = QHBoxLayout()
        for key, label in (
                ("architect", "Architect only"),
                ("operator", "Operator only"),
                ("flavor", "Flavor only")):
            btn = QPushButton(label)
            btn.setProperty("secondary", True)
            btn.clicked.connect(lambda _=False, k=key: self._run_install("models", keys=[k]))
            row2.addWidget(btn)
        v.addLayout(row2)
        hint = QLabel(
            "Start with Architect if you only want Write. Add Operator for Team "
            "jobs, Flavor for critics. You can keep using the studio while this runs.")
        hint.setWordWrap(True)
        hint.setProperty("muted", True)
        v.addWidget(hint)
        return box

    def _build_image_card(self) -> QWidget:
        box = QGroupBox("Image — Visualize / Image Gen (ComfyUI)")
        v = QVBoxLayout(box)
        self.image_enable = QCheckBox("Enable Image pack")
        self.image_enable.toggled.connect(lambda on: self._toggle("image", on))
        v.addWidget(self.image_enable)
        self.image_status = QLabel("")
        self.image_status.setWordWrap(True)
        v.addWidget(self.image_status)
        form = QFormLayout()
        folder_row = QHBoxLayout()
        self.comfy_dir = QLineEdit()
        browse = QPushButton("Browse…")
        browse.clicked.connect(lambda: self._browse_dir(self.comfy_dir))
        folder_row.addWidget(self.comfy_dir, 1)
        folder_row.addWidget(browse)
        form.addRow("ComfyUI folder", folder_row)
        v.addLayout(form)
        row = QHBoxLayout()
        save = QPushButton("Save folder")
        save.clicked.connect(self._save_image)
        row.addWidget(save)
        detect = QPushButton("Auto-detect")
        detect.clicked.connect(self._detect_comfy)
        row.addWidget(detect)
        launch = QPushButton("Launch ComfyUI")
        launch.clicked.connect(self._launch_comfy)
        row.addWidget(launch)
        sync = QPushButton("Sync assets")
        sync.clicked.connect(self._sync_assets)
        row.addWidget(sync)
        v.addLayout(row)
        help_btn = QPushButton("How to install ComfyUI…")
        help_btn.setProperty("secondary", True)
        help_btn.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(COMFY_HELP)))
        v.addWidget(help_btn)
        return box

    def _build_audio_card(self) -> QWidget:
        box = QGroupBox("Audio — Listen / speech (not music)")
        v = QVBoxLayout(box)
        self.audio_enable = QCheckBox("Enable Audio pack")
        self.audio_enable.toggled.connect(lambda on: self._toggle("audio", on))
        v.addWidget(self.audio_enable)
        self.audio_status = QLabel("")
        self.audio_status.setWordWrap(True)
        v.addWidget(self.audio_status)
        piper_btn = QPushButton("Install Piper (offline speech, small download)")
        piper_btn.clicked.connect(lambda: self._run_install("piper"))
        v.addWidget(piper_btn)
        form = QFormLayout()
        at_row = QHBoxLayout()
        self.alltalk_dir = QLineEdit()
        browse = QPushButton("Browse…")
        browse.clicked.connect(lambda: self._browse_dir(self.alltalk_dir))
        at_row.addWidget(self.alltalk_dir, 1)
        at_row.addWidget(browse)
        form.addRow("AllTalk folder (optional)", at_row)
        v.addLayout(form)
        row = QHBoxLayout()
        save = QPushButton("Save AllTalk folder")
        save.clicked.connect(self._save_audio)
        row.addWidget(save)
        launch = QPushButton("Launch AllTalk")
        launch.clicked.connect(self._launch_alltalk)
        row.addWidget(launch)
        v.addLayout(row)
        return box

    def _build_extra_card(self) -> QWidget:
        box = QGroupBox("Extra plugins (optional)")
        v = QVBoxLayout(box)
        hint = QLabel(
            "Drop-in folders. A grammar checker is a file named radix_grammar.py "
            "with check(text). Not required.")
        hint.setWordWrap(True)
        v.addWidget(hint)
        self.extra_edit = QLineEdit()
        self.extra_edit.setPlaceholderText("Folder path")
        row = QHBoxLayout()
        row.addWidget(self.extra_edit, 1)
        browse = QPushButton("Browse…")
        browse.clicked.connect(lambda: self._browse_extra())
        row.addWidget(browse)
        v.addLayout(row)
        save = QPushButton("Save extra path")
        save.clicked.connect(self._save_extra)
        v.addWidget(save)
        return box

    def refresh_status(self):
        info = pack_install.summarize(self.app.settings)
        llm = info["llm"]
        models = ", ".join(
            f"{r['key']}{' ✓' if r['present'] else ' ✗'}" for r in llm["models"])
        self.llm_enable.blockSignals(True)
        self.llm_enable.setChecked(llm["enabled"])
        self.llm_enable.blockSignals(False)
        self.llm_status.setText(
            f"Inference engine: {'ready' if llm['llama'] else 'not installed'}.  "
            f"Models: {llm['models_present']}/{llm['models_total']}  ({models}).")

        image = info["image"]
        self.image_enable.blockSignals(True)
        self.image_enable.setChecked(image["enabled"])
        self.image_enable.blockSignals(False)
        if not self.comfy_dir.text().strip():
            self.comfy_dir.setText(image["folder"])
        self.image_status.setText(
            "ComfyUI folder: " + ("found" if image["folder_ok"] else "not set")
            + (f"  (also found: {image['guesses'][0]})" if image["guesses"] and not image["folder_ok"] else "")
        )

        audio = info["audio"]
        self.audio_enable.blockSignals(True)
        self.audio_enable.setChecked(audio["enabled"])
        self.audio_enable.blockSignals(False)
        if not self.alltalk_dir.text().strip():
            self.alltalk_dir.setText(audio["alltalk_folder"])
        self.audio_status.setText(
            f"Piper: {'ready' if audio['piper'] else 'not installed'}.  "
            f"AllTalk: {'folder set' if audio['alltalk_ok'] else 'optional'}.")

        self.extra_edit.setText(";".join(extra_paths(self.app.settings)))

    def _toggle(self, key: str, on: bool):
        self.app.settings.set(f"plugins.{key}", bool(on), save=True)
        if hasattr(self.app, "apply_plugin_chrome"):
            self.app.apply_plugin_chrome()
        label = {"llm": "Local LLM", "image": "Image", "audio": "Audio"}[key]
        self.app.show_toast(f"{label} pack {'enabled' if on else 'disabled'}.")
        self.refresh_status()

    def _run_install(self, kind: str, keys=None):
        if kind in ("llama", "models") and not is_enabled(self.app.settings, "llm"):
            self.app.show_toast("Enable the Local LLM pack first.", error=True)
            return
        if kind == "piper" and not is_enabled(self.app.settings, "audio"):
            self.app.show_toast("Enable the Audio pack first.", error=True)
            return
        if self._worker and self._worker.isRunning():
            self.app.show_toast("An install is already running.")
            return
        self.log.appendPlainText(f"— starting {kind} —")
        self._worker = PackInstallWorker(kind, {"keys": keys or []})
        self._worker.line.connect(self.log.appendPlainText)
        self._worker.finished_ok.connect(self._install_done)
        self._worker.start()

    def _install_done(self, ok: bool):
        self.log.appendPlainText("Done." if ok else "Finished with errors.")
        self.refresh_status()
        if hasattr(self.app, "apply_plugin_chrome"):
            self.app.apply_plugin_chrome()
        if hasattr(self.app, "_update_mock_pill"):
            self.app._update_mock_pill()

    def _browse_dir(self, line: QLineEdit):
        path = QFileDialog.getExistingDirectory(self, "Choose folder", line.text())
        if path:
            line.setText(path)

    def _browse_extra(self):
        path = QFileDialog.getExistingDirectory(self, "Plugin folder")
        if path:
            self.extra_edit.setText(path)

    def _save_extra(self):
        raw = self.extra_edit.text().strip()
        parts = [p.strip() for p in raw.split(";") if p.strip()]
        self.app.settings.set("plugins.extra_paths", parts, save=True)
        self.app.show_toast("Extra plugin path saved.")

    def _detect_comfy(self):
        found = pack_install.guess_comfy_dirs()
        if not found:
            self.app.show_toast("No ComfyUI folder found. Install it, then Browse.", error=True)
            return
        self.comfy_dir.setText(found[0])
        self._save_image()

    def _save_image(self):
        if not is_enabled(self.app.settings, "image"):
            self.app.show_toast("Enable the Image pack first.", error=True)
            return
        self.app.settings.set("services.comfyui_dir", self.comfy_dir.text().strip())
        self.app.show_toast("Image folder saved.")
        self.refresh_status()

    def _save_audio(self):
        if not is_enabled(self.app.settings, "audio"):
            self.app.show_toast("Enable the Audio pack first.", error=True)
            return
        self.app.settings.set("services.alltalk_dir", self.alltalk_dir.text().strip())
        self.app.show_toast("AllTalk folder saved.")
        self.refresh_status()

    def _launch_comfy(self):
        if not is_enabled(self.app.settings, "image"):
            self.app.show_toast("Enable the Image pack first.", error=True)
            return
        from src import service_launch
        self.app.settings.set("services.comfyui_dir", self.comfy_dir.text().strip())
        try:
            service_launch.launch_comfyui(self.app.settings)
            self.app.show_toast("Launching ComfyUI…")
        except Exception as exc:
            self.app.show_toast(str(exc), error=True)

    def _launch_alltalk(self):
        if not is_enabled(self.app.settings, "audio"):
            self.app.show_toast("Enable the Audio pack first.", error=True)
            return
        from src import service_launch
        self.app.settings.set("services.alltalk_dir", self.alltalk_dir.text().strip())
        try:
            service_launch.launch_alltalk(self.app.settings)
            self.app.show_toast("Launching AllTalk…")
        except Exception as exc:
            self.app.show_toast(str(exc), error=True)

    def _sync_assets(self):
        if not is_enabled(self.app.settings, "image") and not is_enabled(
                self.app.settings, "audio"):
            self.app.show_toast("Enable Image or Audio first.", error=True)
            return
        from src import asset_sync
        _results, summary = asset_sync.run_sync(self.app.settings)
        n = int(summary.get("copied", 0)) + int(summary.get("overwritten", 0))
        self.app.show_toast(f"Synced {n} asset(s).")

    def on_show(self):
        self.refresh_status()
