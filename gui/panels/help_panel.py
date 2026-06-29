"""In-app Help panel - renders USER_GUIDE.txt / INSTALL.txt as plain text."""

import os

import customtkinter as ctk

import config
from gui import theme
from gui.panels.base import BasePanel
from gui.tooltip import attach

_DOCS = [
    ("User Guide", config.USER_GUIDE_PATH),
    ("Installation", config.INSTALL_PATH),
]


class HelpPanel(BasePanel):
    title = "Help"

    def __init__(self, master, app):
        super().__init__(master, app)
        self.grid_rowconfigure(2, weight=1)
        self.grid_columnconfigure(0, weight=1)
        self.header("Help & Documentation",
                    "User guide and Windows installation tutorial. Model download "
                    "URLs are in User Guide section 13 and INSTALL.txt sections "
                    "7, 9, and 10.")

        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.grid(row=1, column=0, sticky="ew", padx=20, pady=(0, 4))
        self.doc_switch = ctk.CTkSegmentedButton(
            bar, values=[name for name, _ in _DOCS],
            command=lambda _v: self._render())
        self.doc_switch.set(_DOCS[0][0])
        self.doc_switch.pack(side="left")
        attach(self.doc_switch, "Switch between the User Guide and the Windows "
                                "Installation tutorial.")

        self.body = ctk.CTkTextbox(self, wrap="word", font=("Segoe UI", 13),
                                   fg_color=theme.BG_INPUT)
        self.body.grid(row=2, column=0, sticky="nsew", padx=20, pady=(4, 16))
        self._render()

    def show_doc(self, name):
        """Public: open a specific doc (used by the startup launcher / marquee)."""
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
        path = self._path()
        self.body.configure(state="normal")
        self.body.delete("1.0", "end")
        if not os.path.exists(path):
            self.body.insert("1.0", f"Documentation file not found:\n{path}\n\n"
                                    "It should ship alongside the app.")
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

    def on_show(self):
        self._render()
