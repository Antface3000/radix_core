"""In-app Help panel - renders USER_GUIDE.txt / INSTALL.txt as plain text."""

import os
import threading
import time

import customtkinter as ctk

import config
from gui import theme
from gui import panel_text
from gui.panels.base import BasePanel
from gui.tooltip import attach
from src import updater

_DOCS = [
    ("User Guide", config.USER_GUIDE_PATH),
    ("Installation", config.INSTALL_PATH),
    ("About & Updates", None),
]


class HelpPanel(BasePanel):
    title = "Help"

    def __init__(self, master, app):
        super().__init__(master, app)
        self.grid_rowconfigure(2, weight=1)
        self.grid_columnconfigure(0, weight=1)
        self._update_result = None
        self.header("Help & Documentation",
                    "User guide, installation tutorial, and version updates.")

        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.grid(row=1, column=0, sticky="ew", padx=20, pady=(0, 4))
        self.doc_switch = ctk.CTkSegmentedButton(
            bar, values=[name for name, _ in _DOCS],
            command=lambda _v: self._render())
        self.doc_switch.set(_DOCS[0][0])
        theme.style_segmented_button(self.doc_switch)
        self.doc_switch.pack(side="left")
        attach(self.doc_switch, "Switch between docs, install guide, and updates.")

        self.body = panel_text.new_textbox(
            self, self.app.settings, wrap="word", fg_color=theme.BG_INPUT)
        self.body.grid(row=2, column=0, sticky="nsew", padx=20, pady=(4, 8))

        self.about_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.about_frame.grid(row=2, column=0, sticky="nsew", padx=20, pady=(4, 8))
        self.about_frame.grid_columnconfigure(0, weight=1)
        self.about_frame.grid_remove()

        ctk.CTkLabel(
            self.about_frame,
            text=f"Radix Core  v{config.APP_VERSION}",
            font=ctk.CTkFont(size=20, weight="bold"),
            text_color=theme.LIME,
        ).grid(row=0, column=0, sticky="w", pady=(0, 8))

        install_type = "Git clone" if updater.is_git_install() else "Zip / folder install"
        ctk.CTkLabel(
            self.about_frame, text=f"Install type: {install_type}",
            text_color=theme.TEXT_MUTED, anchor="w",
        ).grid(row=1, column=0, sticky="w")

        self.update_status = ctk.CTkLabel(
            self.about_frame, text="Update status: not checked yet",
            anchor="w", justify="left", wraplength=520)
        self.update_status.grid(row=2, column=0, sticky="ew", pady=(8, 8))

        btn_row = ctk.CTkFrame(self.about_frame, fg_color="transparent")
        btn_row.grid(row=3, column=0, sticky="w", pady=(0, 8))
        self.check_btn = ctk.CTkButton(
            btn_row, text="Check for updates", command=self._check_updates,
            **theme.secondary_btn())
        self.check_btn.pack(side="left", padx=(0, 8))
        self.update_btn = ctk.CTkButton(
            btn_row, text="Update now", command=self._apply_update, state="disabled",
            **theme.primary_btn())
        self.update_btn.pack(side="left", padx=(0, 8))
        ctk.CTkButton(
            btn_row, text="View changelog", command=self._view_changelog,
            **theme.ghost_btn()).pack(side="left")

        ctk.CTkLabel(
            self.about_frame,
            text="You can also double-click update.bat in the app folder.\n"
                 "Updates preserve data/, models/, .venv/, and assets/piper/.",
            text_color=theme.TEXT_MUTED, justify="left", anchor="w",
        ).grid(row=4, column=0, sticky="w", pady=(8, 0))

        self._render()

    def show_doc(self, name):
        if name in (n for n, _ in _DOCS):
            self.doc_switch.set(name)
            self._render()

    def _path(self):
        name = self.doc_switch.get()
        for n, p in _DOCS:
            if n == name:
                return p
        return _DOCS[0][1]

    def _render(self):
        name = self.doc_switch.get()
        if name == "About & Updates":
            self.body.grid_remove()
            self.about_frame.grid()
            return
        self.about_frame.grid_remove()
        self.body.grid()
        path = self._path()
        self.body.configure(state="normal")
        self.body.delete("1.0", "end")
        if not path or not os.path.exists(path):
            self.body.insert("1.0", f"Documentation file not found:\n{path}\n")
            self.body.configure(state="disabled")
            return
        try:
            with open(path, "r", encoding="utf-8") as fh:
                text = fh.read()
        except Exception as exc:
            self.body.insert("1.0", f"Could not read {path}:\n{exc}")
            self.body.configure(state="disabled")
            return
        self.body.insert("1.0", text)
        self.body.configure(state="disabled")

    def _view_changelog(self):
        self.about_frame.grid_remove()
        self.body.grid()
        self.body.configure(state="normal")
        self.body.delete("1.0", "end")
        if os.path.exists(config.CHANGELOG_PATH):
            with open(config.CHANGELOG_PATH, "r", encoding="utf-8") as fh:
                self.body.insert("1.0", fh.read())
        else:
            self.body.insert("1.0", "CHANGELOG.txt not found.")
        self.body.configure(state="disabled")

    def _check_updates(self):
        self.check_btn.configure(state="disabled")
        self.update_status.configure(text="Checking for updates...")

        def worker():
            try:
                result = updater.check_for_update()
                err = None
            except Exception as exc:
                result = None
                err = str(exc)
            self.after(0, lambda: self._show_update_result(result, err))

        threading.Thread(target=worker, daemon=True).start()

    def _show_update_result(self, result, err):
        self.check_btn.configure(state="normal")
        self.app.settings.set("updates.last_check_ts", time.time(), save=True)
        if err:
            self.update_status.configure(text=f"Could not check: {err}")
            self.update_btn.configure(state="disabled")
            return
        if result is None:
            self.update_status.configure(
                text="Could not reach update source (offline or private repo). "
                     f"See {config.RELEASES_URL}")
            self.update_btn.configure(state="disabled")
            return
        self._update_result = result
        if result.available:
            self.update_status.configure(
                text=f"Update available: v{result.remote_version} "
                     f"(you have v{result.local_version}).\n{result.summary}")
            self.update_btn.configure(state="normal")
        else:
            self.update_status.configure(
                text=f"Up to date (v{result.local_version}).")
            self.update_btn.configure(state="disabled")

    def _apply_update(self):
        updater.apply_update()
        self.app.destroy()

    def on_show(self):
        self._render()
