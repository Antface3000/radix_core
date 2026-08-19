"""First-run dialogs: welcome, project launcher, background update check."""

from __future__ import annotations

from PySide6.QtCore import Qt, QThread, Signal, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QListWidget,
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
    dlg = QDialog(window)
    dlg.setWindowTitle(f"Welcome to {config.APP_TITLE}")
    dlg.setMinimumWidth(420)
    v = QVBoxLayout(dlg)
    v.addWidget(QLabel(
        f"<b>{config.APP_TITLE}</b> v{config.APP_VERSION}<br><br>"
        "This is a writing studio. Story Bible, lore, binder, and compile "
        "work with no AI.<br><br>"
        "Want Write/Chat, images, or speech? Open <b>Add Ons</b> on the left, "
        "enable a pack, and use the Install buttons there.<br><br>"
        "<b>Help</b> has the full user guide."))
    again = QCheckBox("Show this welcome on launch")
    again.setChecked(True)
    v.addWidget(again)
    row = QHBoxLayout()
    row.addStretch()
    ok = QPushButton("Continue")
    ok.clicked.connect(dlg.accept)
    row.addWidget(ok)
    v.addLayout(row)
    dlg.exec()
    if not again.isChecked():
        window.settings.set("ui.show_welcome", False, save=True)


def _show_project_launcher(window) -> None:
    dlg = QDialog(window)
    dlg.setWindowTitle("Open a project")
    dlg.setMinimumSize(460, 360)
    v = QVBoxLayout(dlg)
    v.addWidget(QLabel("Choose a project to work in, or create a new one."))

    lst = QListWidget()
    active = window.engine.project_id
    for p in window.engine.list_projects():
        label = p["name"]
        if p["id"] == active:
            label += "  (current)"
        lst.addItem(label)
        lst.item(lst.count() - 1).setData(Qt.ItemDataRole.UserRole, p["id"])
    if lst.count():
        lst.setCurrentRow(0)
    v.addWidget(lst, 1)

    name_row = QHBoxLayout()
    name_entry = QLineEdit()
    name_entry.setPlaceholderText("New project name…")
    name_row.addWidget(name_entry)
    create_btn = QPushButton("Create")
    name_row.addWidget(create_btn)
    v.addLayout(name_row)

    btn_row = QHBoxLayout()
    skip = QPushButton("Continue with current")
    skip.setProperty("secondary", True)
    open_btn = QPushButton("Open selected")
    btn_row.addWidget(skip)
    btn_row.addStretch()
    btn_row.addWidget(open_btn)
    v.addLayout(btn_row)

    show_again = QCheckBox("Show project launcher on launch")
    show_again.setChecked(True)
    v.addWidget(show_again)

    def open_selected():
        item = lst.currentItem()
        if item:
            pid = item.data(Qt.ItemDataRole.UserRole)
            if pid:
                window.switch_project(pid)
        dlg.accept()

    def create_project():
        name = name_entry.text().strip()
        if not name:
            return
        window.engine.create_project(name)
        for p in window.engine.list_projects():
            if p["name"] == name:
                window.switch_project(p["id"])
                break
        dlg.accept()

    open_btn.clicked.connect(open_selected)
    create_btn.clicked.connect(create_project)
    skip.clicked.connect(dlg.accept)
    lst.itemDoubleClicked.connect(open_selected)
    dlg.exec()

    if not show_again.isChecked():
        window.settings.set("ui.show_startup", False, save=True)


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
