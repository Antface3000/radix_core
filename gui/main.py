"""RadixApp - the editor-first Mission Control shell.

Layout:
    +-------------------------------------------------------------+
    |  MARQUEE: [Radix Core] [Project v] [+ New] [Settings]  ...  |
    |                       ... [date | location | scene]         |
    +------+--------------------+---------------------------------+
    | rail |  feature dock      |  EDITOR (persistent center)     |
    |      |  (collapsible,     |                                 |
    |      |   pop-out-able)    |                                 |
    +------+--------------------+---------------------------------+
    |  status bar                                                 |
    +-------------------------------------------------------------+

The editor is always visible. Secondary features (Story Bible, Agents, Image
Gen, Voice, etc.) open in a left dock column and can be popped out into their
own window (CTkToplevel) for multi-monitor use. Owns the shared runtime:
Settings, AgentEngine, ComfyClient, TTSClient.
"""

import os
import threading
import time

import customtkinter as ctk

import config
from gui import theme
from gui.toast import ToastOverlay
from gui.tooltip import attach
from gui.panels.agents_panel import AgentsPanel
from gui.panels.projects_panel import ProjectsPanel
from gui.panels.storybible_panel import StoryBiblePanel
from gui.panels.imagegen_panel import ImageGenPanel
from gui.panels.tts_panel import TTSPanel
from gui.panels.settings_panel import SettingsPanel
from gui.panels.editor_panel import EditorPanel
from gui.panels.focus_panel import FocusPanel
from gui.panels.music_panel import MusicPanel
from gui.panels.help_panel import HelpPanel
from gui.panels.setup_panel import SetupPanel
from src import projects, service_launch, services, world_state, updater
from src.settings import Settings
from src.engine import AgentEngine
from src.writing_engine import WritingEngine
from src.comfyui import ComfyClient
from src.tts import TTSClient


class RadixApp(ctk.CTk):
    DOCK_MIN_W = 320
    DOCK_MAX_W = 900
    # App-level features kept out of the left rail (reachable from the marquee).
    RAIL_EXCLUDE = {"Setup", "Settings", "Help"}

    def __init__(self):
        super().__init__()
        projects.ensure_initialized()
        self.settings = Settings()
        theme.apply_theme(self.settings)

        self.engine = AgentEngine(settings=self.settings)
        self.engine.flush_callback = self.flush_project_context
        self.writing = WritingEngine(self.engine)
        self.comfy = ComfyClient(self.settings, self.engine)
        self.tts = TTSClient(self.settings)

        self.title(f"{config.APP_TITLE} v{config.APP_VERSION}")
        self.geometry(config.APP_GEOMETRY)
        self.minsize(1040, 700)
        self.configure(fg_color=theme.BG_APP)

        # Feature registry: (name, icon, panel class). Extended by later phases.
        self.features = [
            ("Story Bible", "\U0001F4D6", StoryBiblePanel),
            ("Agents", "\U0001F916", AgentsPanel),
            ("Projects", "\U0001F3E0", ProjectsPanel),
            ("Image Gen", "\U0001F5BC", ImageGenPanel),
            ("Voice", "\U0001F50A", TTSPanel),
            ("Focus", "\U0001F4CC", FocusPanel),
            ("Music", "\U0001F3B5", MusicPanel),
            ("Setup", "\U0001F50C", SetupPanel),
            ("Help", "\u2753", HelpPanel),
            ("Settings", "\u2699", SettingsPanel),
        ]
        self._feature_classes = {name: cls for name, _icon, cls in self.features}
        self._dock_name = None        # feature currently shown in the dock
        self._dock_panel = None       # its live panel instance
        self._dock_cache = {}         # name -> hidden panel (preserved on tab switch)
        self._windows = {}            # name -> (toplevel, panel) for pop-outs
        self._marquee_collapsed = False   # secondary marquee items in overflow?
        self._marquee_full_w = None       # px width needed to show everything
        self._overflow_win = None         # the open overflow drawer, if any

        # Columns: 0 rail | 1 dock | 2 splitter | 3 editor (stretches).
        self.grid_columnconfigure(3, weight=1)
        self.grid_rowconfigure(1, weight=1)

        self._build_marquee()
        self._build_rail()
        self._build_dock()
        self._build_splitter()
        self._build_editor()
        self._build_statusbar()
        self._toast = ToastOverlay(self)

        # Collapse the marquee's secondary controls into a "More" drawer when the
        # window is too narrow to show them without clipping.
        self.bind("<Configure>", self._reflow_marquee)
        self.after(250, self._measure_marquee)

        self.refresh_header()
        self.refresh_worldbar()
        self._heartbeat_job = None
        self._setup_prompted = False
        self._pending_update = None
        self._heartbeat()
        self._startup_services()

        if self.settings.get("ui.show_startup", True):
            # Hide the main window until the launcher choice is made, so it
            # doesn't appear behind the startup dialog.
            self.withdraw()
            self.after(100, self._show_startup)
        else:
            self.after(400, self._schedule_update_check)

    def flush_project_context(self):
        """Persist unsaved Story Bible / World State / Lore before agent runs."""
        for panel in self._open_panels():
            if isinstance(panel, StoryBiblePanel):
                panel.flush_if_dirty()

    def refresh_setting_previews(self):
        for panel in self._open_panels():
            if isinstance(panel, AgentsPanel):
                panel._refresh_setting_status()

    def refresh_panel_fonts(self):
        """Apply panel text size to all secondary CTkTextboxes."""
        from gui import panel_text
        panel_text.apply_font_tree(self.editor, self.settings)
        for panel in self._open_panels():
            panel_text.apply_font_tree(panel, self.settings)

    def _story_bible_panel(self):
        if isinstance(self._dock_panel, StoryBiblePanel):
            return self._dock_panel
        for panel in self._dock_cache.values():
            if isinstance(panel, StoryBiblePanel):
                return panel
        for _w, panel in self._windows.values():
            if isinstance(panel, StoryBiblePanel):
                return panel
        return None

    def _schedule_update_check(self):
        if not self.settings.get("updates.check_on_startup", True):
            return
        last = float(self.settings.get("updates.last_check_ts") or 0)
        if time.time() - last < 86400:
            return

        def worker():
            try:
                result = updater.check_for_update()
            except Exception:
                return
            self.settings.set("updates.last_check_ts", time.time(), save=True)
            if result and result.available:
                dismissed = self.settings.get("updates.dismissed_version")
                if dismissed != result.remote_version:
                    self.after(0, lambda r=result: self._offer_update(r))
        threading.Thread(target=worker, daemon=True).start()

    def _offer_update(self, result):
        self._pending_update = result
        self.status(f"Update available: v{result.remote_version}")
        win = ctk.CTkToplevel(self)
        win.title("Update available")
        win.geometry("440x220")
        win.configure(fg_color=theme.BG_APP)
        win.attributes("-topmost", True)
        ctk.CTkLabel(
            win,
            text=f"Radix Core v{result.remote_version} is available "
                 f"(you have v{result.local_version}).",
            wraplength=400, justify="left",
        ).pack(anchor="w", padx=20, pady=(16, 8))
        if result.summary:
            ctk.CTkLabel(win, text=result.summary, text_color=theme.TEXT_MUTED,
                         wraplength=400, justify="left").pack(anchor="w", padx=20, pady=(0, 8))

        btns = ctk.CTkFrame(win, fg_color="transparent")
        btns.pack(fill="x", padx=20, pady=12)

        def _now():
            win.destroy()
            updater.apply_update()
            self.destroy()

        def _later():
            win.destroy()

        def _skip():
            self.settings.set("updates.dismissed_version", result.remote_version)
            win.destroy()

        ctk.CTkButton(btns, text="Update now", command=_now,
                      **theme.primary_btn()).pack(side="left", padx=(0, 8))
        ctk.CTkButton(btns, text="Later", command=_later,
                      **theme.secondary_btn()).pack(side="left", padx=(0, 8))
        ctk.CTkButton(btns, text="Skip this version", command=_skip,
                      **theme.ghost_btn()).pack(side="left")

    def _build_marquee(self):
        bar = ctk.CTkFrame(self, fg_color=theme.BG_SIDEBAR, height=54,
                           corner_radius=0)
        bar.grid(row=0, column=0, columnspan=4, sticky="ew")
        bar.grid_columnconfigure(5, weight=1)
        bar.grid_propagate(False)

        self._mq_logo = ctk.CTkLabel(bar, text="RADIX CORE",
                     font=ctk.CTkFont(size=18, weight="bold"),
                     text_color=theme.LIME)
        self._mq_logo.grid(row=0, column=0, padx=(16, 18), pady=10)

        self._mq_proj_label = ctk.CTkLabel(bar, text="Project",
                                           text_color=theme.TEXT_MUTED)
        self._mq_proj_label.grid(row=0, column=1, padx=(0, 6))
        self.project_menu = ctk.CTkOptionMenu(bar, values=["default"], width=200,
                                              command=self._on_project_select)
        self.project_menu.grid(row=0, column=2, pady=10)
        self._mq_new_btn = ctk.CTkButton(bar, text="+ New", width=64,
                                         command=self._new_project,
                                         **theme.secondary_btn())
        self._mq_new_btn.grid(row=0, column=3, padx=8)
        left_btns = ctk.CTkFrame(bar, fg_color="transparent")
        self._mq_left_extra = left_btns
        left_btns.grid(row=0, column=4, padx=(0, 8))
        setup_btn = ctk.CTkButton(left_btns, text="\U0001F50C Setup", width=88,
                                  command=lambda: self.open_feature("Setup"),
                                  **theme.secondary_btn())
        setup_btn.pack(side="left", padx=(0, 8))
        attach(setup_btn, "Service Setup: point Radix at your ComfyUI / AllTalk "
                          "installs, verify health, and sync assets.")
        ctk.CTkButton(left_btns, text="\u2699 Settings", width=96,
                      command=lambda: self.open_feature("Settings"),
                      **theme.secondary_btn()).pack(side="left")

        # Right cluster: help + world state readout + service health.
        right = ctk.CTkFrame(bar, fg_color="transparent")
        self._mq_right = right
        right.grid(row=0, column=6, sticky="e", padx=14)
        help_btn = ctk.CTkButton(right, text="?", width=34, height=34,
                                 command=lambda: self.open_feature("Help"),
                                 **theme.secondary_btn())
        help_btn.pack(side="left", padx=(0, 12))
        attach(help_btn, "Open the in-app User Guide and installation tutorial.")
        self.worldbar = ctk.CTkButton(
            right, text="", anchor="e", height=34,
            command=lambda: self.open_feature("Story Bible"),
            **theme.ghost_btn())
        self.worldbar.pack(side="left", padx=(0, 12))
        attach(self.worldbar, "Current date / location / scene for this project. "
                              "Click to edit in Story Bible -> World State.")
        health = ctk.CTkFrame(right, fg_color="transparent")
        health.pack(side="left")
        attach(health, "Live service heartbeat: ComfyUI (images) and AllTalk/Piper "
                       "(voice). Green = connected. Open Setup to configure.")
        self.health_dots = {}
        for key, label in (("comfyui", "ComfyUI"), ("alltalk", "AllTalk"),
                           ("piper", "Piper")):
            dot = ctk.CTkLabel(health, text=f"\u25CF {label}",
                               text_color=theme.TEXT_MUTED,
                               font=ctk.CTkFont(size=11))
            dot.pack(side="left", padx=(0, 8))
            self.health_dots[key] = dot
        # Keep a reference so the Setup panel can read the latest probe result.
        self.last_health = None

        # Overflow "More" button: hidden until the window is too narrow to fit
        # the Setup/Settings + help/world/health clusters above.
        self.more_btn = ctk.CTkButton(bar, text="\u22EF More", width=82, height=34,
                                      command=self._toggle_overflow_drawer,
                                      **theme.secondary_btn())
        self.more_btn.grid(row=0, column=6, sticky="e", padx=14)
        attach(self.more_btn, "Show Setup, Settings, Help, world state and service "
                              "health that don't fit at this window size.")
        self.more_btn.grid_remove()

    def _build_rail(self):
        rail = ctk.CTkFrame(self, fg_color=theme.BG_SIDEBAR, width=64,
                            corner_radius=0)
        rail.grid(row=1, column=0, sticky="nsw")
        rail.grid_propagate(False)
        self.rail_buttons = {}
        for name, icon, _cls in self.features:
            # App-level features (Setup, Settings, Help) live in the top marquee,
            # so the rail stays focused on content panels only.
            if name in self.RAIL_EXCLUDE:
                continue
            b = ctk.CTkButton(rail, text=f"{icon}\n{name}", width=56, height=52,
                              font=ctk.CTkFont(size=10),
                              command=lambda n=name: self.toggle_feature(n),
                              **theme.ghost_btn())
            b.pack(pady=(8 if not self.rail_buttons else 4, 0), padx=4)
            attach(b, f"Open {name} in the side dock (click again to close). "
                      f"Use 'Pop out' to move it to another monitor.")
            self.rail_buttons[name] = b

    def _build_dock(self):
        try:
            width = int(self.settings.get("ui.dock_width", 460))
        except (TypeError, ValueError):
            width = 460
        self._dock_width = max(self.DOCK_MIN_W, min(self.DOCK_MAX_W, width))
        self.dock = ctk.CTkFrame(self, fg_color=theme.BG_CARD,
                                 width=self._dock_width, corner_radius=0)
        self.dock.grid(row=1, column=1, sticky="nsew")
        self.dock.grid_propagate(False)
        self.dock.grid_columnconfigure(0, weight=1)
        self.dock.grid_rowconfigure(1, weight=1)

        head = ctk.CTkFrame(self.dock, fg_color=theme.BG_SIDEBAR, height=36,
                            corner_radius=0)
        head.grid(row=0, column=0, sticky="ew")
        head.grid_columnconfigure(0, weight=1)
        self.dock_title = ctk.CTkLabel(head, text="", anchor="w",
                                       font=ctk.CTkFont(size=13, weight="bold"),
                                       text_color=theme.LIME)
        self.dock_title.grid(row=0, column=0, sticky="w", padx=12, pady=6)
        popout_btn = ctk.CTkButton(head, text="\u2197 Pop out", width=78,
                                   command=self._popout_current, **theme.ghost_btn())
        popout_btn.grid(row=0, column=1, padx=2, pady=4)
        attach(popout_btn, "Open this panel in its own window for use on a "
                           "second monitor.")
        close_btn = ctk.CTkButton(head, text="\u2715", width=32,
                                  command=self.close_dock, **theme.ghost_btn())
        close_btn.grid(row=0, column=2, padx=(2, 8), pady=4)
        attach(close_btn, "Close this panel.")

        self.dock_body = ctk.CTkFrame(self.dock, fg_color=theme.BG_APP,
                                      corner_radius=0)
        self.dock_body.grid(row=1, column=0, sticky="nsew")
        self.dock_body.grid_columnconfigure(0, weight=1)
        self.dock_body.grid_rowconfigure(0, weight=1)
        self.dock.grid_remove()  # collapsed until a feature is opened

    def _build_splitter(self):
        """Thin draggable handle to resize the dock; contents reflow to fit."""
        self.splitter = ctk.CTkFrame(self, width=6, corner_radius=0,
                                     fg_color=theme.BORDER)
        self.splitter.grid(row=1, column=2, sticky="ns")
        self.splitter.grid_propagate(False)
        try:
            self.splitter.configure(cursor="sb_h_double_arrow")
        except Exception:
            pass
        self.splitter.bind("<Enter>",
                           lambda _e: self.splitter.configure(fg_color=theme.BORDER_ACTIVE))
        self.splitter.bind("<Leave>",
                           lambda _e: self.splitter.configure(fg_color=theme.BORDER))
        self.splitter.bind("<B1-Motion>", self._on_splitter_drag)
        self.splitter.bind("<ButtonRelease-1>", self._on_splitter_release)
        self.splitter.grid_remove()  # only shown alongside an open dock

    def _on_splitter_drag(self, event):
        new_w = event.x_root - self.dock.winfo_rootx()
        new_w = max(self.DOCK_MIN_W, min(self.DOCK_MAX_W, int(new_w)))
        self._dock_width = new_w
        self.dock.configure(width=new_w)

    def _on_splitter_release(self, _event):
        self.settings.set("ui.dock_width", int(self._dock_width))

    def _build_editor(self):
        self.editor = EditorPanel(self, self)
        self.editor.grid(row=1, column=3, sticky="nsew")

    def _build_statusbar(self):
        bar = ctk.CTkFrame(self, fg_color=theme.BG_SIDEBAR, height=26,
                           corner_radius=0)
        bar.grid(row=2, column=0, columnspan=4, sticky="ew")
        self.status_lbl = ctk.CTkLabel(bar, text="Ready.", anchor="w",
                                       text_color=theme.TEXT_MUTED)
        self.status_lbl.pack(side="left", padx=16)

    # ======================= marquee overflow drawer =======================
    def _measure_marquee(self):
        """Record the width needed to show the full marquee, then reflow once."""
        try:
            self.update_idletasks()
            parts = (self._mq_logo, self._mq_proj_label, self.project_menu,
                     self._mq_new_btn, self._mq_left_extra, self._mq_right)
            # Natural widths of every cluster + generous padding/breathing room so
            # we collapse a little BEFORE anything actually clips.
            self._marquee_full_w = sum(w.winfo_reqwidth() for w in parts) + 180
        except Exception:
            self._marquee_full_w = 1180
        self._reflow_marquee()

    def _reflow_marquee(self, _event=None):
        """Move secondary marquee items in/out of the overflow drawer on resize."""
        if self._marquee_full_w is None:
            return
        collapse = self.winfo_width() < self._marquee_full_w
        if collapse == self._marquee_collapsed:
            return
        self._marquee_collapsed = collapse
        if collapse:
            self._mq_left_extra.grid_remove()
            self._mq_right.grid_remove()
            self.more_btn.grid()
        else:
            self.more_btn.grid_remove()
            self._mq_left_extra.grid()
            self._mq_right.grid()
            self._close_overflow_drawer()

    def _toggle_overflow_drawer(self):
        if self._overflow_win is not None:
            self._close_overflow_drawer()
        else:
            self._open_overflow_drawer()

    def _close_overflow_drawer(self):
        if self._overflow_win is not None:
            try:
                self._overflow_win.destroy()
            except Exception:
                pass
            self._overflow_win = None

    def _open_overflow_drawer(self):
        """Frameless panel under the More button holding the collapsed controls.

        Rebuilt on each open so it always reflects the current world state and
        live service health (no second set of widgets to keep in sync)."""
        try:
            win = ctk.CTkToplevel(self)
            win.overrideredirect(True)
        except Exception:
            return
        self._overflow_win = win
        win.configure(fg_color=theme.BG_CARD)
        try:
            win.attributes("-topmost", True)
        except Exception:
            pass

        def _act(name):
            self._close_overflow_drawer()
            self.open_feature(name)

        pad = dict(padx=10, fill="x")
        ctk.CTkLabel(win, text="More", anchor="w", text_color=theme.TEXT_MUTED,
                     font=ctk.CTkFont(size=12, weight="bold")
                     ).pack(**pad, pady=(10, 2))
        ctk.CTkButton(win, text="\U0001F50C  Setup", anchor="w",
                      command=lambda: _act("Setup"),
                      **theme.secondary_btn()).pack(**pad, pady=3)
        ctk.CTkButton(win, text="\u2699  Settings", anchor="w",
                      command=lambda: _act("Settings"),
                      **theme.secondary_btn()).pack(**pad, pady=3)
        ctk.CTkButton(win, text="?  Help", anchor="w",
                      command=lambda: _act("Help"),
                      **theme.secondary_btn()).pack(**pad, pady=3)

        ctk.CTkFrame(win, height=1, fg_color=theme.BORDER).pack(**pad, pady=(8, 4))
        ctk.CTkButton(win, text=self.worldbar.cget("text") or "World", anchor="w",
                      command=lambda: _act("Story Bible"),
                      **theme.ghost_btn()).pack(**pad, pady=3)

        health = ctk.CTkFrame(win, fg_color="transparent")
        health.pack(**pad, pady=(4, 12))
        for key, label in (("comfyui", "ComfyUI"), ("alltalk", "AllTalk"),
                           ("piper", "Piper")):
            src = self.health_dots.get(key)
            color = src.cget("text_color") if src else theme.TEXT_MUTED
            ctk.CTkLabel(health, text=f"\u25CF {label}", text_color=color,
                         font=ctk.CTkFont(size=11)).pack(side="left", padx=(0, 10))

        # Position the drawer under the More button, right-aligned to it.
        self.update_idletasks()
        width = 230
        bx = self.more_btn.winfo_rootx() + self.more_btn.winfo_width()
        by = self.more_btn.winfo_rooty() + self.more_btn.winfo_height() + 4
        win.geometry(f"{width}x250+{max(0, bx - width)}+{by}")

        win.bind("<FocusOut>", lambda _e: self._close_overflow_drawer())
        win.bind("<Escape>", lambda _e: self._close_overflow_drawer())
        try:
            win.focus_force()
        except Exception:
            pass

    # ======================= feature dock / pop-out ========================
    def toggle_feature(self, name):
        """Rail click: open in dock, or collapse if already the active one."""
        if name in self._windows:
            self._windows[name][0].focus()
            return
        if self._dock_name == name:
            self.close_dock()
        else:
            self.open_feature(name)

    def _stash_dock_panel(self):
        """Hide the active dock panel without destroying it (keeps chat/state)."""
        if self._dock_panel is None or not self._dock_name:
            return
        self._dock_panel.grid_remove()
        self._dock_cache[self._dock_name] = self._dock_panel
        self._dock_panel = None
        self._dock_name = None

    def open_feature(self, name):
        if name in self._windows:
            self._windows[name][0].focus()
            return
        cls = self._feature_classes.get(name)
        if cls is None:
            self.status(f"'{name}' is not available yet.")
            return
        self._stash_dock_panel()
        self.dock.configure(width=self._dock_width)
        self.dock.grid()
        self.splitter.grid()
        self.dock_title.configure(text=name)
        panel = self._dock_cache.get(name)
        if panel is None:
            try:
                panel = cls(self.dock_body, self)
            except Exception:
                panel = None
        else:
            try:
                if not panel.winfo_exists():
                    panel = cls(self.dock_body, self)
            except Exception:
                panel = cls(self.dock_body, self)
        self._dock_cache[name] = panel
        panel.grid(row=0, column=0, sticky="nsew")
        self._dock_panel = panel
        self._dock_name = name
        self._sync_rail()
        panel.on_show()

    def close_dock(self):
        self._stash_dock_panel()
        self.dock.grid_remove()
        self.splitter.grid_remove()
        self._sync_rail()

    def open_help(self, doc="User Guide"):
        """Open the Help panel on a specific document (used by the welcome window)."""
        self.open_feature("Help")
        panel = self._dock_panel
        if panel is None and "Help" in self._windows:
            panel = self._windows["Help"][1]
        if panel is not None and hasattr(panel, "show_doc"):
            panel.show_doc(doc)

    # ======================= startup project launcher =====================
    def _show_startup(self):
        """On-launch chooser: continue the last project, open another, or start a
        new one. Replaces the old welcome popup; guide links live at the bottom."""
        try:
            win = ctk.CTkToplevel(self)
        except Exception:
            self.deiconify()  # never leave the app stuck with no window
            return
        win.title("Radix Core")
        win.geometry("560x560")
        win.configure(fg_color=theme.BG_APP)
        # Not transient: the main window is withdrawn, and a transient child is
        # hidden along with its master, which would leave nothing on screen.
        try:
            win.attributes("-topmost", True)
            win.grab_set()
        except Exception:
            pass
        win.grid_columnconfigure(0, weight=1)
        win.grid_rowconfigure(4, weight=1)

        ctk.CTkLabel(win, text=f"Radix Core  v{config.APP_VERSION}",
                     font=ctk.CTkFont(size=22, weight="bold"),
                     text_color=theme.LIME).grid(row=0, column=0, sticky="w",
                                                 padx=20, pady=(18, 2))
        ctk.CTkLabel(win, text="Continue where you left off, open a project, or "
                              "start a new one.", text_color=theme.TEXT_MUTED,
                     anchor="w").grid(row=1, column=0, sticky="w", padx=20,
                                      pady=(0, 10))

        def _close():
            self._finish_startup(win)

        active = projects.get_active_project()
        active_id = active["id"] if active else None

        top = ctk.CTkFrame(win, fg_color="transparent")
        top.grid(row=2, column=0, sticky="ew", padx=20, pady=(0, 6))
        top.grid_columnconfigure(0, weight=1)
        cont_label = (f"Continue  -  {active['name']}" if active
                      else "Continue")
        ctk.CTkButton(top, text=cont_label, command=_close,
                      **theme.primary_btn()).grid(row=0, column=0, sticky="ew",
                                                  padx=(0, 8))
        ctk.CTkButton(top, text="+ New Project", width=130,
                      command=lambda: self._startup_new(win),
                      **theme.secondary_btn()).grid(row=0, column=1)

        ctk.CTkLabel(win, text="Your projects", anchor="w",
                     font=ctk.CTkFont(size=13, weight="bold"),
                     text_color=theme.TEXT_PRIMARY).grid(row=3, column=0,
                                                         sticky="w", padx=20,
                                                         pady=(6, 0))

        lst = ctk.CTkScrollableFrame(win, fg_color=theme.BG_CARD)
        lst.grid(row=4, column=0, sticky="nsew", padx=20, pady=(4, 6))
        lst.grid_columnconfigure(0, weight=1)

        plist = sorted(projects.list_projects(),
                       key=lambda p: p.get("lastOpenedAt", ""), reverse=True)
        for i, project in enumerate(plist):
            is_active = project["id"] == active_id
            row = ctk.CTkFrame(lst, fg_color=theme.BG_SIDEBAR)
            row.grid(row=i, column=0, sticky="ew", pady=4, padx=4)
            row.grid_columnconfigure(0, weight=1)
            label = project["name"] + ("   (current)" if is_active else "")
            ctk.CTkLabel(row, text=label, anchor="w",
                         font=ctk.CTkFont(size=14,
                                          weight="bold" if is_active else "normal"),
                         text_color=theme.LIME if is_active else theme.TEXT_PRIMARY
                         ).grid(row=0, column=0, sticky="w", padx=12, pady=10)
            ctk.CTkButton(row, text="Open", width=72,
                          command=lambda p=project: self._startup_open(win, p),
                          **(theme.secondary_btn() if is_active else {})
                          ).grid(row=0, column=1, padx=(4, 8), pady=8)

        footer = ctk.CTkFrame(win, fg_color="transparent")
        footer.grid(row=5, column=0, sticky="ew", padx=20, pady=(2, 6))
        footer.grid_columnconfigure(2, weight=1)

        def _open_guide(doc):
            self._finish_startup(win)
            self.open_help(doc)

        ctk.CTkButton(footer, text="Open guide", width=110,
                      command=lambda: _open_guide("User Guide"),
                      **theme.ghost_btn()).grid(row=0, column=0, padx=(0, 8))
        ctk.CTkButton(footer, text="Installation", width=110,
                      command=lambda: _open_guide("Installation"),
                      **theme.ghost_btn()).grid(row=0, column=1)

        show_var = ctk.BooleanVar(value=self.settings.get("ui.show_startup", True))

        def _toggle():
            self.settings.set("ui.show_startup", bool(show_var.get()))
        ctk.CTkCheckBox(win, text="Show this on startup", variable=show_var,
                        command=_toggle).grid(row=6, column=0, sticky="w",
                                              padx=20, pady=(0, 16))
        win.protocol("WM_DELETE_WINDOW", _close)

    def _finish_startup(self, win):
        """Close the launcher and reveal the (previously hidden) main window."""
        try:
            win.grab_release()
        except Exception:
            pass
        try:
            win.destroy()
        except Exception:
            pass
        try:
            self.deiconify()
            self.lift()
            self.focus_force()
        except Exception:
            pass
        self.after(400, self._schedule_update_check)

    def _startup_open(self, win, project):
        if project["id"] != self.engine.project_id:
            self.switch_project(project["id"])
        self._finish_startup(win)

    def _startup_new(self, win):
        # Reveal the main window first so the name dialog isn't parented to a
        # withdrawn window (which would hide it).
        self._finish_startup(win)
        dlg = ctk.CTkInputDialog(text="Name the new project:", title="New Project")
        name = dlg.get_input()
        if name:
            project = projects.create_project(name)
            self.switch_project(project["id"])

    def _popout_current(self):
        if not self._dock_name:
            return
        name = self._dock_name
        self.close_dock()
        # Pop-out builds a fresh panel in a new window; drop the cached dock copy
        # so we don't keep two live instances (e.g. duplicate agent poll loops).
        cached = self._dock_cache.pop(name, None)
        if cached is not None:
            try:
                cached.destroy()
            except Exception:
                pass
        self._open_window(name)

    def _open_window(self, name):
        cls = self._feature_classes.get(name)
        if cls is None:
            return
        win = ctk.CTkToplevel(self)
        win.title(f"Radix Core - {name}")
        win.geometry("560x720")
        win.configure(fg_color=theme.BG_APP)
        win.grid_columnconfigure(0, weight=1)
        win.grid_rowconfigure(0, weight=1)
        panel = cls(win, self)
        panel.grid(row=0, column=0, sticky="nsew")
        self._windows[name] = (win, panel)
        self._sync_rail()

        def _on_close():
            self._windows.pop(name, None)
            win.destroy()
            self._sync_rail()
        win.protocol("WM_DELETE_WINDOW", _on_close)
        win.after(120, panel.on_show)

    def _sync_rail(self):
        for name, btn in self.rail_buttons.items():
            if name == self._dock_name or name in self._windows:
                btn.configure(fg_color=theme.LIME_DIM, text_color=theme.BG_APP)
            else:
                # Elevated fill (not transparent) so resting buttons stay
                # visible against the near-black sidebar.
                btn.configure(fg_color=theme.BG_ELEVATED,
                              text_color=theme.TEXT_PRIMARY)

    def _open_panels(self):
        """All live feature panels (docked, cached, and popped-out)."""
        panels = []
        seen = set()
        if self._dock_panel is not None:
            panels.append(self._dock_panel)
            seen.add(id(self._dock_panel))
        for panel in self._dock_cache.values():
            if id(panel) in seen:
                continue
            try:
                if panel.winfo_exists():
                    panels.append(panel)
                    seen.add(id(panel))
            except Exception:
                pass
        for _w, p in self._windows.values():
            if id(p) not in seen:
                panels.append(p)
        return panels

    # ======================= project management ============================
    def refresh_header(self):
        plist = projects.list_projects()
        names = [p["name"] for p in plist]
        self._name_to_id = {p["name"]: p["id"] for p in plist}
        active = projects.get_active_project()
        self.project_menu.configure(values=names or ["default"])
        if active:
            self.project_menu.set(active["name"])

    def _on_project_select(self, name):
        pid = getattr(self, "_name_to_id", {}).get(name)
        if pid and pid != self.engine.project_id:
            self.switch_project(pid)

    def _new_project(self):
        dlg = ctk.CTkInputDialog(text="Name the new project:", title="New Project")
        name = dlg.get_input()
        if not name:
            return
        project = projects.create_project(name)
        self.switch_project(project["id"])

    def switch_project(self, project_id):
        self.engine.set_project(project_id)
        self.refresh_header()
        self.refresh_worldbar()
        self.editor.on_project_change()
        for panel in self._open_panels():
            panel.on_project_change()
        active = projects.get_active_project()
        self.status(f"Switched to project '{active['name'] if active else project_id}'.")

    def refresh_agents(self):
        for panel in self._open_panels():
            if isinstance(panel, AgentsPanel):
                panel.on_project_change()

    # ======================= world state marquee ===========================
    def refresh_worldbar(self):
        try:
            ws = world_state.read(self.engine.paths["world_state"])
        except Exception:
            ws = {}
        date = ws.get("currentDate") or "-"
        loc = ws.get("currentLocation") or "-"
        scene = ws.get("scene") or "-"
        self.worldbar.configure(
            text=f"World state  -  Date: {date}   Location: {loc}   Scene: {scene}")

    # ======================= status / health ===============================
    def status(self, text):
        self.status_lbl.configure(text=text)

    def toast(self, message, kind="success", duration_ms=2600):
        """Show a brief on-screen toast (also updates the status bar)."""
        self.status(message)
        self._toast.show(message, kind=kind, duration_ms=duration_ms)

    def saved(self, message):
        """Save confirmation: status bar + success toast."""
        self.toast(message, kind="success")

    def _startup_services(self):
        """Background: auto-launch AllTalk if needed; notify about ComfyUI.

        When the launcher .bat already ran the pre-launch service step
        (RADIX_SERVICES_PRELAUNCHED), skip re-launching here - the heartbeat
        still refreshes the health dots - so we don't duplicate the work.
        """
        if os.environ.get("RADIX_SERVICES_PRELAUNCHED") == "1":
            self.refresh_health()
            return

        def worker():
            try:
                _plan, notices = service_launch.run_startup(self.settings)
            except Exception:
                return
            if notices:
                self.after(0, lambda: self.status("  |  ".join(notices)))
        threading.Thread(target=worker, daemon=True).start()

    _LABELS = {"comfyui": "ComfyUI", "alltalk": "AllTalk", "piper": "Piper"}

    def _initial_health(self):
        """One heartbeat probe (runs in a worker thread)."""
        res = services.check_all(self.settings)
        self.after(0, lambda: self._apply_health(res))

    def _apply_health(self, res):
        self.last_health = res
        for key, dot in self.health_dots.items():
            r = res.get(key, {})
            ok = bool(r.get("ok"))
            dot.configure(text=f"\u25CF {self._LABELS.get(key, key)}",
                          text_color=(theme.GREEN if ok else theme.RED))
        # Let an open Setup panel refresh its checklist too.
        panel = self._dock_panel if self._dock_name == "Setup" else \
            (self._windows.get("Setup") or (None, None))[1]
        if panel is not None and hasattr(panel, "on_health"):
            try:
                panel.on_health(res)
            except Exception:
                pass
        # First-run nudge: if the user hasn't done setup and something is down,
        # open Service Setup once so they can point Radix at their installs.
        if not self._setup_prompted:
            self._setup_prompted = True
            if not self.settings.get("ui.setup_done", False) and \
                    not all(r.get("ok") for r in res.values()):
                self.after(600, lambda: self.open_feature("Setup"))

    def refresh_health(self):
        """Manual one-off refresh (also used by Setup's Test button)."""
        threading.Thread(target=self._initial_health, daemon=True).start()

    def _heartbeat(self):
        """Periodic, non-locking health loop; interval is user-adjustable."""
        threading.Thread(target=self._initial_health, daemon=True).start()
        try:
            secs = int(self.settings.get("services.heartbeat_interval_s",
                                         config.HEARTBEAT_INTERVAL_S))
        except (TypeError, ValueError):
            secs = config.HEARTBEAT_INTERVAL_S
        secs = max(5, secs)
        self._heartbeat_job = self.after(secs * 1000, self._heartbeat)

    def restart_heartbeat(self):
        """Re-arm the heartbeat now (e.g. after the interval is changed)."""
        if getattr(self, "_heartbeat_job", None) is not None:
            try:
                self.after_cancel(self._heartbeat_job)
            except Exception:
                pass
            self._heartbeat_job = None
        self._heartbeat()


# Backwards-compatible alias for run.py.
RadixGUI = RadixApp


if __name__ == "__main__":
    app = RadixApp()
    app.mainloop()
