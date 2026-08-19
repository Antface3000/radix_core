"""Qt Projects panel."""

from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QListWidget, QPushButton, QLineEdit, QLabel,
    QInputDialog, QMessageBox, QFileDialog,
)
from ui_qt.panels.base import BasePanel


class ProjectsPanel(BasePanel):
    title = "Projects"

    def __init__(self, app, parent=None):
        super().__init__(app, parent)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Switch or create a writing project."))
        self.list = QListWidget()
        self.list.itemDoubleClicked.connect(self._activate_selected)
        layout.addWidget(self.list)
        row = QHBoxLayout()
        self.name_entry = QLineEdit()
        self.name_entry.setPlaceholderText("New project name...")
        row.addWidget(self.name_entry)
        create_btn = QPushButton("Create")
        create_btn.clicked.connect(self._create)
        row.addWidget(create_btn)
        layout.addLayout(row)
        act_btn = QPushButton("Open selected")
        act_btn.clicked.connect(self._activate_selected)
        layout.addWidget(act_btn)
        backup_btn = QPushButton("Backup to folder…")
        backup_btn.clicked.connect(self._backup)
        layout.addWidget(backup_btn)
        series_btn = QPushButton("Share lore/bible from another project…")
        series_btn.clicked.connect(self._series_share)
        layout.addWidget(series_btn)
        self.refresh()

    def refresh(self):
        self.list.clear()
        active = self.app.engine.project_id
        for p in self.app.engine.list_projects():
            label = p["name"]
            if p["id"] == active:
                label += "  (active)"
            self.list.addItem(label)
            self.list.item(self.list.count() - 1).setData(256, p["id"])

    def _create(self):
        name = self.name_entry.text().strip()
        if not name:
            return
        self.app.engine.create_project(name)
        self.name_entry.clear()
        self.refresh()
        projects = self.app.engine.list_projects()
        for p in projects:
            if p["name"] == name:
                self.app.switch_project(p["id"])
                break
        self.app.show_toast(f"Created and opened project: {name}")

    def _activate_selected(self):
        item = self.list.currentItem()
        if not item:
            return
        pid = item.data(256)
        self.app.switch_project(pid)

    def _backup(self):
        paths = self.app.engine.paths
        if not paths:
            return
        dest = QFileDialog.getExistingDirectory(self, "Backup project to folder")
        if not dest:
            return
        from src import snapshots
        target = snapshots.backup_project_to(paths, dest)
        self.app.show_toast(f"Backup saved to {target}")

    def _series_share(self):
        paths = self.app.engine.paths
        if not paths:
            return
        projects = self.app.engine.list_projects()
        names = [p["name"] for p in projects if p["id"] != self.app.engine.project_id]
        if not names:
            self.app.show_toast("Create another project first.", error=True)
            return
        name, ok = QInputDialog.getItem(
            self, "Series bible",
            "Share lore, Story Bible, and World State from:",
            names, 0, False)
        if not ok:
            return
        parent = next((p["id"] for p in projects if p["name"] == name), None)
        from src import series
        series.set_share_from(paths, parent)
        self.app.engine.set_project(self.app.engine.project_id)
        self.app.show_toast(f"This book now shares canon with {name}.")
