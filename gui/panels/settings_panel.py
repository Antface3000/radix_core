"""Settings Control Center - one panel to control the whole unit.

Backed by src/settings.py: changes persist to data/global.json and
data/agents.json (+ per-project agents.json) and apply live. Sub-sections:
Agents, Models, Orchestration, Services, Image, Appearance.
"""

import threading

import customtkinter as ctk

import config
from gui import theme
from gui import panel_text
from gui.panels.base import BasePanel
from gui.tooltip import attach
from src import services

MODEL_KEYS = list(config.MODEL_REGISTRY.keys())


class SettingsPanel(BasePanel):
    title = "Settings"

    def __init__(self, master, app):
        super().__init__(master, app)
        self.grid_rowconfigure(1, weight=1)
        self.header("Settings Control Center",
                    "Configure agents, models, orchestration, services, images, "
                    "and appearance. Changes save immediately.")
        self.tabs = ctk.CTkTabview(self, fg_color=theme.BG_CARD)
        self.tabs.grid(row=1, column=0, sticky="nsew", padx=16, pady=(4, 16))
        for name in ("Agents", "Editor", "Models", "Orchestration", "Services",
                     "Image", "Appearance"):
            self.tabs.add(name)
        self._build_agents(self.tabs.tab("Agents"))
        self._build_editor(self.tabs.tab("Editor"))
        self._build_models(self.tabs.tab("Models"))
        self._build_orchestration(self.tabs.tab("Orchestration"))
        self._build_services(self.tabs.tab("Services"))
        self._build_image(self.tabs.tab("Image"))
        self._build_appearance(self.tabs.tab("Appearance"))
        theme.style_tabview(self.tabs)

    @property
    def s(self):
        return self.app.settings

    # ----------------------- Agents ----------------------------------------
    def _build_agents(self, tab):
        tab.grid_rowconfigure(1, weight=1)
        tab.grid_columnconfigure(0, weight=1)
        top = ctk.CTkFrame(tab, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", pady=6)
        ctk.CTkLabel(top, text="Editing scope:").pack(side="left", padx=6)
        self.agent_scope = ctk.CTkSegmentedButton(
            top, values=["Global Default", "Current Project"],
            command=lambda _v: self._reload_agents())
        self.agent_scope.set("Global Default")
        self.agent_scope.pack(side="left", padx=6)
        attach(self.agent_scope, "Global Default applies to every project; Current "
                                 "Project saves overrides only for the open project.")
        ctk.CTkLabel(top, text="(Project overrides win over the global default.)",
                     text_color=theme.TEXT_MUTED).pack(side="left", padx=8)

        self.agent_rows = ctk.CTkScrollableFrame(tab, fg_color=theme.BG_SIDEBAR)
        self.agent_rows.grid(row=1, column=0, sticky="nsew", pady=6)
        self.agent_rows.grid_columnconfigure(0, weight=1)
        self._reload_agents()

    def _agent_scope_key(self):
        return "global" if self.agent_scope.get() == "Global Default" else "project"

    def _agent_project_id(self):
        return self.app.engine.project_id if self._agent_scope_key() == "project" else None

    def _reload_agents(self):
        for w in self.agent_rows.winfo_children():
            w.destroy()
        scope = self._agent_scope_key()
        pid = self._agent_project_id()
        resolved = self.s.personas(self.app.engine.project_id)
        for i, p in enumerate(resolved):
            self._agent_row(i, p, scope, pid)

    def _agent_row(self, i, p, scope, pid):
        key = p["key"]
        row = ctk.CTkFrame(self.agent_rows, fg_color=theme.BG_CARD)
        row.grid(row=i, column=0, sticky="ew", pady=3, padx=3)
        row.grid_columnconfigure(1, weight=1)

        enabled = ctk.BooleanVar(value=bool(p.get("enabled", True)))
        ctk.CTkCheckBox(row, text="", width=24, variable=enabled).grid(row=0, column=0, padx=(8, 0))
        ctk.CTkLabel(row, text=p["display_name"], anchor="w",
                     font=ctk.CTkFont(size=13, weight="bold")
                     ).grid(row=0, column=1, sticky="w", padx=6, pady=6)

        model = ctk.CTkOptionMenu(row, values=MODEL_KEYS, width=110)
        model.set(p.get("model_key", MODEL_KEYS[0]))
        model.grid(row=0, column=2, padx=4)

        temp = ctk.CTkEntry(row, width=60)
        temp.insert(0, str(p.get("temperature", "")))
        temp.grid(row=0, column=3, padx=4)
        maxtok = ctk.CTkEntry(row, width=70)
        maxtok.insert(0, str(p.get("max_tokens", "")))
        maxtok.grid(row=0, column=4, padx=4)

        ctk.CTkButton(row, text="Prompt", width=70,
                      command=lambda: self._edit_prompt(key, scope, pid)
                      ).grid(row=0, column=5, padx=4)
        ctk.CTkButton(row, text="Save", width=60,
                      command=lambda: self._save_agent(key, scope, pid, enabled, model, temp, maxtok)
                      ).grid(row=0, column=6, padx=4)
        if scope == "project":
            ctk.CTkButton(row, text="Reset", width=60, **theme.secondary_btn(),
                          command=lambda: self._reset_agent(key)
                          ).grid(row=0, column=7, padx=(4, 8))

    def _save_agent(self, key, scope, pid, enabled, model, temp, maxtok):
        self.s.set_agent_field(scope, key, "enabled", bool(enabled.get()), pid)
        self.s.set_agent_field(scope, key, "model_key", model.get(), pid)
        t = temp.get().strip()
        if t:
            try:
                self.s.set_agent_field(scope, key, "temperature", float(t), pid)
            except ValueError:
                pass
        m = maxtok.get().strip()
        if m:
            try:
                self.s.set_agent_field(scope, key, "max_tokens", int(m), pid)
            except ValueError:
                pass
        self.app.saved(f"Saved agent '{key}' ({scope}).")
        self.app.refresh_agents()

    def _reset_agent(self, key):
        self.s.reset_agent(self.app.engine.project_id, key)
        self._reload_agents()
        self.app.refresh_agents()
        self.app.saved(f"Reset '{key}' to global default.")

    def _edit_prompt(self, key, scope, pid):
        resolved = self.s.persona(self.app.engine.project_id, key)
        win = ctk.CTkToplevel(self)
        win.title(f"System prompt - {key} ({scope})")
        win.geometry("680x520")
        win.transient(self.winfo_toplevel())
        box = panel_text.new_textbox(win, self.s, wrap="word")
        box.pack(fill="both", expand=True, padx=12, pady=12)
        box.insert("1.0", resolved.get("system_prompt", ""))

        def save():
            self.s.set_agent_field(scope, key, "system_prompt",
                                   box.get("1.0", "end").strip(), pid)
            self.app.refresh_agents()
            self.app.saved(f"Saved system prompt for '{key}'.")
            win.destroy()
        ctk.CTkButton(win, text="Save Prompt", command=save).pack(pady=(0, 12))

    # ----------------------- Editor ----------------------------------------
    def _persona_maps(self):
        plist = self.s.personas(self.app.engine.project_id)
        n2k = {p["display_name"]: p["key"] for p in plist}
        k2n = {p["key"]: p["display_name"] for p in plist}
        return plist, n2k, k2n

    def _build_editor(self, tab):
        tab.grid_rowconfigure(0, weight=1)
        tab.grid_columnconfigure(0, weight=1)
        scroll = ctk.CTkScrollableFrame(tab, fg_color=theme.BG_SIDEBAR)
        scroll.grid(row=0, column=0, sticky="nsew", pady=6)
        scroll.grid_columnconfigure(0, weight=1)

        plist, n2k, k2n = self._persona_maps()
        self._ed_n2k = n2k
        names = list(n2k.keys())

        def sect(text):
            ctk.CTkLabel(scroll, text=text, anchor="w", text_color=theme.LIME,
                         font=ctk.CTkFont(size=14, weight="bold")
                         ).pack(fill="x", padx=10, pady=(12, 2))

        def lbl(text):
            ctk.CTkLabel(scroll, text=text, anchor="w",
                         text_color=theme.TEXT_PRIMARY).pack(fill="x", padx=12,
                                                            pady=(6, 1))

        def menu(values, current):
            m = ctk.CTkOptionMenu(scroll, values=values)
            m.set(current if current in values else (values[0] if values else ""))
            m.pack(anchor="w", padx=12)
            return m

        def entry(value, width=90):
            e = ctk.CTkEntry(scroll, width=width)
            e.insert(0, str(value))
            e.pack(anchor="w", padx=12)
            return e

        # --- Write pipeline ---
        sect("Write pipeline (Ghostwriter draft \u2192 critics review)")
        lbl("Ghostwriter persona")
        self.ed_write_persona = menu(
            names, k2n.get(self.s.get("editor.write_persona", "ghostwriter"), ""))
        lbl("Write temperature")
        self.ed_write_temp = entry(self.s.get("editor.write_temperature", 0.65))
        lbl("Write max tokens")
        self.ed_write_max = entry(self.s.get("editor.write_max_tokens", 1400))
        self.ed_full_team = ctk.BooleanVar(
            value=self.s.get("editor.write_full_team", False))
        full_team_cb = ctk.CTkCheckBox(scroll, text="Optional full-team pass "
                        "(use Manager-led orchestration instead of "
                        "Ghostwriter+critics)", variable=self.ed_full_team)
        full_team_cb.pack(anchor="w", padx=12, pady=6)
        attach(full_team_cb, "Slower, higher quality: routes Write through the "
                             "Manager and the whole agent team instead of just "
                             "Ghostwriter + critics.")
        lbl("Critics (review/refine the draft)")
        current_critics = set(self.s.get("editor.write_critics", []) or [])
        self.ed_critics = {}
        crit_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        crit_frame.pack(fill="x", padx=12)
        attach(crit_frame, "Agents that review and refine each Ghostwriter draft "
                           "(e.g. continuity, prose/style). More critics = "
                           "slower but more polished.")
        for i, p in enumerate(plist):
            var = ctk.BooleanVar(value=p["key"] in current_critics)
            ctk.CTkCheckBox(crit_frame, text=p["display_name"], variable=var
                            ).grid(row=i // 2, column=i % 2, sticky="w",
                                   padx=4, pady=2)
            self.ed_critics[p["key"]] = var

        # --- Brainstorm ---
        sect("Brainstorm")
        lbl("Mode")
        self.ed_brain_mode = menu(["single", "team"],
                                  self.s.get("editor.brainstorm_mode", "single"))
        attach(self.ed_brain_mode, "single = one persona answers quickly; team = "
                                   "full orchestration for richer, cross-checked "
                                   "ideas.")
        lbl("Brainstorm persona (single mode)")
        self.ed_brain_persona = menu(
            names, k2n.get(self.s.get("editor.brainstorm_persona",
                                      "quest_architect"), ""))
        lbl("Brainstorm max tokens")
        self.ed_brain_max = entry(self.s.get("editor.brainstorm_max_tokens", 2200))

        # --- Chat ---
        sect("Project Chat")
        lbl("Chat persona")
        self.ed_chat_persona = menu(
            names, k2n.get(self.s.get("editor.chat_persona", "user_liaison"), ""))

        # --- Writing style ---
        sect("Writing style presets (used by Write)")
        lbl("Active style preset")
        self.ed_voice = menu(list(config.STYLE_PRESET_LABELS),
                             config.style_preset_display(
                                 self.s.get("editor.voice_preset", "my")))
        attach(self.ed_voice, "Which style guide Write uses: My Style, Alt Style, "
                              "or Neutral Style (no style guide).")
        lbl("My Style guide")
        self.ed_style_my = panel_text.new_textbox(scroll, self.s, height=70, wrap="word")
        self.ed_style_my.pack(fill="x", padx=12, pady=2)
        self.ed_style_my.insert("1.0", self.s.get("editor.style_guide_my", ""))
        lbl("Alt Style guide")
        self.ed_style_alt = panel_text.new_textbox(scroll, self.s, height=70, wrap="word")
        self.ed_style_alt.pack(fill="x", padx=12, pady=2)
        self.ed_style_alt.insert("1.0", self.s.get("editor.style_guide_alt", ""))

        # --- Lore auto-scan ---
        sect("Live lore auto-scan")
        self.ed_autoscan = ctk.BooleanVar(
            value=self.s.get("editor.lore_autoscan", True))
        autoscan_cb = ctk.CTkCheckBox(scroll, text="Surface relevant lore while "
                        "writing", variable=self.ed_autoscan)
        autoscan_cb.pack(anchor="w", padx=12, pady=6)
        attach(autoscan_cb, "Continuously scan recent text and show matching lore "
                            "as chips under the editor (and feed it to the AI).")
        lbl("Scan interval (ms)")
        self.ed_scan_interval = entry(
            self.s.get("editor.lore_scan_interval_ms", 3000))
        attach(self.ed_scan_interval, "How often (milliseconds) to re-scan for "
                                      "relevant lore. Higher = less CPU, slower "
                                      "to update.")

        ctk.CTkButton(tab, text="Save Editor Settings", command=self._save_editor,
                      **theme.primary_btn()).grid(row=1, column=0, sticky="e",
                                                  padx=8, pady=8)

    def _save_editor(self):
        n2k = self._ed_n2k

        def to_float(w, d):
            try:
                return float(w.get())
            except ValueError:
                return d

        def to_int(w, d):
            try:
                return int(w.get())
            except ValueError:
                return d
        self.s.set("editor.write_persona",
                   n2k.get(self.ed_write_persona.get(), "ghostwriter"), save=False)
        self.s.set("editor.write_temperature",
                   to_float(self.ed_write_temp, 0.65), save=False)
        self.s.set("editor.write_max_tokens",
                   to_int(self.ed_write_max, 1400), save=False)
        self.s.set("editor.write_full_team", bool(self.ed_full_team.get()),
                   save=False)
        critics = [k for k, var in self.ed_critics.items() if var.get()]
        self.s.set("editor.write_critics", critics, save=False)
        self.s.set("editor.brainstorm_mode", self.ed_brain_mode.get(), save=False)
        self.s.set("editor.brainstorm_persona",
                   n2k.get(self.ed_brain_persona.get(), "quest_architect"),
                   save=False)
        self.s.set("editor.brainstorm_max_tokens",
                   to_int(self.ed_brain_max, 2200), save=False)
        self.s.set("editor.chat_persona",
                   n2k.get(self.ed_chat_persona.get(), "user_liaison"), save=False)
        self.s.set("editor.voice_preset",
                   config.style_preset_from_display(self.ed_voice.get()),
                   save=False)
        self.s.set("editor.style_guide_my",
                   self.ed_style_my.get("1.0", "end").strip(), save=False)
        self.s.set("editor.style_guide_alt",
                   self.ed_style_alt.get("1.0", "end").strip(), save=False)
        self.s.set("editor.lore_autoscan", bool(self.ed_autoscan.get()),
                   save=False)
        self.s.set("editor.lore_scan_interval_ms",
                   to_int(self.ed_scan_interval, 3000))
        self.app.saved("Editor settings saved.")

    # ----------------------- Models ----------------------------------------
    def _build_models(self, tab):
        tab.grid_columnconfigure(0, weight=1)
        reg = self.s.model_registry()
        self.model_widgets = {}
        scroll = ctk.CTkScrollableFrame(tab, fg_color=theme.BG_SIDEBAR)
        scroll.pack(fill="both", expand=True, pady=6)
        scroll.grid_columnconfigure(1, weight=1)
        r = 0
        for tier, spec in reg.items():
            ctk.CTkLabel(scroll, text=f"Tier: {tier}", text_color=theme.LIME,
                         font=ctk.CTkFont(size=14, weight="bold")
                         ).grid(row=r, column=0, columnspan=2, sticky="w", padx=8, pady=(10, 2))
            r += 1
            self.model_widgets[tier] = {}
            for field, default in (("path", spec.get("path", "")),
                                   ("n_ctx", spec.get("n_ctx", 4096)),
                                   ("n_gpu_layers", spec.get("n_gpu_layers", -1))):
                ctk.CTkLabel(scroll, text=field, anchor="w").grid(row=r, column=0, sticky="w", padx=12)
                e = ctk.CTkEntry(scroll)
                e.insert(0, str(default))
                e.grid(row=r, column=1, sticky="ew", padx=12, pady=2)
                if field == "n_ctx":
                    attach(e, "Context window size (tokens). Larger holds more "
                              "story but uses more VRAM/RAM.")
                elif field == "n_gpu_layers":
                    attach(e, "Layers offloaded to the GPU. -1 = all (fastest if "
                              "it fits in VRAM); lower it if you run out of VRAM.")
                self.model_widgets[tier][field] = e
                r += 1
        ctk.CTkLabel(tab, text="Note: on 8GB VRAM, models load single-slot (one at a time).",
                     text_color=theme.TEXT_MUTED).pack(anchor="w", padx=8)
        ctk.CTkButton(tab, text="Save Models", command=self._save_models).pack(anchor="e", pady=8)

    def _save_models(self):
        models = {}
        for tier, fields in self.model_widgets.items():
            entry = {"path": fields["path"].get().strip()}
            try:
                entry["n_ctx"] = int(fields["n_ctx"].get())
            except ValueError:
                pass
            try:
                entry["n_gpu_layers"] = int(fields["n_gpu_layers"].get())
            except ValueError:
                pass
            models[tier] = entry
        self.s.set("models", models)
        self.app.saved("Model registry saved.")

    # ----------------------- Orchestration ---------------------------------
    def _build_orchestration(self, tab):
        f = ctk.CTkFrame(tab, fg_color="transparent")
        f.pack(fill="x", pady=6)
        self.orch = {}
        self.orch["max_steps"] = self._labeled_entry(f, "Max steps",
                                                     self.s.get("orchestration.max_steps", 5))
        self.orch["manager_key"] = self._labeled_entry(f, "Manager key",
                                                       self.s.get("orchestration.manager_key", "manager"))
        self.orch["liaison_key"] = self._labeled_entry(f, "Liaison key",
                                                       self.s.get("orchestration.liaison_key", "user_liaison"))
        self.orch["inject_max_chars"] = self._labeled_entry(f, "Setting inject max chars",
                                                            self.s.get("context.inject_max_chars", 6000))
        attach(self.orch["inject_max_chars"], "Character budget for the story "
                                              "bible/lore/world state injected "
                                              "into each prompt. Higher = more "
                                              "context, slower, more VRAM.")
        self.orch["memory_recent_turns"] = self._labeled_entry(f, "Memory recent turns",
                                                              self.s.get("context.memory_recent_turns", 4))
        attach(self.orch["memory_recent_turns"], "How many recent conversation "
                                                 "turns to remember and replay "
                                                 "into the next prompt.")
        self.orch_synth = ctk.BooleanVar(value=self.s.get("orchestration.synthesis", True))
        ctk.CTkCheckBox(f, text="Final synthesis pass", variable=self.orch_synth
                        ).pack(anchor="w", padx=12, pady=4)
        self.orch_hitl = ctk.BooleanVar(value=self.s.get("orchestration.hitl", False))
        hitl_cb = ctk.CTkCheckBox(f, text="Human-in-the-loop (Liaison asks/checks in)",
                                  variable=self.orch_hitl)
        hitl_cb.pack(anchor="w", padx=12, pady=4)
        attach(hitl_cb, "When on, orchestration can pause to ask you questions "
                        "mid-run via the User Liaison agent.")
        self.orch_inject = ctk.BooleanVar(value=self.s.get("context.inject", True))
        ctk.CTkCheckBox(f, text="Inject setting (story bible + lore + world state)",
                        variable=self.orch_inject).pack(anchor="w", padx=12, pady=4)
        self.orch_capture = ctk.BooleanVar(value=self.s.get("context.auto_capture", True))
        ctk.CTkCheckBox(f, text="Auto-capture [[REMEMBER]] into lore",
                        variable=self.orch_capture).pack(anchor="w", padx=12, pady=4)
        ctk.CTkButton(tab, text="Save Orchestration", command=self._save_orch).pack(anchor="e", pady=8)

    def _save_orch(self):
        def to_int(w, default):
            try:
                return int(w.get())
            except ValueError:
                return default
        self.s.set("orchestration.max_steps", to_int(self.orch["max_steps"], 5), save=False)
        self.s.set("orchestration.manager_key", self.orch["manager_key"].get().strip(), save=False)
        self.s.set("orchestration.liaison_key", self.orch["liaison_key"].get().strip(), save=False)
        self.s.set("orchestration.synthesis", bool(self.orch_synth.get()), save=False)
        self.s.set("orchestration.hitl", bool(self.orch_hitl.get()), save=False)
        self.s.set("context.inject", bool(self.orch_inject.get()), save=False)
        self.s.set("context.auto_capture", bool(self.orch_capture.get()), save=False)
        self.s.set("context.inject_max_chars", to_int(self.orch["inject_max_chars"], 6000), save=False)
        self.s.set("context.memory_recent_turns", to_int(self.orch["memory_recent_turns"], 4))
        self.app.engine.context_inject = bool(self.orch_inject.get())
        self.app.engine.context_auto_capture = bool(self.orch_capture.get())
        self.app.saved("Orchestration settings saved.")

    # ----------------------- Services --------------------------------------
    def _build_services(self, tab):
        f = ctk.CTkFrame(tab, fg_color="transparent")
        f.pack(fill="x", pady=6)
        self.svc = {}
        self.svc["comfyui_url"] = self._labeled_entry(f, "ComfyUI URL",
                                                     self.s.get("services.comfyui_url", config.COMFYUI_URL))
        self.svc["alltalk_url"] = self._labeled_entry(f, "AllTalk URL",
                                                     self.s.get("services.alltalk_url", config.ALLTALK_URL))
        ctk.CTkLabel(f, text="TTS engine", anchor="w").pack(fill="x", padx=12, pady=(8, 2))
        self.tts_engine = ctk.CTkOptionMenu(f, values=["alltalk", "piper", "off", "auto"])
        self.tts_engine.set(self.s.get("services.tts_engine", config.TTS_ENGINE))
        self.tts_engine.pack(anchor="w", padx=12)
        self.svc["tts_voice"] = self._labeled_entry(f, "TTS voice",
                                                    self.s.get("services.tts_voice", config.TTS_VOICE))
        self.svc["piper_exe"] = self._labeled_entry(f, "Piper exe path",
                                                   self.s.get("services.piper_exe", config.PIPER_EXE))
        self.svc["piper_voice"] = self._labeled_entry(f, "Piper voice (.onnx)",
                                                     self.s.get("services.piper_voice", config.PIPER_VOICE))
        self.svc["styles_csv"] = self._labeled_entry(f, "styles.csv path (optional)",
                                                    self.s.get("services.styles_csv", ""))
        self.svc["heartbeat_interval_s"] = self._labeled_entry(
            f, "Heartbeat interval (seconds)",
            self.s.get("services.heartbeat_interval_s",
                       config.HEARTBEAT_INTERVAL_S))
        attach(self.svc["heartbeat_interval_s"],
               "How often the status bar re-checks service health, in seconds "
               "(minimum 5). Lower = more responsive dots, slightly more network "
               "chatter.")

        health = ctk.CTkFrame(tab, fg_color="transparent")
        health.pack(fill="x", pady=6)
        self.health_lbl = ctk.CTkLabel(health, text="Health: (not tested)",
                                       text_color=theme.TEXT_MUTED)
        self.health_lbl.pack(side="left", padx=8)
        ctk.CTkButton(health, text="Test Services", command=self._test_services
                      ).pack(side="left", padx=8)
        ctk.CTkButton(tab, text="Save Services", command=self._save_services).pack(anchor="e", pady=8)

    def _save_services(self):
        for key, w in self.svc.items():
            val = w.get().strip()
            if key == "heartbeat_interval_s":
                try:
                    val = max(5, int(val))
                except ValueError:
                    val = config.HEARTBEAT_INTERVAL_S
            self.s.set(f"services.{key}", val, save=False)
        self.s.set("services.tts_engine", self.tts_engine.get())
        if hasattr(self.app, "restart_heartbeat"):
            self.app.restart_heartbeat()
        self.app.saved("Service settings saved.")

    def _test_services(self):
        self.health_lbl.configure(text="Health: testing...")
        self._save_services()
        threading.Thread(target=self._test_worker, daemon=True).start()

    def _test_worker(self):
        res = services.check_all(self.s)

        def dot(ok):
            return "OK" if ok else "DOWN"
        text = (f"ComfyUI: {dot(res['comfyui']['ok'])} | "
                f"AllTalk: {dot(res['alltalk']['ok'])} | "
                f"Piper: {dot(res['piper']['ok'])}")
        self.after(0, lambda: self.health_lbl.configure(
            text="Health:  " + text,
            text_color=(theme.GREEN if all(r["ok"] for r in res.values()) else theme.ORANGE)))
        self.after(0, self.app.refresh_header)

    # ----------------------- Image -----------------------------------------
    def _build_image(self, tab):
        f = ctk.CTkFrame(tab, fg_color="transparent")
        f.pack(fill="x", pady=6)
        self.img = {}
        self.img["workflow"] = self._labeled_entry(f, "Workflow file (in workflows/)",
                                                   self.s.get("image.workflow", config.IMAGE_WORKFLOW))
        self.img["width"] = self._labeled_entry(f, "Default width",
                                               self.s.get("image.width", 1024))
        self.img["height"] = self._labeled_entry(f, "Default height",
                                                self.s.get("image.height", 1024))
        self.img["style_prefix"] = self._labeled_entry(f, "Style prefix",
                                                      self.s.get("image.style_prefix", ""))
        ctk.CTkLabel(f, text="Seed behavior", anchor="w").pack(fill="x", padx=12, pady=(8, 2))
        self.seed_behavior = ctk.CTkOptionMenu(f, values=["randomize", "fixed"])
        self.seed_behavior.set(self.s.get("image.seed_behavior", "randomize"))
        self.seed_behavior.pack(anchor="w", padx=12)
        attach(self.seed_behavior, "randomize = a new image every run; fixed = "
                                   "reuse the same seed for reproducible results.")
        ctk.CTkButton(tab, text="Save Image Defaults", command=self._save_image).pack(anchor="e", pady=8)

    def _save_image(self):
        self.s.set("image.workflow", self.img["workflow"].get().strip(), save=False)
        for k in ("width", "height"):
            try:
                self.s.set(f"image.{k}", int(self.img[k].get()), save=False)
            except ValueError:
                pass
        self.s.set("image.style_prefix", self.img["style_prefix"].get().strip(), save=False)
        self.s.set("image.seed_behavior", self.seed_behavior.get())
        self.app.saved("Image defaults saved.")

    # ----------------------- Appearance ------------------------------------
    def _build_appearance(self, tab):
        f = ctk.CTkFrame(tab, fg_color="transparent")
        f.pack(fill="x", pady=6)
        ctk.CTkLabel(f, text="Appearance mode", anchor="w").pack(fill="x", padx=12, pady=(8, 2))
        self.mode = ctk.CTkOptionMenu(f, values=["dark", "light", "system"])
        self.mode.set(self.s.get("appearance_mode", "dark"))
        self.mode.pack(anchor="w", padx=12)
        ctk.CTkLabel(f, text="Color theme", anchor="w").pack(fill="x", padx=12, pady=(8, 2))
        self.theme_opt = ctk.CTkOptionMenu(f, values=["radix", "blue", "green", "dark-blue"])
        self.theme_opt.set(self.s.get("color_theme", "radix"))
        self.theme_opt.pack(anchor="w", padx=12)
        ctk.CTkLabel(f, text="(Theme change applies on next launch.)",
                     text_color=theme.TEXT_MUTED).pack(anchor="w", padx=12, pady=4)

        ctk.CTkLabel(f, text="Panel text size", anchor="w").pack(
            fill="x", padx=12, pady=(12, 2))
        self.panel_font_size = ctk.CTkOptionMenu(
            f, values=[str(n) for n in range(10, 21)],
            command=lambda _v: None)
        self.panel_font_size.set(str(self.s.get("ui.panel_font_size", 13)))
        self.panel_font_size.pack(anchor="w", padx=12)
        attach(self.panel_font_size,
               "Font size for Agents, Story Bible fields, AI dock, Help, and "
               "other panel text boxes (not the main manuscript editor).")

        self.panel_auto_scroll = ctk.BooleanVar(
            value=self.s.get("ui.panel_auto_scroll", True))
        auto_cb = ctk.CTkCheckBox(
            f, text="Auto-scroll panel text boxes",
            variable=self.panel_auto_scroll)
        auto_cb.pack(anchor="w", padx=12, pady=(10, 4))
        attach(auto_cb,
               "Keep Agents chat and the editor AI/Chat dock scrolled to the "
               "latest text while content streams in.")

        ctk.CTkButton(tab, text="Save Appearance", command=self._save_appearance).pack(anchor="e", pady=8)

    def _save_appearance(self):
        self.s.set("appearance_mode", self.mode.get(), save=False)
        self.s.set("color_theme", self.theme_opt.get(), save=False)
        try:
            self.s.set("ui.panel_font_size", int(self.panel_font_size.get()), save=False)
        except ValueError:
            pass
        self.s.set("ui.panel_auto_scroll", bool(self.panel_auto_scroll.get()))
        ctk.set_appearance_mode(self.mode.get())
        self.app.refresh_panel_fonts()
        from gui.panels.agents_panel import AgentsPanel
        for panel in self.app._open_panels():
            if isinstance(panel, AgentsPanel):
                panel.auto_scroll.set(self.s.get("ui.panel_auto_scroll", True))
        self.app.saved("Appearance saved (theme applies next launch).")

    # ----------------------- helper ----------------------------------------
    def _labeled_entry(self, parent, label, value):
        ctk.CTkLabel(parent, text=label, anchor="w").pack(fill="x", padx=12, pady=(8, 2))
        e = ctk.CTkEntry(parent)
        e.insert(0, str(value))
        e.pack(fill="x", padx=12)
        return e
