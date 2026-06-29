"""World State panel - the current, mutable situation of the world."""

import customtkinter as ctk

from gui import theme
from gui.panels.base import BasePanel, bind_scroll_width
from gui.widgets.generate_field import GenerateRegistry, attach_field_generate
from src import world_state

_SCALARS = [("currentDate", "Current date"), ("currentLocation", "Current location"),
            ("scene", "Scene / time of day")]
_LISTS = [("timeline", "Timeline (one per line)"),
          ("factions", "Factions (one per line)"),
          ("ongoingEvents", "Ongoing events (one per line)"),
          ("facts", "Facts (one per line)")]


class WorldStatePanel(BasePanel):
    title = "World State"

    def __init__(self, master, app):
        super().__init__(master, app)
        self.grid_rowconfigure(1, weight=1)
        self._gen_registry = GenerateRegistry()
        self.header("World State", "Tracks 'now': timeline beats, factions, events, "
                                   "and facts. Injected into agents alongside the bible.")
        self.scroll = ctk.CTkScrollableFrame(self, fg_color=theme.BG_CARD)
        self.scroll.grid(row=1, column=0, sticky="nsew", padx=16, pady=(4, 8))
        self.scroll.grid_columnconfigure(0, weight=1)
        bind_scroll_width(self.scroll)
        self.widgets = {}
        row = 0
        for key, label in _SCALARS:
            block = attach_field_generate(
                self.scroll, app, label, multiline=False,
                context_fn=lambda: "World State tab",
                registry=self._gen_registry,
            )
            block.grid(row=row, column=0, sticky="ew", padx=12, pady=(0, 4))
            self.widgets[key] = block.widget
            row += 1
        for key, label in _LISTS:
            block = attach_field_generate(
                self.scroll, app, label, multiline=True, height=80,
                context_fn=lambda: "World State tab",
                registry=self._gen_registry,
            )
            block.grid(row=row, column=0, sticky="ew", padx=12, pady=(0, 4))
            self.widgets[key] = block.widget
            row += 1
        ctk.CTkButton(self, text="Save World State", command=self._save,
                      **theme.primary_btn()
                      ).grid(row=2, column=0, sticky="e", padx=16, pady=(0, 16))
        self.on_show()

    def on_show(self):
        data = world_state.read(self.app.engine.paths["world_state"])
        for key, _ in _SCALARS:
            self.widgets[key].delete(0, "end")
            self.widgets[key].insert(0, str(data.get(key, "") or ""))
        for key, _ in _LISTS:
            items = data.get(key, [])
            text = "\n".join(i if isinstance(i, str) else
                             (i.get("name") or i.get("text") or str(i))
                             for i in items)
            self.widgets[key].delete("1.0", "end")
            self.widgets[key].insert("1.0", text)

    on_project_change = on_show

    def _save(self):
        patch = {}
        for key, _ in _SCALARS:
            patch[key] = self.widgets[key].get().strip()
        for key, _ in _LISTS:
            lines = [ln.strip() for ln in
                     self.widgets[key].get("1.0", "end").splitlines() if ln.strip()]
            patch[key] = lines
        world_state.write(self.app.engine.paths["world_state"], patch)
        self.app.status("World State saved.")
        if hasattr(self.app, "refresh_worldbar"):
            self.app.refresh_worldbar()
