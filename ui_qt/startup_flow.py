"""First-run dialogs: welcome, project launcher, background update check."""

from __future__ import annotations

from PySide6.QtCore import Qt, QThread, Signal, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QListWidget,
    QLineEdit, QCheckBox, QMessageBox,
)

import config
from src import updater


class UpdateCheckWorker(QThread):
    result = Signal(object)

    def run(self):
        try:
            self.result.emit(updater.check_for_update(timeout=6))
        except Exception:
            self.result.emit(None)


def run_startup_flow(window) -> None:
    """Run modal startup UI then optional background update check."""
    settings = window.settings

    if settings.get("ui.show_welcome", True):
        _show_welcome(window)

    if settings.get("ui.show_startup", True):
        _show_project_launcher(window)

    if settings.get("updates.check_on_startup", True):
        _start_update_check(window)


def _show_welcome(window) -> None:
    from ui_qt.widgets.themed_dialog import ThemedDialog

    dlg = ThemedDialog(window)
    dlg.setWindowTitle(f"Welcome to {config.APP_TITLE}")
    dlg.setMinimumWidth(520)
    v = QVBoxLayout(dlg)
    v.setSpacing(10)

    title = QLabel(f"<b>{config.APP_TITLE}</b> v{config.APP_VERSION}")
    title.setProperty("h2", True)
    v.addWidget(title)

    body = QLabel(
        "This is a <b>writing studio</b> first. Story Bible, lore, binder, "
        "and compile work with <b>no AI installed</b>.<br><br>"
        "<b>Optional Add Ons packs</b> unlock the AI toolbar buttons "
        "(Brainstorm, Ask Agent, Summarize, Visualize, Listen) and Team.<br><br>"
        "<b>How to turn AI on</b><br>"
        "1. Open <b>Add Ons</b> on the left rail<br>"
        "2. Check <b>Enable</b> on the pack you want<br>"
        "3. Use that pack’s <b>Install</b> buttons (models / engine / Piper)<br><br>"
        "<b>What each pack unlocks</b><br>"
        "• <b>Local LLM</b> — Write, Chat, Brainstorm, Ask Agent, Summarize, Team<br>"
        "• <b>Image</b> — Visualize / Image Gen (needs ComfyUI)<br>"
        "• <b>Audio</b> — Listen / Voice (Piper or AllTalk)<br><br>"
        "Until a pack is enabled and installed, those buttons will tell you "
        "what to turn on. <b>Help</b> has the full guide."
    )
    body.setWordWrap(True)
    body.setTextFormat(Qt.TextFormat.RichText)
    v.addWidget(body)

    again = QCheckBox("Show this welcome on launch")
    again.setChecked(True)
    v.addWidget(again)

    row = QHBoxLayout()
    open_addons = QPushButton("Open Add Ons")
    open_addons.setToolTip("Enable packs and run Install from there")

    def _go_addons():
        dlg.accept()
        window.ensure_feature("Add Ons")

    open_addons.clicked.connect(_go_addons)
    row.addWidget(open_addons)
    row.addStretch()
    ok = QPushButton("Continue")
    ok.setDefault(True)
    ok.clicked.connect(dlg.accept)
    row.addWidget(ok)
    v.addLayout(row)

    dlg.exec()
    if not again.isChecked():
        window.settings.set("ui.show_welcome", False, save=True)


def _show_project_launcher(window) -> None:
    from src import projects as projects_mod
    from ui_qt.widgets.themed_dialog import ThemedDialog

    dlg = ThemedDialog(window)
    dlg.setWindowTitle("Open a project")
    dlg.setMinimumSize(460, 360)
    v = QVBoxLayout(dlg)
    v.addWidget(QLabel(
        "Choose a project to work in, or create a new one. "
        "Nothing is opened until you pick Open, Create, or Open last."))

    last_id = projects_mod.get_active_project_id()
    lst = QListWidget()
    last_row = 0
    for i, p in enumerate(window.engine.list_projects()):
        label = p["name"]
        if p["id"] == last_id:
            label += "  (last opened)"
            last_row = i
        lst.addItem(label)
        lst.item(lst.count() - 1).setData(Qt.ItemDataRole.UserRole, p["id"])
    if lst.count():
        lst.setCurrentRow(last_row)
    v.addWidget(lst, 1)

    name_row = QHBoxLayout()
    name_entry = QLineEdit()
    name_entry.setPlaceholderText("New project name…")
    name_row.addWidget(name_entry)
    create_btn = QPushButton("Create")
    name_row.addWidget(create_btn)
    v.addLayout(name_row)

    btn_row = QHBoxLayout()
    skip = QPushButton("Open last project")
    skip.setProperty("secondary", True)
    skip.setEnabled(bool(last_id))
    skip.setToolTip("Open the project you used last time")
    none_btn = QPushButton("No project")
    none_btn.setProperty("secondary", True)
    none_btn.setToolTip("Close this window without opening a manuscript")
    open_btn = QPushButton("Open selected")
    btn_row.addWidget(skip)
    btn_row.addWidget(none_btn)
    btn_row.addStretch()
    open_btn.setDefault(True)
    btn_row.addWidget(open_btn)
    v.addLayout(btn_row)

    show_again = QCheckBox("Show project launcher on launch")
    show_again.setChecked(True)
    v.addWidget(show_again)

    opened = {"ok": False}

    def open_selected():
        item = lst.currentItem()
        if item:
            pid = item.data(Qt.ItemDataRole.UserRole)
            if pid:
                window.switch_project(pid)
                opened["ok"] = True
        dlg.accept()

    def open_last():
        if last_id:
            window.switch_project(last_id)
            opened["ok"] = True
        dlg.accept()

    def create_project():
        name = name_entry.text().strip()
        if not name:
            return
        window.engine.create_project(name)
        for p in window.engine.list_projects():
            if p["name"] == name:
                window.switch_project(p["id"])
                opened["ok"] = True
                break
        dlg.accept()

    open_btn.clicked.connect(open_selected)
    create_btn.clicked.connect(create_project)
    skip.clicked.connect(open_last)
    none_btn.clicked.connect(dlg.accept)
    lst.itemDoubleClicked.connect(open_selected)
    dlg.exec()

    if not show_again.isChecked():
        window.settings.set("ui.show_startup", False, save=True)
    if not opened["ok"]:
        window.refresh_header()
        window.refresh_worldbar()
        if window.editor:
            window.editor.on_project_change()


def _start_update_check(window) -> None:
    worker = UpdateCheckWorker(window)
    window._update_check_worker = worker

    def on_result(result):
        if result is None:
            return
        if not getattr(result, "available", False):
            return
        msg = (
            f"A newer version is available: v{result.remote_version} "
            f"(you have v{result.local_version}).\n\n{result.summary}")
        box = QMessageBox(window)
        box.setWindowTitle("Update available")
        box.setText(msg)
        open_rel = box.addButton("View release", QMessageBox.ButtonRole.ActionRole)
        box.addButton(QMessageBox.StandardButton.Ok)
        box.exec()
        if box.clickedButton() == open_rel:
            QDesktopServices.openUrl(QUrl(result.releases_url))

    worker.result.connect(on_result)
    worker.finished.connect(lambda: setattr(window, "_update_check_worker", None))
    worker.start()
