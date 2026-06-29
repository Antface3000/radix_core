"""Service Setup - the guided verification + asset-sync hub.

Point Radix Core at the user's existing ComfyUI / AllTalk / Piper installs,
verify they respond (live dots, also driven by the background heartbeat),
launch AllTalk / ComfyUI from their folders, and push bundled voices (and,
optionally, nodes/workflows) into them with Sync Assets.
"""

import threading
from tkinter import filedialog

import customtkinter as ctk

import config
from gui import theme
from gui.panels.base import BasePanel
from gui.tooltip import attach
from src import asset_sync, service_launch, services


class SetupPanel(BasePanel):
    title = "Service Setup"

    def __init__(self, master, app):
        super().__init__(master, app)
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)
        self.header("Service Setup",
                    "Connect Radix Core to your local engines, verify them, and "
                    "sync the assets they need. Everything stays on your machine.")

        self.fields = {}
        self.dots = {}

        scroll = ctk.CTkScrollableFrame(self, fg_color=theme.BG_CARD)
        scroll.grid(row=1, column=0, sticky="nsew", padx=16, pady=(4, 16))
        scroll.grid_columnconfigure(0, weight=1)
        self._build_services(scroll)
        self._build_sync(scroll)

        # Reflect whatever the last heartbeat already found.
        if getattr(self.app, "last_health", None):
            self.on_health(self.app.last_health)

    # ----------------------- services ---------------------------------------
    def _build_services(self, parent):
        ctk.CTkLabel(parent, text="1. Connect your services",
                     font=ctk.CTkFont(size=15, weight="bold"),
                     text_color=theme.LIME).grid(row=0, column=0, sticky="w",
                                                 padx=12, pady=(10, 2))

        box = ctk.CTkFrame(parent, fg_color=theme.BG_SIDEBAR)
        box.grid(row=1, column=0, sticky="ew", padx=12, pady=4)
        box.grid_columnconfigure(1, weight=1)
        r = 0

        r = self._service_header(box, r, "comfyui", "ComfyUI (image generation)")
        r = self._row(box, r, "comfyui_url", "Server URL",
                      self.app.settings.get("services.comfyui_url",
                                            config.COMFYUI_URL))
        r = self._row(box, r, "comfyui_dir", "Install folder", self.app.settings.get(
            "services.comfyui_dir", config.COMFYUI_DIR), browse="dir",
            tip="The ComfyUI folder that contains main.py. Used by Sync Assets to "
                "place custom nodes and workflows.")

        r = self._service_header(box, r, "alltalk", "AllTalk (voice)")
        r = self._row(box, r, "alltalk_url", "Server URL", self.app.settings.get(
            "services.alltalk_url", config.ALLTALK_URL))
        r = self._row(box, r, "alltalk_dir", "Install folder", self.app.settings.get(
            "services.alltalk_dir", config.ALLTALK_DIR), browse="dir",
            tip="The AllTalk folder. Used by Sync Assets to install bundled "
                "voices into its voices/ directory.")

        r = self._service_header(box, r, "piper", "Piper (offline voice)")
        r = self._row(box, r, "piper_exe", "piper.exe", self.app.settings.get(
            "services.piper_exe", config.PIPER_EXE), browse="file")
        r = self._row(box, r, "piper_voice", "Voice (.onnx)", self.app.settings.get(
            "services.piper_voice", config.PIPER_VOICE), browse="file")

        actions = ctk.CTkFrame(parent, fg_color="transparent")
        actions.grid(row=2, column=0, sticky="ew", padx=12, pady=(6, 2))
        ctk.CTkButton(actions, text="Save", width=90, command=self._save,
                      **theme.primary_btn()).pack(side="left", padx=(0, 8))
        test_btn = ctk.CTkButton(actions, text="Test now", width=90,
                                 command=self._test, **theme.secondary_btn())
        test_btn.pack(side="left", padx=(0, 8))
        attach(test_btn, "Save the paths and probe all services right now. The "
                         "dots also refresh automatically on the heartbeat.")
        launch_at = ctk.CTkButton(actions, text="Launch AllTalk", width=110,
                                  command=self._launch_alltalk,
                                  **theme.secondary_btn())
        launch_at.pack(side="left", padx=(0, 8))
        attach(launch_at, "Start the AllTalk voice server from its install folder "
                          "(set above). It opens in its own console window.")
        launch_comfy = ctk.CTkButton(actions, text="Launch ComfyUI", width=110,
                                     command=self._launch_comfyui,
                                     **theme.secondary_btn())
        launch_comfy.pack(side="left")
        attach(launch_comfy, "Start ComfyUI from its install folder (set above). "
                             "It opens in its own console window.")
        self.summary = ctk.CTkLabel(actions, text="", text_color=theme.TEXT_MUTED)
        self.summary.pack(side="left", padx=12)

    def _service_header(self, box, r, key, label):
        row = ctk.CTkFrame(box, fg_color="transparent")
        row.grid(row=r, column=0, columnspan=3, sticky="ew", padx=8, pady=(10, 0))
        dot = ctk.CTkLabel(row, text="\u25CF", text_color=theme.TEXT_MUTED,
                           font=ctk.CTkFont(size=14))
        dot.pack(side="left")
        self.dots[key] = dot
        ctk.CTkLabel(row, text=label, font=ctk.CTkFont(size=13, weight="bold"),
                     text_color=theme.TEXT_PRIMARY).pack(side="left", padx=6)
        return r + 1

    def _row(self, box, r, key, label, value, browse=None, tip=None):
        ctk.CTkLabel(box, text=label, anchor="w", text_color=theme.TEXT_MUTED
                     ).grid(row=r, column=0, sticky="w", padx=(28, 6), pady=3)
        entry = ctk.CTkEntry(box)
        entry.insert(0, str(value or ""))
        entry.grid(row=r, column=1, sticky="ew", padx=6, pady=3)
        if tip:
            attach(entry, tip)
        self.fields[key] = entry
        if browse:
            ctk.CTkButton(box, text="Browse", width=72,
                          command=lambda k=key, b=browse: self._browse(k, b),
                          **theme.secondary_btn()).grid(row=r, column=2,
                                                        padx=(0, 8), pady=3)
        return r + 1

    def _browse(self, key, kind):
        if kind == "dir":
            path = filedialog.askdirectory(title="Select folder")
        else:
            path = filedialog.askopenfilename(title="Select file")
        if path:
            self.fields[key].delete(0, "end")
            self.fields[key].insert(0, path)

    def _save(self):
        for key, entry in self.fields.items():
            self.app.settings.set(f"services.{key}", entry.get().strip(),
                                  save=False)
        # Visiting + saving Setup counts as "done" - stop the first-run nudge.
        self.app.settings.set("ui.setup_done", True, save=False)
        self.app.settings.save()
        if hasattr(self.app, "restart_heartbeat"):
            self.app.restart_heartbeat()
        self.app.status("Service paths saved.")

    def _test(self):
        self._save()
        self.summary.configure(text="testing...")
        threading.Thread(target=self._test_worker, daemon=True).start()

    def _test_worker(self):
        res = services.check_all(self.app.settings)
        self.after(0, lambda: self.on_health(res))
        # Also nudge the shared heartbeat readout.
        if hasattr(self.app, "_apply_health"):
            self.after(0, lambda: self.app._apply_health(res))

    def _launch_alltalk(self):
        self._save()
        self.summary.configure(text="launching AllTalk...")
        threading.Thread(target=self._launch_worker, args=("alltalk",),
                         daemon=True).start()

    def _launch_comfyui(self):
        self._save()
        self.summary.configure(text="launching ComfyUI...")
        threading.Thread(target=self._launch_worker, args=("comfyui",),
                         daemon=True).start()

    def _launch_worker(self, which):
        if which == "alltalk":
            res = service_launch.launch_alltalk(self.app.settings)
        else:
            res = service_launch.launch_comfyui(self.app.settings)
        self.after(0, lambda: self.summary.configure(text=res["detail"]))
        self.after(0, lambda: self.app.status(
            f"{which}: {res['detail']}"))
        self.after(0, lambda: self._test())

    def on_health(self, res):
        """Called by the heartbeat (and Test) to recolor the status dots."""
        ok_count = 0
        for key, dot in self.dots.items():
            r = (res or {}).get(key, {})
            ok = bool(r.get("ok"))
            ok_count += 1 if ok else 0
            try:
                dot.configure(text_color=theme.GREEN if ok else theme.RED)
            except Exception:
                pass
        try:
            self.summary.configure(
                text=f"{ok_count}/{len(self.dots)} services connected")
        except Exception:
            pass

    # ----------------------- sync assets ------------------------------------
    def _build_sync(self, parent):
        ctk.CTkLabel(parent, text="2. Sync assets into your installs",
                     font=ctk.CTkFont(size=15, weight="bold"),
                     text_color=theme.LIME).grid(row=3, column=0, sticky="w",
                                                 padx=12, pady=(16, 2))
        desc = ctk.CTkLabel(parent, text="Copies assets bundled WITH Radix "
                            "(from radix_core/assets and workflows) into the "
                            "folders above. Copy-only and non-destructive. The "
                            "default workflow is already wired and sent over the "
                            "API, and custom nodes are best installed via ComfyUI "
                            "Manager - so the main use here is pushing voices into "
                            "AllTalk.", text_color=theme.TEXT_MUTED,
                            wraplength=320, justify="left")
        desc.grid(row=4, column=0, sticky="ew", padx=12)
        parent.bind("<Configure>", lambda e, lbl=desc: lbl.configure(
            wraplength=max(220, e.width - 36)))

        bar = ctk.CTkFrame(parent, fg_color="transparent")
        bar.grid(row=5, column=0, sticky="ew", padx=12, pady=6)
        preview_btn = ctk.CTkButton(bar, text="Preview", width=90,
                                    command=self._preview, **theme.secondary_btn())
        preview_btn.pack(side="left", padx=(0, 8))
        attach(preview_btn, "Dry run: show exactly what would be copied or "
                            "overwritten, with no changes made.")
        sync_btn = ctk.CTkButton(bar, text="Sync Assets", width=110,
                                 command=self._run_sync, **theme.primary_btn())
        sync_btn.pack(side="left", padx=(0, 8))
        attach(sync_btn, "Copy the bundled assets into your ComfyUI / AllTalk "
                         "folders.")
        self.overwrite_var = ctk.BooleanVar(value=True)
        ow = ctk.CTkCheckBox(bar, text="Overwrite existing",
                             variable=self.overwrite_var, width=20)
        ow.pack(side="left")
        attach(ow, "If on, files that already exist are replaced; if off, they "
                   "are left untouched.")

        self.sync_log = ctk.CTkTextbox(parent, height=200, wrap="word",
                                       font=("Consolas", 11),
                                       fg_color=theme.BG_INPUT)
        self.sync_log.grid(row=6, column=0, sticky="ew", padx=12, pady=(4, 12))
        self.sync_log.insert("1.0", "Click Preview to see the sync plan.")
        self.sync_log.configure(state="disabled")

    def _log(self, text):
        self.sync_log.configure(state="normal")
        self.sync_log.delete("1.0", "end")
        self.sync_log.insert("1.0", text)
        self.sync_log.configure(state="disabled")

    def _preview(self):
        self._save()
        plan = asset_sync.plan_sync(self.app.settings)
        self._log(self._format_plan(plan))

    def _format_plan(self, plan):
        lines = []
        group = None
        for it in plan:
            if it["group"] != group:
                group = it["group"]
                lines.append(f"\n[{group}]")
            mark = {"copy": "+ copy", "overwrite": "~ overwrite",
                    "blocked": "x blocked"}.get(it["action"], it["action"])
            extra = f"  ({it.get('reason')})" if it["action"] == "blocked" else ""
            lines.append(f"  {mark}: {it['name']}{extra}")
        return "\n".join(lines).strip() or "Nothing to sync."

    def _run_sync(self):
        self._save()
        self._log("Syncing...")
        threading.Thread(target=self._sync_worker, daemon=True).start()

    def _sync_worker(self):
        results, summary = asset_sync.run_sync(
            self.app.settings, overwrite=self.overwrite_var.get())
        lines = [f"Copied {summary['copied']}, overwritten "
                 f"{summary['overwritten']}, skipped {summary['skipped']}, "
                 f"blocked {summary['blocked']}, failed {summary['failed']}.", ""]
        group = None
        for it in results:
            if it["group"] != group:
                group = it["group"]
                lines.append(f"[{group}]")
            flag = "OK " if it.get("ok") else "ERR"
            lines.append(f"  {flag} {it['name']} - {it.get('detail', '')}")
        text = "\n".join(lines)
        self.after(0, lambda: self._log(text))
        self.after(0, lambda: self.app.status("Asset sync complete."))

    def on_show(self):
        if getattr(self.app, "last_health", None):
            self.on_health(self.app.last_health)
