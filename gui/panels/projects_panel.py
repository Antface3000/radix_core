"""Projects panel - create / switch / rename / delete isolated workspaces."""

import customtkinter as ctk

from gui import theme
from gui.panels.base import BasePanel
from src import projects


class ProjectsPanel(BasePanel):
    title = "Projects"

    def __init__(self, master, app):
        super().__init__(master, app)
        self.grid_rowconfigure(2, weight=1)
        self.header("Projects", "Each project is a self-contained world: lore, "
                                "story bible, world state, images, and agent overrides.")
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.grid(row=1, column=0, sticky="ew", padx=20, pady=8)
        ctk.CTkButton(bar, text="+ New Project", command=self._new).pack(side="left")
        ctk.CTkButton(bar, text="Refresh", command=self.on_show, width=90,
                      **theme.secondary_btn()).pack(side="left", padx=8)

        self.list_frame = ctk.CTkScrollableFrame(self, fg_color=theme.BG_CARD)
        self.list_frame.grid(row=2, column=0, sticky="nsew", padx=20, pady=(4, 16))
        self.list_frame.grid_columnconfigure(0, weight=1)
        self.on_show()

    def on_show(self):
        for w in self.list_frame.winfo_children():
            w.destroy()
        active = projects.get_active_project_id()
        for i, project in enumerate(projects.list_projects()):
            self._row(i, project, project["id"] == active)

    def _row(self, i, project, is_active):
        row = ctk.CTkFrame(self.list_frame, fg_color=theme.BG_SIDEBAR)
        row.grid(row=i, column=0, sticky="ew", pady=4, padx=4)
        row.grid_columnconfigure(0, weight=1)
        label = project["name"] + ("   (active)" if is_active else "")
        ctk.CTkLabel(row, text=label, anchor="w",
                     font=ctk.CTkFont(size=15, weight="bold" if is_active else "normal"),
                     text_color=theme.LIME if is_active else theme.TEXT_PRIMARY
                     ).grid(row=0, column=0, sticky="w", padx=12, pady=10)
        if not is_active:
            ctk.CTkButton(row, text="Open", width=70,
                          command=lambda p=project: self._switch(p)
                          ).grid(row=0, column=1, padx=4, pady=8)
        ctk.CTkButton(row, text="Rename", width=80, **theme.secondary_btn(),
                      command=lambda p=project: self._rename(p)
                      ).grid(row=0, column=2, padx=4, pady=8)
        if not is_active:
            ctk.CTkButton(row, text="Delete", width=80, **theme.danger_btn(),
                          command=lambda p=project: self._delete(p)
                          ).grid(row=0, column=3, padx=(4, 8), pady=8)

    def _new(self):
        dlg = ctk.CTkInputDialog(text="Name the new project:", title="New Project")
        name = dlg.get_input()
        if not name:
            return
        project = projects.create_project(name)
        self.app.switch_project(project["id"])
        self.on_show()

    def _switch(self, project):
        self.app.switch_project(project["id"])
        self.on_show()

    def _rename(self, project):
        dlg = ctk.CTkInputDialog(text="New name:", title="Rename Project")
        name = dlg.get_input()
        if not name:
            return
        projects.rename_project(project["id"], name)
        self.app.refresh_header()
        self.on_show()

    def _delete(self, project):
        try:
            projects.delete_project(project["id"])
            self.app.status(f"Deleted project '{project['name']}'.")
        except ValueError as exc:
            self.app.status(str(exc))
        self.on_show()
