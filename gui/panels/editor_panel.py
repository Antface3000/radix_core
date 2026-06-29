"""EditorPanel - the persistent manuscript editor at the center of Radix Core.

A rich tk.Text writing surface backed by per-project chapters (src/chapters.py),
with a chapter bar, a format toolbar (font / size / line height / focus /
typewriter / word goal / colors / find), live word count + goal progress, and a
reserved AI action bar + right dock that later phases populate (Write /
Brainstorm / Chat / Visualize / Listen + AI response/preview).
"""

import base64
import io
import os
import queue
import threading
import time
import tkinter as tk
from tkinter import colorchooser

import customtkinter as ctk

import config
from gui import theme
from gui.panels.base import BasePanel
from gui.tooltip import attach
from src import chapters, projects, story_context

try:
    from PIL import Image
    _PIL_OK = True
except Exception:
    Image = None
    _PIL_OK = False

_FONT_FAMILIES = ["Georgia", "Palatino Linotype", "Times New Roman", "Cambria",
                  "Courier New", "Consolas", "Segoe UI", "Arial"]
_FONT_SIZES = [str(n) for n in range(12, 37)]
_LINE_HEIGHTS = ["1.2", "1.4", "1.6", "1.8", "2.0", "2.4"]
# Quick-access presets shown next to the color picker; the picker handles any
# other color via a popup wheel.
_COLOR_PRESETS = [("Lime", theme.LIME), ("Blue", theme.BLUE),
                  ("Orange", theme.ORANGE)]


class EditorPanel(BasePanel):
    title = "Editor"

    def __init__(self, master, app):
        super().__init__(master, app)
        s = app.settings
        self.font_family = s.get("editor.font_family", "Georgia")
        self.font_size = int(s.get("editor.font_size", 18))
        self.line_height = float(s.get("editor.line_height", 1.6))
        self.word_goal = int(s.get("editor.word_goal", 1000))
        self.focus_mode = bool(s.get("editor.focus_mode", False))
        self.typewriter = bool(s.get("editor.typewriter", False))

        self.current_chapter_id = None
        self._loading = False
        self._save_handle = None

        # Text coloring: last picked color + every color tag we've created.
        self._last_color = theme.LIME
        self._color_tags = set()

        # AI dock state.
        self.ai_queue = queue.Queue()
        self._ai_busy = False
        self._ai_buffer = ""
        self._ai_history = []      # list of {"title": str, "text": str}
        self._ai_index = -1
        self._ai_final = None      # insertable result for current run
        self._reroll = None        # (title, gen_factory) for re-roll
        self._chat_history = []    # list of (role, content)

        # Draft edits (AI insertions pending accept/reject).
        self._drafts = []          # [{"id": int, "note": str, "tag": str}]
        self._draft_seq = 0

        # Live lore auto-scan.
        self._last_scan_sig = None

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        self._build_chapter_bar()
        self._build_toolbar()
        self._build_main()
        self._build_ai_bar()
        self._build_draft_bar()
        self._build_footer()

        self._apply_font()
        self._apply_focus()
        self._load_chapters()
        self.after(1500, self._lore_scan)

    # ======================= layout ========================================
    def _build_chapter_bar(self):
        bar = ctk.CTkFrame(self, fg_color=theme.BG_SIDEBAR, corner_radius=0)
        bar.grid(row=0, column=0, sticky="ew")
        self.chapter_bar = bar
        ctk.CTkLabel(bar, text="Chapter", text_color=theme.TEXT_MUTED
                     ).pack(side="left", padx=(12, 6), pady=8)
        self.chapter_menu = ctk.CTkOptionMenu(bar, values=["(none)"], width=210,
                                              command=self._on_chapter_select)
        self.chapter_menu.pack(side="left", pady=8)
        ctk.CTkButton(bar, text="+ New", width=64, command=self._new_chapter,
                      **theme.primary_btn()).pack(side="left", padx=(8, 2), pady=8)
        ctk.CTkButton(bar, text="Rename", width=70, command=self._rename_chapter,
                      **theme.secondary_btn()).pack(side="left", padx=2, pady=8)
        ctk.CTkButton(bar, text="Delete", width=66, command=self._delete_chapter,
                      **theme.danger_btn()).pack(side="left", padx=2, pady=8)
        ctk.CTkButton(bar, text="Save", width=60, command=self._save_now,
                      **theme.secondary_btn()).pack(side="left", padx=2, pady=8)

        # Find cluster (right side).
        self.find_var = tk.StringVar()
        self.find_entry = ctk.CTkEntry(bar, placeholder_text="Find...", width=150,
                                       textvariable=self.find_var)
        self.find_entry.pack(side="right", padx=(2, 12), pady=8)
        self.find_entry.bind("<Return>", lambda _e: self._find(1))
        self.find_entry.bind("<Shift-Return>", lambda _e: self._find(-1))
        attach(self.find_entry, "Type text to find in this chapter. Enter = next "
                                "match, Shift+Enter = previous match.")
        find_prev = ctk.CTkButton(bar, text="\u25B2", width=30,
                                  command=lambda: self._find(-1),
                                  **theme.secondary_btn())
        find_prev.pack(side="right", padx=2, pady=8)
        attach(find_prev, "Find previous match (Shift+Enter).")
        find_next = ctk.CTkButton(bar, text="\u25BC", width=30,
                                  command=lambda: self._find(1),
                                  **theme.secondary_btn())
        find_next.pack(side="right", padx=2, pady=8)
        attach(find_next, "Find next match (Enter).")

    def _build_toolbar(self):
        bar = ctk.CTkFrame(self, fg_color=theme.BG_CARD, corner_radius=0)
        bar.grid(row=1, column=0, sticky="ew")
        self.toolbar = bar

        ctk.CTkLabel(bar, text="Font", text_color=theme.TEXT_MUTED
                     ).pack(side="left", padx=(12, 4), pady=6)
        self.font_menu = ctk.CTkOptionMenu(bar, values=_FONT_FAMILIES, width=150,
                                           command=self._set_font_family)
        self.font_menu.set(self.font_family)
        self.font_menu.pack(side="left", pady=6)

        ctk.CTkLabel(bar, text="Size", text_color=theme.TEXT_MUTED
                     ).pack(side="left", padx=(10, 4))
        self.size_menu = ctk.CTkOptionMenu(bar, values=_FONT_SIZES, width=64,
                                           command=self._set_font_size)
        self.size_menu.set(str(self.font_size))
        self.size_menu.pack(side="left", pady=6)

        ctk.CTkLabel(bar, text="Line", text_color=theme.TEXT_MUTED
                     ).pack(side="left", padx=(10, 4))
        self.line_menu = ctk.CTkOptionMenu(bar, values=_LINE_HEIGHTS, width=64,
                                           command=self._set_line_height)
        self.line_menu.set(str(self.line_height))
        self.line_menu.pack(side="left", pady=6)

        # Color: a picker (opens a color wheel) + a few quick presets + clear.
        ctk.CTkLabel(bar, text="Color", text_color=theme.TEXT_MUTED
                     ).pack(side="left", padx=(10, 4))
        self.color_btn = ctk.CTkButton(
            bar, text="\U0001F3A8", width=32, command=self._pick_color,
            **{**theme.ghost_btn(), "text_color": self._last_color})
        self.color_btn.pack(side="left", padx=1, pady=6)
        attach(self.color_btn, "Pick any text color from a color wheel and apply "
                               "it to the selected text.")
        for label, color in _COLOR_PRESETS:
            sw = ctk.CTkButton(bar, text="A", width=24,
                               command=lambda c=color: self._apply_color(c),
                               **{**theme.ghost_btn(), "text_color": color})
            sw.pack(side="left", padx=1, pady=6)
            attach(sw, f"Quick-color the selected text {label.lower()}.")
        clear_btn = ctk.CTkButton(bar, text="\u2715", width=24,
                                  command=lambda: self._apply_color(None),
                                  **theme.ghost_btn())
        clear_btn.pack(side="left", padx=1, pady=6)
        attach(clear_btn, "Clear color from the selected text.")

        ctk.CTkLabel(bar, text="Goal", text_color=theme.TEXT_MUTED
                     ).pack(side="left", padx=(10, 4))
        self.goal_entry = ctk.CTkEntry(bar, width=70)
        self.goal_entry.insert(0, str(self.word_goal))
        self.goal_entry.bind("<Return>", lambda _e: self._set_word_goal())
        self.goal_entry.bind("<FocusOut>", lambda _e: self._set_word_goal())
        self.goal_entry.pack(side="left", pady=6)
        attach(self.goal_entry, "Word goal for this chapter; fills the progress "
                                "bar in the footer. Press Enter to apply.")

        self.focus_var = ctk.BooleanVar(value=self.focus_mode)
        focus_cb = ctk.CTkCheckBox(bar, text="Focus", variable=self.focus_var,
                                   command=self._toggle_focus, width=20)
        focus_cb.pack(side="left", padx=(12, 4))
        attach(focus_cb, "Hide the format toolbar to reduce distraction.")
        self.tw_var = ctk.BooleanVar(value=self.typewriter)
        tw_cb = ctk.CTkCheckBox(bar, text="Typewriter", variable=self.tw_var,
                                command=self._toggle_typewriter, width=20)
        tw_cb.pack(side="left", padx=4)
        attach(tw_cb, "Typewriter mode: keep the cursor line in view as you type.")

    def _build_main(self):
        wrap = ctk.CTkFrame(self, fg_color=theme.BG_APP, corner_radius=0)
        wrap.grid(row=2, column=0, sticky="nsew")
        wrap.grid_rowconfigure(0, weight=1)
        wrap.grid_columnconfigure(0, weight=1)
        self.main_wrap = wrap

        editor_frame = ctk.CTkFrame(wrap, fg_color=theme.BG_INPUT)
        editor_frame.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        editor_frame.grid_rowconfigure(0, weight=1)
        editor_frame.grid_columnconfigure(0, weight=1)

        self.text = tk.Text(
            editor_frame, wrap="word", undo=True, relief="flat", bd=0,
            bg=theme.BG_INPUT, fg=theme.TEXT_PRIMARY,
            insertbackground=theme.LIME, selectbackground=theme.BORDER_ACTIVE,
            selectforeground="#FFFFFF", padx=26, pady=20,
            font=(self.font_family, self.font_size),
            spacing1=2, spacing3=6)
        self.text.grid(row=0, column=0, sticky="nsew")
        scrollbar = ctk.CTkScrollbar(editor_frame, command=self.text.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.text.configure(yscrollcommand=scrollbar.set)
        self.text.configure(state="disabled")  # enabled once a chapter loads

        self.text.tag_configure("find", background=theme.LIME,
                                foreground=theme.BG_APP)
        self.text.tag_configure("draft-ins", background="#23330F",
                                underline=True)

        self.text.bind("<<Modified>>", self._on_modified)
        self.text.bind("<KeyRelease>", self._on_keyrelease)

        # Right dock for AI response / chat / image preview.
        self.right_dock = ctk.CTkFrame(wrap, fg_color=theme.BG_CARD, width=380,
                                       corner_radius=0)
        self.right_dock.grid(row=0, column=1, sticky="nsew")
        self.right_dock.grid_propagate(False)
        self._build_ai_dock()
        self.right_dock.grid_remove()

    def _build_ai_dock(self):
        dock = self.right_dock
        dock.grid_columnconfigure(0, weight=1)
        dock.grid_rowconfigure(0, weight=1)
        self.dock_tabs = ctk.CTkTabview(dock, fg_color=theme.BG_APP)
        self.dock_tabs.grid(row=0, column=0, sticky="nsew", padx=6, pady=6)
        self.dock_tabs.add("AI")
        self.dock_tabs.add("Chat")
        self.dock_tabs.add("Image")
        self._build_response_tab(self.dock_tabs.tab("AI"))
        self._build_chat_tab(self.dock_tabs.tab("Chat"))
        self._build_image_tab(self.dock_tabs.tab("Image"))

    def _build_response_tab(self, tab):
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(1, weight=1)
        head = ctk.CTkFrame(tab, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew")
        head.grid_columnconfigure(0, weight=1)
        self.ai_title = ctk.CTkLabel(head, text="AI Response", anchor="w",
                                     font=ctk.CTkFont(size=13, weight="bold"),
                                     text_color=theme.LIME)
        self.ai_title.grid(row=0, column=0, sticky="w", padx=2)
        prev_btn = ctk.CTkButton(head, text="\u25C0", width=30,
                                 command=lambda: self._ai_nav(-1),
                                 **theme.secondary_btn())
        prev_btn.grid(row=0, column=1, padx=1)
        attach(prev_btn, "Previous AI response in the history.")
        self.ai_counter = ctk.CTkLabel(head, text="0/0", width=40,
                                       text_color=theme.TEXT_MUTED)
        self.ai_counter.grid(row=0, column=2)
        next_btn = ctk.CTkButton(head, text="\u25B6", width=30,
                                 command=lambda: self._ai_nav(1),
                                 **theme.secondary_btn())
        next_btn.grid(row=0, column=3, padx=1)
        attach(next_btn, "Next AI response in the history.")
        close_btn = ctk.CTkButton(head, text="\u2715", width=30,
                                  command=self.hide_dock, **theme.ghost_btn())
        close_btn.grid(row=0, column=4, padx=(2, 0))
        attach(close_btn, "Hide the AI dock.")

        self.ai_text = ctk.CTkTextbox(tab, wrap="word", font=("Georgia", 13))
        self.ai_text.grid(row=1, column=0, sticky="nsew", pady=6)
        self.ai_text.configure(state="disabled")

        actions = ctk.CTkFrame(tab, fg_color="transparent")
        actions.grid(row=2, column=0, sticky="ew")
        self.ai_insert_btn = ctk.CTkButton(actions, text="Insert at Cursor",
                                           command=self._ai_insert, **theme.primary_btn())
        self.ai_insert_btn.pack(side="left", padx=2)
        attach(self.ai_insert_btn, "Insert this response at the cursor as a draft "
                                   "edit (accept/reject below).")
        copy_btn = ctk.CTkButton(actions, text="Copy", width=64, command=self._ai_copy,
                                 **theme.secondary_btn())
        copy_btn.pack(side="left", padx=2)
        attach(copy_btn, "Copy this response to the clipboard.")
        reroll_btn = ctk.CTkButton(actions, text="\u21BB Re-roll", width=84,
                                   command=self._ai_reroll, **theme.secondary_btn())
        reroll_btn.pack(side="left", padx=2)
        attach(reroll_btn, "Run the same request again for a different result.")

    def _build_chat_tab(self, tab):
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(0, weight=1)
        self.chat_text = ctk.CTkTextbox(tab, wrap="word", font=("Segoe UI", 12))
        self.chat_text.grid(row=0, column=0, sticky="nsew", pady=(2, 6))
        self.chat_text.configure(state="disabled")
        bottom = ctk.CTkFrame(tab, fg_color="transparent")
        bottom.grid(row=1, column=0, sticky="ew")
        bottom.grid_columnconfigure(0, weight=1)
        self.chat_entry = ctk.CTkEntry(bottom, placeholder_text="Ask about the project...")
        self.chat_entry.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        self.chat_entry.bind("<Return>", lambda _e: self._chat_send())
        ctk.CTkButton(bottom, text="Send", width=60, command=self._chat_send,
                      **theme.primary_btn()).grid(row=0, column=1)

    def _build_image_tab(self, tab):
        """Image preview (populated by the visualize phase)."""
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(0, weight=1)
        self.image_preview = ctk.CTkLabel(tab, text="No image yet.\nSelect text "
                                          "and click Visualize.",
                                          text_color=theme.TEXT_MUTED)
        self.image_preview.grid(row=0, column=0, sticky="nsew")

    def _build_ai_bar(self):
        # Horizontally scrollable so the agent dropdown / Ask never clip off the
        # right edge on a narrow editor; scroll with the bar or Shift+wheel.
        bar = ctk.CTkScrollableFrame(self, orientation="horizontal",
                                     fg_color=theme.BG_SIDEBAR, corner_radius=0,
                                     height=48)
        bar.grid(row=3, column=0, sticky="ew")
        self.ai_bar = bar

        write_btn = ctk.CTkButton(bar, text="Write", width=70, command=self._write,
                                  **theme.primary_btn())
        write_btn.pack(side="left", padx=(12, 3), pady=8)
        attach(write_btn, "Continue the prose: the Ghostwriter drafts the next "
                          "passage, then the critics refine it. The result lands "
                          "in the AI dock; Insert adds it as a draft edit.")
        brainstorm_btn = ctk.CTkButton(bar, text="Brainstorm", width=92,
                                       command=self._brainstorm,
                                       **theme.accent_btn(theme.BLUE, "#1f5aa8"))
        brainstorm_btn.pack(side="left", padx=3, pady=8)
        attach(brainstorm_btn, "Get 3 idea directions for the current scene "
                               "(does not write prose into the manuscript).")
        chat_btn = ctk.CTkButton(bar, text="Chat", width=64, command=self._open_chat,
                                 **theme.accent_btn(theme.PURPLE, "#5e1f96"))
        chat_btn.pack(side="left", padx=3, pady=8)
        attach(chat_btn, "Open a project-aware conversation about plot, "
                         "characters, and consistency. It discusses; it does not "
                         "write prose.")

        self.vis_mode = ctk.CTkOptionMenu(bar, values=["Landscape", "Portrait"],
                                          width=104)
        self.vis_mode.set("Landscape")
        self.vis_mode.pack(side="left", padx=(10, 3), pady=8)
        attach(self.vis_mode, "Landscape renders a background; Portrait renders a "
                              "character image. Saved to the project's "
                              "backgrounds/ or portraits/ folder.")
        vis_btn = ctk.CTkButton(bar, text="Visualize", width=84,
                                command=self._visualize,
                                **theme.accent_btn(theme.PURPLE, "#5e1f96"))
        vis_btn.pack(side="left", padx=3, pady=8)
        attach(vis_btn, "Render the selected text (or recent prose) as an image "
                        "via ComfyUI; shown in the Image tab.")
        listen_btn = ctk.CTkButton(bar, text="Listen", width=66,
                                   command=self._listen,
                                   **theme.accent_btn(theme.ORANGE, "#c24400"))
        listen_btn.pack(side="left", padx=3, pady=8)
        attach(listen_btn, "Read the selected text aloud with the configured TTS "
                           "engine (Settings -> Services).")

        self.direction = ctk.CTkEntry(bar, placeholder_text="Direction for Write...",
                                      width=160)
        self.direction.pack(side="left", padx=(10, 3), pady=8)
        attach(self.direction, "Optional guidance for Write/Brainstorm/Ask, e.g. "
                               "'introduce the rival' or 'end on a cliffhanger'.")
        self.voice_menu = ctk.CTkOptionMenu(
            bar, values=list(config.STYLE_PRESET_LABELS), width=120,
            command=lambda v: self.app.settings.set(
                "editor.voice_preset", config.style_preset_from_display(v)))
        self.voice_menu.set(config.style_preset_display(
            self.app.settings.get("editor.voice_preset", "my")))
        self.voice_menu.pack(side="left", padx=3, pady=8)
        attach(self.voice_menu, "Writing style preset for Write: My Style, "
                                "Alt Style, or Neutral Style. Edit the style "
                                "guide text in Settings -> Editor.")

        # Ask Agent + Author's Note. Packed left (like everything else) so the
        # scrollable bar lays them out in reading order without colliding.
        self.agent_menu = ctk.CTkOptionMenu(bar, values=self._agent_values(),
                                            width=170)
        self.agent_menu.pack(side="left", padx=(10, 3), pady=8)
        attach(self.agent_menu, "Choose one agent, or 'Team (orchestrate)', for "
                                "the Ask button.")
        ask_btn = ctk.CTkButton(bar, text="Ask", width=54, command=self._ask_agent,
                                **theme.secondary_btn())
        ask_btn.pack(side="left", padx=3, pady=8)
        attach(ask_btn, "Run the chosen agent (or the whole team) on the selected "
                        "text or your Direction; output streams into the AI dock.")
        note_btn = ctk.CTkButton(bar, text="Author's Note", width=104,
                                 command=self._author_note, **theme.secondary_btn())
        note_btn.pack(side="left", padx=(3, 12), pady=8)
        attach(note_btn, "Per-project scene guidance injected into every Write "
                         "(e.g. current goal, tone, what to emphasize).")

        self.after(120, self._ai_poll)

    def _build_draft_bar(self):
        bar = ctk.CTkFrame(self, fg_color="#15200B", corner_radius=0)
        bar.grid(row=4, column=0, sticky="ew")
        self.draft_bar = bar
        self.draft_count_lbl = ctk.CTkLabel(
            bar, text="", text_color=theme.LIME,
            font=ctk.CTkFont(size=12, weight="bold"))
        self.draft_count_lbl.pack(side="left", padx=12, pady=4)
        accept_btn = ctk.CTkButton(bar, text="Accept All", width=90,
                                   command=self._accept_all_drafts,
                                   **theme.primary_btn())
        accept_btn.pack(side="left", padx=3, pady=4)
        attach(accept_btn, "Keep all pending AI insertions (removes the draft "
                           "highlight).")
        reject_btn = ctk.CTkButton(bar, text="Reject All", width=90,
                                   command=self._reject_all_drafts,
                                   **theme.danger_btn())
        reject_btn.pack(side="left", padx=3, pady=4)
        attach(reject_btn, "Delete all pending AI insertions from the manuscript.")
        review_btn = ctk.CTkButton(bar, text="Review...", width=86,
                                   command=self._review_drafts,
                                   **theme.secondary_btn())
        review_btn.pack(side="left", padx=3, pady=4)
        attach(review_btn, "Review each AI insertion and accept or reject it "
                           "individually.")
        self.draft_bar.grid_remove()

    def _build_footer(self):
        bar = ctk.CTkFrame(self, fg_color=theme.BG_SIDEBAR, height=28,
                           corner_radius=0)
        bar.grid(row=5, column=0, sticky="ew")
        self.word_count_lbl = ctk.CTkLabel(bar, text="0 words",
                                           text_color=theme.TEXT_MUTED)
        self.word_count_lbl.pack(side="left", padx=12, pady=2)
        self.progress = ctk.CTkProgressBar(bar, width=160)
        self.progress.set(0)
        self.progress.pack(side="left", padx=8)
        self.engine_status = ctk.CTkLabel(bar, text="\u25CF READY",
                                          text_color=theme.GREEN,
                                          font=ctk.CTkFont(size=11))
        self.engine_status.pack(side="right", padx=12)
        ctk.CTkLabel(bar, text="Active lore:", text_color=theme.TEXT_MUTED,
                     font=ctk.CTkFont(size=11)).pack(side="left", padx=(18, 2))
        self.lore_strip = ctk.CTkFrame(bar, fg_color="transparent")
        self.lore_strip.pack(side="left")

    # ======================= chapters ======================================
    def _paths(self):
        return self.app.engine.paths

    def _load_chapters(self, select_id=None):
        cdir = self._paths()["chapters"]
        lst = chapters.list_chapters(cdir)
        if not lst:
            chapters.create(cdir, "Chapter 1")
            lst = chapters.list_chapters(cdir)
        self._chapter_by_name = {}
        names = []
        for c in lst:
            name = c["name"]
            # disambiguate duplicate display names
            if name in self._chapter_by_name:
                name = f"{name} ({c['id'][:4]})"
            self._chapter_by_name[name] = c["id"]
            names.append(name)
        self.chapter_menu.configure(values=names)

        ids = [c["id"] for c in lst]
        target = select_id or self.current_chapter_id
        if target not in ids:
            target = ids[0]
        self._load_chapter(target)

    def _name_for_id(self, cid):
        for name, _id in self._chapter_by_name.items():
            if _id == cid:
                return name
        return None

    def _on_chapter_select(self, name):
        cid = self._chapter_by_name.get(name)
        if cid and cid != self.current_chapter_id:
            self._save_now()
            self._load_chapter(cid)

    def _load_chapter(self, cid):
        try:
            data = chapters.read(self._paths()["chapters"], cid)
        except ValueError:
            return
        self._loading = True
        self.current_chapter_id = cid
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.insert("1.0", data["content"])
        self.text.edit_reset()
        self.text.edit_modified(False)
        self._loading = False
        name = self._name_for_id(cid)
        if name:
            self.chapter_menu.set(name)
        self._load_drafts()
        self._update_word_count()

    def _new_chapter(self):
        dlg = ctk.CTkInputDialog(text="Name the new chapter:", title="New Chapter")
        name = dlg.get_input()
        if not name:
            return
        self._save_now()
        ch = chapters.create(self._paths()["chapters"], name)
        self._load_chapters(select_id=ch["id"])
        self.app.status(f"Created chapter '{name}'.")

    def _rename_chapter(self):
        if not self.current_chapter_id:
            return
        dlg = ctk.CTkInputDialog(text="New chapter name:", title="Rename Chapter")
        name = dlg.get_input()
        if not name:
            return
        chapters.rename(self._paths()["chapters"], self.current_chapter_id, name)
        self._load_chapters(select_id=self.current_chapter_id)

    def _delete_chapter(self):
        if not self.current_chapter_id:
            return
        chapters.delete(self._paths()["chapters"], self.current_chapter_id)
        self.current_chapter_id = None
        self._load_chapters()
        self.app.status("Chapter deleted.")

    # ======================= autosave ======================================
    def _on_modified(self, _event=None):
        if self._loading:
            self.text.edit_modified(False)
            return
        self.text.edit_modified(False)
        self._update_word_count()
        self._schedule_save()

    def _on_keyrelease(self, _event=None):
        if self.typewriter:
            self.text.see("insert")

    def _schedule_save(self):
        if self._save_handle:
            self.after_cancel(self._save_handle)
        self._save_handle = self.after(900, self._save_now)

    def _save_now(self):
        if self._save_handle:
            self.after_cancel(self._save_handle)
            self._save_handle = None
        if not self.current_chapter_id or self._loading:
            return
        content = self.text.get("1.0", "end-1c")
        try:
            chapters.write(self._paths()["chapters"], self.current_chapter_id,
                           content)
            self._persist_drafts()
        except ValueError:
            pass

    # ======================= formatting ====================================
    def _apply_font(self):
        spacing = max(0, int(self.font_size * (self.line_height - 1)))
        self.text.configure(font=(self.font_family, self.font_size),
                            spacing1=spacing // 2, spacing3=spacing)

    def _set_font_family(self, value):
        self.font_family = value
        self._apply_font()
        self.app.settings.set("editor.font_family", value)

    def _set_font_size(self, value):
        self.font_size = int(value)
        self._apply_font()
        self.app.settings.set("editor.font_size", self.font_size)

    def _set_line_height(self, value):
        self.line_height = float(value)
        self._apply_font()
        self.app.settings.set("editor.line_height", self.line_height)

    def _set_word_goal(self):
        try:
            self.word_goal = max(1, int(self.goal_entry.get()))
        except ValueError:
            return
        self.app.settings.set("editor.word_goal", self.word_goal)
        self._update_word_count()

    def _toggle_focus(self):
        self.focus_mode = self.focus_var.get()
        self.app.settings.set("editor.focus_mode", self.focus_mode)
        self._apply_focus()

    def _apply_focus(self):
        if self.focus_mode:
            self.toolbar.grid_remove()
        else:
            self.toolbar.grid()

    def _toggle_typewriter(self):
        self.typewriter = self.tw_var.get()
        self.app.settings.set("editor.typewriter", self.typewriter)
        if self.typewriter:
            self.text.see("insert")

    def _pick_color(self):
        rgb, hexv = colorchooser.askcolor(
            color=self._last_color, parent=self, title="Text color")
        if not hexv:
            return
        self._last_color = hexv
        self.color_btn.configure(text_color=hexv)
        self._apply_color(hexv)

    def _apply_color(self, color):
        try:
            start, end = "sel.first", "sel.last"
            self.text.index(start)
        except tk.TclError:
            self.app.status("Select text first to color it.")
            return
        for tag in self._color_tags:
            self.text.tag_remove(tag, start, end)
        if color:
            tag = f"color-{color}"
            self.text.tag_configure(tag, foreground=color)
            self._color_tags.add(tag)
            self.text.tag_add(tag, start, end)

    # ======================= find ==========================================
    def _find(self, direction):
        needle = self.find_var.get().strip()
        self.text.tag_remove("find", "1.0", "end")
        if not needle:
            return
        start = self.text.index("insert")
        if direction > 0:
            pos = self.text.search(needle, f"{start}+1c", "end", nocase=True)
            if not pos:
                pos = self.text.search(needle, "1.0", "end", nocase=True)
        else:
            pos = self.text.search(needle, start, "1.0", backwards=True,
                                   nocase=True)
            if not pos:
                pos = self.text.search(needle, "end", "1.0", backwards=True,
                                       nocase=True)
        if pos:
            end = f"{pos}+{len(needle)}c"
            self.text.tag_add("find", pos, end)
            self.text.mark_set("insert", pos)
            self.text.see(pos)

    # ======================= word count ====================================
    def _update_word_count(self):
        words = len(self.text.get("1.0", "end-1c").split())
        self.word_count_lbl.configure(text=f"{words} words")
        self.progress.set(min(1.0, words / max(1, self.word_goal)))

    # ======================= live lore auto-scan ===========================
    def _lore_scan(self):
        try:
            if (self.app.settings.get("editor.lore_autoscan", True)
                    and self.current_chapter_id):
                recent = self.get_text_before_cursor()[-1600:]
                sig = (len(recent), recent[-40:])
                if sig != self._last_scan_sig:
                    self._last_scan_sig = sig
                    entries = story_context.rank_active_lore(
                        self._paths(), recent, "smart", 5)
                    self._render_lore_chips(entries)
        except Exception:
            pass
        interval = self.app.settings.get("editor.lore_scan_interval_ms", 3000)
        self.after(max(1000, int(interval)), self._lore_scan)

    def _render_lore_chips(self, entries):
        for w in self.lore_strip.winfo_children():
            w.destroy()
        if not entries:
            ctk.CTkLabel(self.lore_strip, text="(none)",
                         text_color=theme.TEXT_MUTED,
                         font=ctk.CTkFont(size=11)).pack(side="left")
            return
        for e in entries[:5]:
            name = (e.get("name") or "?")[:18]
            chip = ctk.CTkButton(self.lore_strip, text=name, height=20,
                                 font=ctk.CTkFont(size=11),
                                 command=lambda: self.app.open_feature("Story Bible"),
                                 **theme.secondary_btn())
            chip.pack(side="left", padx=2)
            attach(chip, "Lore the AI detected in your recent text and will "
                         "reference. Click to open the Story Bible.")

    # ======================= editor text helpers (for later phases) ========
    def get_selection(self):
        try:
            return self.text.get("sel.first", "sel.last")
        except tk.TclError:
            return ""

    def get_text_before_cursor(self):
        return self.text.get("1.0", "insert")

    def get_all_text(self):
        return self.text.get("1.0", "end-1c")

    def insert_at_cursor(self, content):
        self.text.insert("insert", content)
        self._update_word_count()
        self._schedule_save()

    # ======================= AI dock + actions =============================
    @staticmethod
    def _name(x):
        return x.get("display_name") if isinstance(x, dict) else str(x)

    def _agent_values(self):
        vals = ["Team (orchestrate)"]
        eng = self.app.engine
        for p in eng.settings.enabled_personas(eng.project_id):
            vals.append(p["display_name"])
        return vals

    def show_dock(self, tab=None):
        self.right_dock.grid()
        if tab:
            self.dock_tabs.set(tab)

    def hide_dock(self):
        self.right_dock.grid_remove()

    def _busy_set(self, busy):
        self._ai_busy = busy
        self.engine_status.configure(
            text="\u25CF WORKING" if busy else "\u25CF READY",
            text_color=theme.ORANGE if busy else theme.GREEN)

    # --- generic streaming runner (Write / Brainstorm / Ask Agent) ---
    def _run_ai(self, title, gen_factory):
        if self._ai_busy:
            self.app.status("AI is busy - wait for it to finish.")
            return
        self._reroll = (title, gen_factory)
        self.show_dock("AI")
        self.ai_title.configure(text=title)
        self._ai_buffer = ""
        self._ai_final = None
        self._ai_set_text("")
        self._busy_set(True)
        threading.Thread(target=self._ai_worker, args=(gen_factory,),
                         daemon=True).start()

    def _ai_worker(self, gen_factory):
        try:
            for ev in gen_factory():
                if isinstance(ev, tuple):
                    self.ai_queue.put(ev)
                else:
                    self.ai_queue.put(("delta", None, ev))
            self.ai_queue.put(("complete", None, None))
        except Exception as exc:
            self.ai_queue.put(("error", None, f"{type(exc).__name__}: {exc}"))

    def _ai_poll(self):
        try:
            while True:
                ev = self.ai_queue.get_nowait()
                kind = ev[0]
                if kind == "plan":
                    lines = "\n".join(
                        f"  {i+1}. {self._name(s['persona'])}: {s['instruction']}"
                        for i, s in enumerate(ev[1]))
                    self._ai_append(f"[Plan]\n{lines}\n")
                elif kind == "step":
                    self._ai_append(f"\n[{self._name(ev[1])}] {ev[2]}\n")
                elif kind == "synthesis":
                    self._ai_append(f"\n[{self._name(ev[1])} - synthesis]\n")
                elif kind == "delta":
                    self._ai_append(ev[2])
                elif kind == "step_done":
                    self._ai_append("\n")
                elif kind == "await_user":
                    self.app.status(ev[1])
                elif kind == "user":
                    self._ai_append(f"\n[You] {ev[1]}\n")
                elif kind == "final":
                    self._ai_final = ev[1]
                elif kind == "done":
                    pass
                elif kind == "complete":
                    self._ai_finish()
                elif kind == "error":
                    self._ai_append(f"\n[ERROR] {ev[2]}\n")
                    self._ai_finish()
                # chat events
                elif kind == "chat_start":
                    self._chat_stream_start()
                elif kind == "chat_delta":
                    self._chat_stream_append(ev[2])
                elif kind == "chat_done":
                    self._chat_history.append(("assistant", ev[1]))
                    self._busy_set(False)
                elif kind == "chat_error":
                    self._chat_stream_append(f"\n[ERROR] {ev[2]}\n")
                    self._busy_set(False)
        except queue.Empty:
            pass
        self.after(80, self._ai_poll)

    def _ai_finish(self):
        if self._ai_final is None:
            self._ai_final = self._ai_buffer.strip()
        self._ai_history.append({"title": self.ai_title.cget("text"),
                                 "display": self._ai_buffer.strip(),
                                 "final": self._ai_final})
        self._ai_index = len(self._ai_history) - 1
        self._update_ai_counter()
        self._busy_set(False)
        self.app.status("AI response ready.")

    def _ai_append(self, text):
        self._ai_buffer += text
        self.ai_text.configure(state="normal")
        self.ai_text.insert("end", text)
        self.ai_text.see("end")
        self.ai_text.configure(state="disabled")

    def _ai_set_text(self, text):
        self.ai_text.configure(state="normal")
        self.ai_text.delete("1.0", "end")
        self.ai_text.insert("1.0", text)
        self.ai_text.configure(state="disabled")

    def _update_ai_counter(self):
        total = len(self._ai_history)
        idx = (self._ai_index + 1) if total else 0
        self.ai_counter.configure(text=f"{idx}/{total}")

    def _ai_nav(self, direction):
        if not self._ai_history:
            return
        self._ai_index = max(0, min(len(self._ai_history) - 1,
                                    self._ai_index + direction))
        entry = self._ai_history[self._ai_index]
        self.ai_title.configure(text=entry["title"])
        self._ai_final = entry["final"]
        self._ai_set_text(entry["display"])
        self._update_ai_counter()

    def _ai_insert(self):
        if not self._ai_final:
            return
        note = self.ai_title.cget("text") + " (AI)"
        self._insert_draft(self._ai_final, note=note)
        self.app.status("Inserted as a draft edit - accept or reject it below.")

    def _ai_copy(self):
        text = self._ai_final or self._ai_buffer
        if not text:
            return
        self.clipboard_clear()
        self.clipboard_append(text)
        self.app.status("Copied.")

    def _ai_reroll(self):
        if self._ai_busy or not getattr(self, "_reroll", None):
            return
        self._run_ai(*self._reroll)

    def _ask_user(self, prompt):
        holder, ev = {}, threading.Event()

        def do():
            dlg = ctk.CTkInputDialog(text=prompt, title="The team needs input")
            holder["v"] = dlg.get_input()
            ev.set()
        self.after(0, do)
        ev.wait()
        return holder.get("v") or ""

    def _write(self):
        before = self.get_text_before_cursor()
        direction = self.direction.get().strip()
        cid = self.current_chapter_id
        note = self._author_note_text()

        def gen():
            return self.app.writing.editor_write(before, cid, author_note=note,
                                                 direction=direction)
        self._run_ai("Write", gen)

    def _brainstorm(self):
        recent = self.get_text_before_cursor()
        selection = self.get_selection()
        instruction = self.direction.get().strip()

        def gen():
            return self.app.writing.editor_brainstorm(recent, selection, instruction)
        self._run_ai("Brainstorm", gen)

    def _ask_agent(self):
        choice = self.agent_menu.get()
        msg = self.get_selection() or self.direction.get().strip()
        if not msg:
            self.app.status("Select text or type a direction for Ask Agent.")
            return
        eng = self.app.engine
        if choice.startswith("Team"):
            def gen():
                return eng.orchestrate(msg, ask_user=self._ask_user)
            self._run_ai("Team", gen)
            return
        persona = eng.settings.persona(eng.project_id, choice)
        if not persona:
            self.app.status("Unknown agent.")
            return

        def gen():
            return eng.stream_task(persona["key"], msg)
        self._run_ai(persona["display_name"], gen)

    # --- chat ---
    def _open_chat(self):
        self.show_dock("Chat")
        self.chat_entry.focus_set()

    def _chat_add(self, who, text):
        self.chat_text.configure(state="normal")
        if self.chat_text.index("end-1c") != "1.0":
            self.chat_text.insert("end", "\n\n")
        self.chat_text.insert("end", f"[{who}]\n{text}")
        self.chat_text.see("end")
        self.chat_text.configure(state="disabled")

    def _chat_stream_start(self):
        eng = self.app.engine
        persona = eng.settings.persona(
            eng.project_id, eng.settings.get("editor.chat_persona", "user_liaison"))
        who = persona["display_name"] if persona else "Assistant"
        self.chat_text.configure(state="normal")
        self.chat_text.insert("end", f"\n\n[{who}]\n")
        self.chat_text.see("end")
        self.chat_text.configure(state="disabled")

    def _chat_stream_append(self, text):
        self.chat_text.configure(state="normal")
        self.chat_text.insert("end", text)
        self.chat_text.see("end")
        self.chat_text.configure(state="disabled")

    def _chat_send(self):
        if self._ai_busy:
            self.app.status("AI is busy - wait for it to finish.")
            return
        msg = self.chat_entry.get().strip()
        if not msg:
            return
        self.chat_entry.delete(0, "end")
        self.show_dock("Chat")
        self._chat_add("You", msg)
        manuscript = self.get_all_text()
        cid = self.current_chapter_id
        note = self._author_note_text()
        history = list(self._chat_history)
        self._chat_history.append(("user", msg))
        eng = self.app.engine

        def worker():
            try:
                system = story_context.build_chat_system(
                    eng.paths, manuscript_text=manuscript, chapter_id=cid,
                    author_note=note)
                self.ai_queue.put(("chat_start", None, None))
                acc = ""
                for d in self.app.writing.editor_chat(system, history, msg):
                    acc += d
                    self.ai_queue.put(("chat_delta", None, d))
                self.ai_queue.put(("chat_done", acc, None))
            except Exception as exc:
                self.ai_queue.put(("chat_error", None,
                                   f"{type(exc).__name__}: {exc}"))
        self._busy_set(True)
        threading.Thread(target=worker, daemon=True).start()

    # --- author's note (per-project config.json) ---
    def _author_note_text(self):
        cfg = projects.read_json_safe(self._paths()["config"], {})
        return cfg.get("authorNote", "")

    def _author_note(self):
        win = ctk.CTkToplevel(self)
        win.title("Author's Note")
        win.geometry("520x360")
        win.configure(fg_color=theme.BG_APP)
        ctk.CTkLabel(win, text="Scene guidance injected into every Write:",
                     text_color=theme.TEXT_MUTED).pack(anchor="w", padx=12,
                                                       pady=(12, 4))
        box = ctk.CTkTextbox(win, wrap="word")
        box.pack(fill="both", expand=True, padx=12, pady=4)
        box.insert("1.0", self._author_note_text())

        def save():
            cfg = projects.read_json_safe(self._paths()["config"], {})
            cfg["authorNote"] = box.get("1.0", "end-1c").strip()
            projects.write_json(self._paths()["config"], cfg)
            self.app.status("Author's Note saved.")
            win.destroy()
        ctk.CTkButton(win, text="Save", command=save, **theme.primary_btn()
                      ).pack(side="right", padx=12, pady=8)

    # --- visualize (ComfyUI) + listen (TTS) on selection ---
    def _visualize(self):
        if self._ai_busy:
            self.app.status("AI is busy - wait for it to finish.")
            return
        sel = self.get_selection()
        text = sel or self.get_text_before_cursor()[-500:]
        text = " ".join(text.split()[:100])  # cap at 100 words
        if not text.strip():
            self.app.status("Select text (or write some) to visualize.")
            return
        landscape = self.vis_mode.get() == "Landscape"
        s = self.app.settings
        w = int(s.get("image.width", 1024))
        h = int(s.get("image.height", 1024))
        if landscape and h > w:
            w, h = h, w
        elif (not landscape) and w > h:
            w, h = h, w
        opts = {"subjectKind": "background" if landscape else "character",
                "width": w, "height": h}
        self.show_dock("Image")
        self.image_preview.configure(text="Rendering...", image=None)
        self._busy_set(True)
        threading.Thread(target=self._visualize_worker,
                         args=(text, opts, landscape), daemon=True).start()

    def _visualize_worker(self, text, opts, landscape):
        def on_progress(u):
            mx, val = u.get("max", 0), u.get("value", 0)
            frac = (val / mx) if mx else 0
            self.after(0, lambda: self.app.status(
                f"ComfyUI {int(frac * 100)}% {u.get('label', '')}"))

        def on_image(b64, _pid):
            self.after(0, lambda: self._show_visual(b64, landscape))

        def on_error(err):
            msg = str(err.get("message", err)) if isinstance(err, dict) else str(err)
            self.after(0, lambda: (self.image_preview.configure(text="Error: " + msg),
                                   self._busy_set(False)))
        try:
            self.app.comfy.render(text, render_options=opts, on_progress=on_progress,
                                  on_image=on_image, on_error=on_error)
        except Exception as exc:
            self.after(0, lambda: (self.image_preview.configure(text=f"Error: {exc}"),
                                   self._busy_set(False)))

    def _show_visual(self, b64, landscape):
        self._busy_set(False)
        folder = self._paths()["backgrounds" if landscape else "portraits"]
        os.makedirs(folder, exist_ok=True)
        prefix = "bg" if landscape else "portrait"
        path = os.path.join(folder, f"{prefix}_{int(time.time())}.png")
        try:
            with open(path, "wb") as f:
                f.write(base64.b64decode(b64))
        except Exception:
            pass
        if _PIL_OK:
            try:
                img = Image.open(io.BytesIO(base64.b64decode(b64)))
                ctk_img = ctk.CTkImage(light_image=img, dark_image=img,
                                       size=(340, 340))
                self.image_preview.configure(image=ctk_img, text="")
                self.image_preview.image = ctk_img
            except Exception:
                pass
        self.app.status(f"Saved render: {path}")

    def _listen(self):
        text = self.get_selection() or self.get_text_before_cursor()[-500:]
        if not text.strip():
            self.app.status("Select text (or write some) to listen.")
            return
        self.app.status("Speaking...")

        def worker():
            try:
                res = self.app.tts.speak(text, play=True)
                msg = ("Played via " + res["engine"]) if res else "TTS is off."
            except Exception as exc:
                msg = f"TTS error: {exc}"
            self.after(0, lambda: self.app.status(msg))
        threading.Thread(target=worker, daemon=True).start()

    # ======================= draft edits ===================================
    def _insert_draft(self, text, note="AI insertion"):
        if not text:
            return
        self.text.configure(state="normal")
        start = self.text.index("insert")
        self.text.insert("insert", text)
        end = self.text.index("insert")
        hid = self._draft_seq
        self._draft_seq += 1
        tag = f"draft-{hid}"
        self.text.tag_add("draft-ins", start, end)
        self.text.tag_add(tag, start, end)
        self._drafts.append({"id": hid, "note": note, "tag": tag})
        self._update_word_count()
        self._refresh_draft_bar()
        self._persist_drafts()
        self._schedule_save()

    def _persist_drafts(self):
        if not self.current_chapter_id:
            return
        hunks = []
        for d in self._drafts:
            r = self.text.tag_ranges(d["tag"])
            if not r:
                continue
            start, end = r[0], r[1]
            start_off = len(self.text.get("1.0", start))
            length = len(self.text.get(start, end))
            if length <= 0:
                continue
            hunks.append({"id": d["id"], "note": d["note"],
                          "start": start_off, "length": length})
        chapters.write_drafts(self._paths()["chapters"],
                              self.current_chapter_id, hunks)

    def _load_drafts(self):
        for d in list(self._drafts):
            self.text.tag_delete(d["tag"])
        self.text.tag_remove("draft-ins", "1.0", "end")
        self._drafts = []
        for h in chapters.read_drafts(self._paths()["chapters"],
                                      self.current_chapter_id):
            hid = h.get("id", self._draft_seq)
            if isinstance(hid, int):
                self._draft_seq = max(self._draft_seq, hid + 1)
            tag = f"draft-{hid}"
            start = f"1.0+{h['start']}c"
            end = f"1.0+{h['start'] + h['length']}c"
            self.text.tag_add("draft-ins", start, end)
            self.text.tag_add(tag, start, end)
            self._drafts.append({"id": hid, "note": h.get("note", ""),
                                 "tag": tag})
        self._refresh_draft_bar()

    def _refresh_draft_bar(self):
        n = len(self._drafts)
        if n:
            self.draft_count_lbl.configure(
                text=f"{n} pending AI draft edit{'s' if n != 1 else ''}")
            self.draft_bar.grid()
        else:
            self.draft_bar.grid_remove()

    def _accept_draft(self, d):
        r = self.text.tag_ranges(d["tag"])
        if r:
            self.text.tag_remove("draft-ins", r[0], r[1])
        self.text.tag_delete(d["tag"])
        if d in self._drafts:
            self._drafts.remove(d)
        self._persist_drafts()
        self._refresh_draft_bar()
        self._schedule_save()

    def _reject_draft(self, d):
        r = self.text.tag_ranges(d["tag"])
        if r:
            self.text.delete(r[0], r[1])
        self.text.tag_delete(d["tag"])
        if d in self._drafts:
            self._drafts.remove(d)
        self._update_word_count()
        self._persist_drafts()
        self._refresh_draft_bar()
        self._schedule_save()

    def _accept_all_drafts(self):
        for d in list(self._drafts):
            self._accept_draft(d)

    def _reject_all_drafts(self):
        for d in list(self._drafts):
            self._reject_draft(d)

    def _review_drafts(self):
        if not self._drafts:
            return
        win = ctk.CTkToplevel(self)
        win.title("Review Draft Edits")
        win.geometry("520x460")
        win.configure(fg_color=theme.BG_APP)
        win.grid_columnconfigure(0, weight=1)
        win.grid_rowconfigure(0, weight=1)
        scroll = ctk.CTkScrollableFrame(win, fg_color=theme.BG_CARD)
        scroll.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)
        scroll.grid_columnconfigure(0, weight=1)

        def render():
            for w in scroll.winfo_children():
                w.destroy()
            if not self._drafts:
                ctk.CTkLabel(scroll, text="No pending draft edits.",
                             text_color=theme.TEXT_MUTED).grid(padx=12, pady=12)
                return
            for i, d in enumerate(self._drafts):
                r = self.text.tag_ranges(d["tag"])
                snippet = self.text.get(r[0], r[1])[:160] if r else ""
                card = ctk.CTkFrame(scroll, fg_color=theme.BG_SIDEBAR)
                card.grid(row=i, column=0, sticky="ew", padx=4, pady=4)
                card.grid_columnconfigure(0, weight=1)
                ctk.CTkLabel(card, text=d["note"], anchor="w",
                             text_color=theme.LIME,
                             font=ctk.CTkFont(size=12, weight="bold")
                             ).grid(row=0, column=0, sticky="ew", padx=8, pady=(6, 0))
                ctk.CTkLabel(card, text=snippet + ("..." if len(snippet) >= 160 else ""),
                             anchor="w", justify="left", wraplength=360,
                             text_color=theme.TEXT_PRIMARY
                             ).grid(row=1, column=0, sticky="ew", padx=8, pady=4)
                btns = ctk.CTkFrame(card, fg_color="transparent")
                btns.grid(row=0, column=1, rowspan=2, padx=6)
                ctk.CTkButton(btns, text="Accept", width=72,
                              command=lambda x=d: (self._accept_draft(x), render()),
                              **theme.primary_btn()).pack(pady=2)
                ctk.CTkButton(btns, text="Reject", width=72,
                              command=lambda x=d: (self._reject_draft(x), render()),
                              **theme.danger_btn()).pack(pady=2)
            self.text.see(self.text.tag_ranges(self._drafts[0]["tag"])[0])
        render()

    # ======================= lifecycle =====================================
    def on_show(self):
        pass

    def on_project_change(self):
        self._save_now()
        self.current_chapter_id = None
        self._chat_history = []
        self._ai_history = []
        self._ai_index = -1
        if hasattr(self, "agent_menu"):
            self.agent_menu.configure(values=self._agent_values())
        self._load_chapters()
