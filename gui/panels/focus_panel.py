"""Focus extras - a tabbed grab-bag of writing-flow helpers.

    Parking Lot - free-text scratchpad stored in the project config.
    Quick Add   - dump quick lore as "Name: notes" / "world: Place: notes".
    Pre-Flight  - a readiness checklist computed from the project's data.
"""

import customtkinter as ctk

from gui import theme
from gui.panels.base import BasePanel
from gui.tooltip import attach
from src import projects, lore, story_bible, world_state, chapters


class FocusPanel(BasePanel):
    title = "Focus"

    def __init__(self, master, app):
        super().__init__(master, app)
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)
        self.tabs = ctk.CTkTabview(self, fg_color=theme.BG_CARD)
        self.tabs.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)
        for name in ("Parking Lot", "Quick Add", "Pre-Flight"):
            self.tabs.add(name)
        self._build_parking(self.tabs.tab("Parking Lot"))
        self._build_quickadd(self.tabs.tab("Quick Add"))
        self._build_preflight(self.tabs.tab("Pre-Flight"))
        theme.style_tabview(self.tabs)
        self.on_show()

    def _paths(self):
        return self.app.engine.paths

    # ----------------------- Parking Lot -----------------------------------
    def _build_parking(self, tab):
        tab.grid_rowconfigure(1, weight=1)
        tab.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(tab, text="Stray ideas, TODOs, and lines you might use later.",
                     text_color=theme.TEXT_MUTED).grid(row=0, column=0, sticky="w",
                                                      padx=10, pady=(8, 2))
        self.parking_box = ctk.CTkTextbox(tab, wrap="word")
        self.parking_box.grid(row=1, column=0, sticky="nsew", padx=10, pady=4)
        ctk.CTkButton(tab, text="Save", command=self._save_parking,
                      **theme.primary_btn()).grid(row=2, column=0, sticky="e",
                                                  padx=10, pady=8)

    def _load_parking(self):
        cfg = projects.read_json_safe(self._paths()["config"], {})
        self.parking_box.delete("1.0", "end")
        self.parking_box.insert("1.0", cfg.get("parkingLot", ""))

    def _save_parking(self):
        cfg = projects.read_json_safe(self._paths()["config"], {})
        cfg["parkingLot"] = self.parking_box.get("1.0", "end-1c")
        projects.write_json(self._paths()["config"], cfg)
        self.app.status("Parking lot saved.")

    # ----------------------- Quick Add -------------------------------------
    def _build_quickadd(self, tab):
        tab.grid_rowconfigure(1, weight=1)
        tab.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(tab, text="One entry per line.  Characters:  Name: notes   "
                     "World:  world: Place: notes", text_color=theme.TEXT_MUTED,
                     wraplength=480, justify="left").grid(row=0, column=0,
                                                         sticky="w", padx=10,
                                                         pady=(8, 2))
        self.quick_box = ctk.CTkTextbox(tab, wrap="word")
        self.quick_box.grid(row=1, column=0, sticky="nsew", padx=10, pady=4)
        self.quick_box.insert("1.0", "Jax Vire: ex-courier, owes everyone\n"
                                     "world: The Undercity: flooded lower tier")
        attach(self.quick_box, "One entry per line. 'Name: notes' adds a "
                               "character; prefix with 'world:' to add a place "
                               "(world: Place: notes).")
        ctk.CTkButton(tab, text="Add to Lorebook", command=self._quick_add,
                      **theme.primary_btn()).grid(row=2, column=0, sticky="e",
                                                  padx=10, pady=8)

    def _quick_add(self):
        added = 0
        for raw in self.quick_box.get("1.0", "end").splitlines():
            line = raw.strip()
            if not line:
                continue
            is_world = line.lower().startswith("world:")
            if is_world:
                line = line.split(":", 1)[1].strip()
            if ":" in line:
                name, notes = line.split(":", 1)
            else:
                name, notes = line, ""
            name = name.strip()
            if not name:
                continue
            lore.add(self._paths()["lore"], {
                "type": "world" if is_world else "character",
                "name": name, "notes": notes.strip(),
                "keywords": [name],
            })
            added += 1
        self.quick_box.delete("1.0", "end")
        self.app.status(f"Added {added} entr{'y' if added == 1 else 'ies'} to lore.")

    # ----------------------- Pre-Flight ------------------------------------
    def _build_preflight(self, tab):
        tab.grid_rowconfigure(1, weight=1)
        tab.grid_columnconfigure(0, weight=1)
        recheck_btn = ctk.CTkButton(tab, text="Re-check", command=self._run_preflight,
                                    **theme.secondary_btn())
        recheck_btn.grid(row=0, column=0, sticky="w", padx=10, pady=8)
        attach(recheck_btn, "Re-run the readiness checklist against the project's "
                            "current bible, lore, world state, and chapters.")
        self.preflight_frame = ctk.CTkScrollableFrame(tab, fg_color=theme.BG_APP)
        self.preflight_frame.grid(row=1, column=0, sticky="nsew", padx=10, pady=4)
        self.preflight_frame.grid_columnconfigure(0, weight=1)

    def _run_preflight(self):
        for w in self.preflight_frame.winfo_children():
            w.destroy()
        p = self._paths()
        bible = story_bible.read(p["bible"])
        book = lore.read(p["lore"])
        ws = world_state.read(p["world_state"])
        chs = chapters.list_chapters(p["chapters"])
        has_content = any(chapters.read(p["chapters"], c["id"])["content"].strip()
                          for c in chs)
        pinned = [e for e in (book["characters"] + book["world"])
                  if e.get("alwaysInclude") or e.get("pinned")]
        checks = [
            ("Premise written", bool(bible.get("premise"))),
            ("Genre & tone set", bool(bible.get("genreTone"))),
            ("Point of view + tense set",
             bool(bible.get("pointOfView")) and bool(bible.get("tense"))),
            ("Style notes written", bool(bible.get("styleNotes"))),
            ("At least one pinned/always-include lore entry", bool(pinned)),
            ("World state location set", bool(ws.get("currentLocation"))),
            ("At least one chapter exists", bool(chs)),
            ("Some prose written", has_content),
        ]
        for i, (label, ok) in enumerate(checks):
            ctk.CTkLabel(self.preflight_frame,
                         text=("\u2714  " if ok else "\u2717  ") + label,
                         anchor="w",
                         text_color=theme.GREEN if ok else theme.RED
                         ).grid(row=i, column=0, sticky="ew", padx=8, pady=3)

    # ----------------------- lifecycle -------------------------------------
    def on_show(self):
        self._load_parking()
        self._run_preflight()

    def on_project_change(self):
        self._load_parking()
        self._run_preflight()
