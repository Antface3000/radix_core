"""Story Bible - the consolidated worldbuilding hub.

A tabbed panel that brings the setting together in one place:
    Bible       - premise / genre / themes / rules / style (the SETTING source)
    Lorebook    - characters & world entries (embedded LoreBookPanel)
    World State - the current mutable 'now' (embedded WorldStatePanel)
    Outline     - per-chapter synopsis + beats

Injected into every agent as the SETTING via src/worldcontext.py.
"""

import customtkinter as ctk

from gui import theme
from gui.panels.base import BasePanel
from gui.panels.lorebook_panel import LoreBookPanel
from gui.panels.worldstate_panel import WorldStatePanel
from src import story_bible, outline, chapters

_BIBLE_FIELDS = [
    ("premise", "Premise", True),
    ("logline", "Logline", False),
    ("genreTone", "Genre & Tone", False),
    ("themes", "Themes (comma-separated)", False),
    ("pointOfView", "Point of View", False),
    ("tense", "Tense", False),
    ("worldRules", "World Rules", True),
    ("styleNotes", "Style Notes", True),
    ("synopsis", "Synopsis", True),
]


class StoryBiblePanel(BasePanel):
    title = "Story Bible"

    def __init__(self, master, app):
        super().__init__(master, app)
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self.tabs = ctk.CTkTabview(self, fg_color=theme.BG_CARD)
        self.tabs.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)
        for name in ("Bible", "Lorebook", "World State", "Outline"):
            self.tabs.add(name)

        self._build_bible(self.tabs.tab("Bible"))
        self.lore_panel = LoreBookPanel(self.tabs.tab("Lorebook"), app)
        self._embed(self.tabs.tab("Lorebook"), self.lore_panel)
        self.world_panel = WorldStatePanel(self.tabs.tab("World State"), app)
        self._embed(self.tabs.tab("World State"), self.world_panel)
        self._build_outline(self.tabs.tab("Outline"))

        self.on_show()

    @staticmethod
    def _embed(tab, panel):
        tab.grid_rowconfigure(0, weight=1)
        tab.grid_columnconfigure(0, weight=1)
        panel.grid(row=0, column=0, sticky="nsew")

    def _paths(self):
        return self.app.engine.paths

    # ----------------------- Bible tab -------------------------------------
    def _build_bible(self, tab):
        tab.grid_rowconfigure(0, weight=1)
        tab.grid_columnconfigure(0, weight=1)
        scroll = ctk.CTkScrollableFrame(tab, fg_color=theme.BG_APP)
        scroll.grid(row=0, column=0, sticky="nsew", padx=4, pady=4)
        scroll.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(scroll, text="Defines the world (the SETTING injected into "
                     "every agent). Edit here, not in the personas.",
                     text_color=theme.TEXT_MUTED, wraplength=520, justify="left"
                     ).grid(sticky="w", padx=12, pady=(8, 4))
        self.bible_widgets = {}
        for key, label, multiline in _BIBLE_FIELDS:
            ctk.CTkLabel(scroll, text=label, anchor="w",
                         text_color=theme.TEXT_PRIMARY).grid(sticky="ew", padx=12,
                                                            pady=(10, 2))
            w = (ctk.CTkTextbox(scroll, height=70, wrap="word") if multiline
                 else ctk.CTkEntry(scroll))
            w.grid(sticky="ew", padx=12, pady=(0, 4))
            self.bible_widgets[key] = w
        ctk.CTkButton(tab, text="Save Bible", command=self._save_bible,
                      **theme.primary_btn()).grid(row=1, column=0, sticky="e",
                                                  padx=12, pady=(4, 8))

    def _load_bible(self):
        data = story_bible.read(self._paths()["bible"])
        for key, w in self.bible_widgets.items():
            val = data.get(key, "")
            if key == "themes" and isinstance(val, list):
                val = ", ".join(val)
            val = str(val or "")
            if isinstance(w, ctk.CTkTextbox):
                w.delete("1.0", "end")
                w.insert("1.0", val)
            else:
                w.delete(0, "end")
                w.insert(0, val)

    def _save_bible(self):
        patch = {}
        for key, w in self.bible_widgets.items():
            val = (w.get("1.0", "end").strip() if isinstance(w, ctk.CTkTextbox)
                   else w.get().strip())
            if key == "themes":
                val = [t.strip() for t in val.split(",") if t.strip()]
            patch[key] = val
        story_bible.write(self._paths()["bible"], patch)
        self.app.status("Story Bible saved.")

    # ----------------------- Outline tab -----------------------------------
    def _build_outline(self, tab):
        tab.grid_rowconfigure(2, weight=1)
        tab.grid_columnconfigure(0, weight=1)
        top = ctk.CTkFrame(tab, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=8, pady=8)
        ctk.CTkLabel(top, text="Chapter", text_color=theme.TEXT_MUTED
                     ).pack(side="left", padx=(0, 6))
        self.outline_menu = ctk.CTkOptionMenu(top, values=["(none)"], width=140,
                                              command=self._on_outline_chapter)
        self.outline_menu.pack(side="left", fill="x", expand=True, padx=(0, 8))
        ctk.CTkButton(top, text="Save Outline", command=self._save_outline,
                      **theme.primary_btn()).pack(side="right")

        ctk.CTkLabel(tab, text="Synopsis", anchor="w", text_color=theme.TEXT_PRIMARY
                     ).grid(row=1, column=0, sticky="ew", padx=12)
        self.outline_synopsis = ctk.CTkTextbox(tab, height=80, wrap="word")
        self.outline_synopsis.grid(row=2, column=0, sticky="ew", padx=12, pady=(0, 6))
        ctk.CTkLabel(tab, text="Beats (one per line)", anchor="w",
                     text_color=theme.TEXT_PRIMARY).grid(row=3, column=0,
                                                        sticky="ew", padx=12)
        self.outline_beats = ctk.CTkTextbox(tab, wrap="word")
        self.outline_beats.grid(row=4, column=0, sticky="nsew", padx=12, pady=(0, 10))
        tab.grid_rowconfigure(4, weight=1)
        self._outline_by_name = {}
        self._outline_cid = None

    def _reload_outline_chapters(self):
        lst = chapters.list_chapters(self._paths()["chapters"])
        self._outline_by_name = {c["name"]: c["id"] for c in lst}
        names = list(self._outline_by_name.keys()) or ["(none)"]
        self.outline_menu.configure(values=names)
        if lst:
            self.outline_menu.set(names[0])
            self._load_outline(lst[0]["id"])
        else:
            self._outline_cid = None

    def _on_outline_chapter(self, name):
        cid = self._outline_by_name.get(name)
        if cid:
            self._load_outline(cid)

    def _load_outline(self, cid):
        self._outline_cid = cid
        data = outline.read_chapter(self._paths()["outlines"], cid)
        self.outline_synopsis.delete("1.0", "end")
        self.outline_synopsis.insert("1.0", data.get("summary", ""))
        beats = data.get("beats", []) or []
        lines = [(b.get("text") if isinstance(b, dict) else str(b)) for b in beats]
        self.outline_beats.delete("1.0", "end")
        self.outline_beats.insert("1.0", "\n".join(l for l in lines if l))

    def _save_outline(self):
        if not self._outline_cid:
            self.app.status("No chapter to outline yet.")
            return
        beats = [{"text": ln.strip()} for ln in
                 self.outline_beats.get("1.0", "end").splitlines() if ln.strip()]
        outline.write_chapter(self._paths()["outlines"], self._outline_cid, {
            "summary": self.outline_synopsis.get("1.0", "end").strip(),
            "beats": beats,
        })
        self.app.status("Outline saved.")

    # ----------------------- lifecycle -------------------------------------
    def on_show(self):
        self._load_bible()
        self.lore_panel.on_show()
        self.world_panel.on_show()
        self._reload_outline_chapters()

    def on_project_change(self):
        self._load_bible()
        self.lore_panel.on_project_change()
        self.world_panel.on_project_change()
        self._reload_outline_chapters()
