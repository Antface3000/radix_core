"""Agents panel - the streaming chat bench (single agent or orchestrated team)."""

import queue
import threading

import customtkinter as ctk

from gui import theme
from gui import panel_text
from gui.panels.base import BasePanel
from gui.tooltip import attach
from src import personas, worldcontext

_TIER_TAG = {
    personas.TIER_ARCHITECT: "T1",
    personas.TIER_OPERATOR: "T2",
    personas.TIER_FLAVOR: "T3",
}


class AgentsPanel(BasePanel):
    title = "Agents"

    def __init__(self, master, app):
        super().__init__(master, app)
        self.result_queue = queue.Queue()
        self._busy = False
        self._current = ""
        self.last_response = ""
        self.last_persona = ""

        self.grid_rowconfigure(4, weight=1)
        self.header("Agents", "Chat with one agent or let the Manager orchestrate the team.")
        self._build_controls()
        self._build_chat()
        self._refresh_personas()
        self.after(80, self._poll)

    # ----------------------- layout ----------------------------------------
    def _build_controls(self):
        bar = ctk.CTkFrame(self)
        bar.grid(row=1, column=0, sticky="ew", padx=16, pady=6)
        bar.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(bar, text="Persona:").grid(row=0, column=0, padx=(12, 6), pady=10)
        self.persona_menu = ctk.CTkOptionMenu(bar, values=["(none)"], width=140,
                                              command=self._on_persona)
        self.persona_menu.grid(row=0, column=1, sticky="ew", padx=6, pady=10)

        self.show_think = ctk.BooleanVar(value=False)
        think_cb = ctk.CTkCheckBox(bar, text="Show <think>", variable=self.show_think)
        think_cb.grid(row=0, column=2, padx=8, pady=10)
        attach(think_cb, "Show the model's hidden reasoning (<think>...). Useful "
                         "for debugging; off keeps replies clean.")
        self.orchestrate = ctk.BooleanVar(value=False)
        orch_cb = ctk.CTkCheckBox(bar, text="Orchestrate", variable=self.orchestrate)
        orch_cb.grid(row=0, column=3, padx=8, pady=10)
        attach(orch_cb, "Let the Manager plan and route your request across the "
                        "whole agent team instead of just the selected agent.")
        self.inject = ctk.BooleanVar(value=self.app.engine.context_inject)
        inject_cb = ctk.CTkCheckBox(bar, text="Inject setting", variable=self.inject,
                                    command=self._toggle_inject)
        inject_cb.grid(row=0, column=4, padx=8, pady=10)
        attach(inject_cb, "Add the story bible, lore, and world state to each "
                          "prompt so agents stay consistent with your world.")
        self.auto_scroll = ctk.BooleanVar(
            value=self.app.settings.get("ui.panel_auto_scroll", True))
        auto_cb = ctk.CTkCheckBox(bar, text="Auto-scroll", variable=self.auto_scroll,
                                  command=self._toggle_auto_scroll)
        auto_cb.grid(row=0, column=5, padx=8, pady=10)
        attach(auto_cb, "Keep the chat scrolled to the latest message while "
                         "agents respond.")

        self.info = ctk.CTkLabel(self, text="", anchor="w", justify="left",
                                 text_color=theme.TEXT_MUTED,
                                 font=ctk.CTkFont(size=12))
        self.info.grid(row=2, column=0, sticky="ew", padx=22, pady=(0, 2))
        setting_row = ctk.CTkFrame(self, fg_color="transparent")
        setting_row.grid(row=3, column=0, sticky="ew", padx=22, pady=(0, 4))
        setting_row.grid_columnconfigure(0, weight=1)
        self.setting_lbl = ctk.CTkLabel(
            setting_row, text="", anchor="w", justify="left",
            text_color=theme.TEXT_MUTED, font=ctk.CTkFont(size=11))
        self.setting_lbl.grid(row=0, column=0, sticky="ew")
        self.preview_btn = ctk.CTkButton(
            setting_row, text="Preview", width=72, command=self._preview_setting,
            **theme.secondary_btn())
        self.preview_btn.grid(row=0, column=1, padx=(8, 0))
        attach(self.preview_btn, "Show the SETTING block injected into agent prompts.")
        self.bind("<Configure>", lambda e: self.info.configure(
            wraplength=max(200, e.width - 48)))
        self._refresh_setting_status()

    def _build_chat(self):
        self.chat = panel_text.new_textbox(self, self.app.settings, wrap="word")
        self.chat.grid(row=4, column=0, sticky="nsew", padx=16, pady=6)
        self.chat.configure(state="disabled")

        bottom = ctk.CTkFrame(self, fg_color="transparent")
        bottom.grid(row=5, column=0, sticky="ew", padx=16, pady=(0, 6))
        bottom.grid_columnconfigure(0, weight=1)
        self.entry = ctk.CTkEntry(bottom, placeholder_text="Message the agent(s)...")
        self.entry.grid(row=0, column=0, sticky="ew", padx=(0, 6), pady=6)
        self.entry.bind("<Return>", lambda _e: self.run())
        self.send_btn = ctk.CTkButton(bottom, text="Execute", width=110, command=self.run)
        self.send_btn.grid(row=0, column=1, padx=4, pady=6)
        ctk.CTkButton(bottom, text="Speak", width=80, command=self._speak_last,
                      **theme.accent_btn(theme.BLUE, "#1f5aa8")
                      ).grid(row=0, column=2, padx=4, pady=6)
        ctk.CTkButton(bottom, text="Clear", width=80, command=self._clear,
                      **theme.secondary_btn()
                      ).grid(row=0, column=3, padx=(4, 0), pady=6)

        self.status = ctk.CTkLabel(self, text="Ready.", anchor="w",
                                   text_color=theme.TEXT_MUTED)
        self.status.grid(row=6, column=0, sticky="ew", padx=22, pady=(0, 8))

    # ----------------------- persona data ----------------------------------
    def _refresh_personas(self):
        self.values, self.by_value = [], {}
        for tier, plist in self.app.engine.get_personas_grouped().items():
            tag = _TIER_TAG.get(tier, "")
            for p in plist:
                v = f"[{tag}] {p['display_name']}"
                self.values.append(v)
                self.by_value[v] = p
        if not self.values:
            self.values = ["(no agents enabled)"]
        self.persona_menu.configure(values=self.values)
        self.persona_menu.set(self.values[0])
        self._on_persona(self.values[0])

    def on_project_change(self):
        self._refresh_personas()
        self.inject.set(self.app.engine.context_inject)
        self._refresh_setting_status()

    def on_show(self):
        self._refresh_setting_status()
        self.auto_scroll.set(self.app.settings.get("ui.panel_auto_scroll", True))
        try:
            self._scroll_chat()
        except Exception:
            pass

    def _scroll_chat(self):
        if self.auto_scroll.get():
            self.chat.see("end")

    def _refresh_setting_status(self):
        if not self.inject.get():
            self.setting_lbl.configure(text="Setting injection OFF")
            return
        paths = self.app.engine.paths
        if not paths:
            self.setting_lbl.configure(text="Setting: no active project")
            return
        info = worldcontext.summarize_injection(paths)
        if info["empty"]:
            self.setting_lbl.configure(
                text="Setting: empty — fill Story Bible and save (or pin lore entries)")
            return
        labels = ", ".join(info["labels"][:4])
        if len(info["labels"]) > 4:
            labels += ", ..."
        lore_part = f", {info['pinned_lore']} pinned lore" if info["pinned_lore"] else ""
        self.setting_lbl.configure(
            text=f"Setting: {info['chars']:,} chars ({labels}{lore_part})")

    def _preview_setting(self):
        paths = self.app.engine.paths
        if not paths:
            return
        text = worldcontext.assemble(
            paths,
            max_chars=self.app.settings.get("context.inject_max_chars", 6000))
        win = ctk.CTkToplevel(self)
        win.title("Injected setting preview")
        win.geometry("640x480")
        win.configure(fg_color=theme.BG_APP)
        box = panel_text.new_textbox(win, self.app.settings, wrap="word")
        box.pack(fill="both", expand=True, padx=12, pady=12)
        box.insert("1.0", text)
        box.configure(state="disabled")

    def _current_persona(self):
        return self.by_value.get(self.persona_menu.get())

    def _on_persona(self, _v):
        p = self._current_persona()
        if not p:
            self.info.configure(text="")
            return
        self.info.configure(
            text=f"{p['tier']}  -  model '{p['model_key']}'  -  temp "
                 f"{p.get('temperature', '-')}  -  captures: {p.get('capture_kind') or 'none'}")

    def _toggle_auto_scroll(self):
        self.app.settings.set("ui.panel_auto_scroll", self.auto_scroll.get())

    def _toggle_inject(self):
        self.app.engine.context_inject = self.inject.get()
        self.app.settings.set("context.inject", self.inject.get())
        self._refresh_setting_status()
        self.status.configure(text=f"Setting injection {'ON' if self.inject.get() else 'OFF'}.")

    # ----------------------- run -------------------------------------------
    def run(self):
        if self._busy:
            return
        msg = self.entry.get().strip()
        if not msg:
            return
        self.entry.delete(0, "end")
        self._block("You", msg)
        self._current = ""
        show = self.show_think.get()
        if self.orchestrate.get():
            self._set_busy(True, "Manager is planning the pipeline...")
            threading.Thread(target=self._worker_orchestrate, args=(msg, show),
                             daemon=True).start()
        else:
            p = self._current_persona()
            if not p:
                self._set_busy(False, "No agent selected.")
                return
            self._set_busy(True, f"{p['display_name']} is thinking...")
            threading.Thread(target=self._worker, args=(p["key"], p["display_name"], msg, show),
                             daemon=True).start()

    def _worker(self, key, name, msg, show):
        try:
            self.result_queue.put(("block", name, None))
            for delta in self.app.engine.stream_task(key, msg, show_think=show):
                self.result_queue.put(("delta", name, delta))
            self.result_queue.put(("done", None, None))
        except Exception as exc:
            self.result_queue.put(("error", name, f"{type(exc).__name__}: {exc}"))

    def _worker_orchestrate(self, task, show):
        try:
            for ev in self.app.engine.orchestrate(task, show_think=show, ask_user=self._ask_user):
                kind = ev[0]
                if kind == "plan":
                    lines = [f"  {i+1}. {s['persona']['display_name']} -> {s['instruction']}"
                             for i, s in enumerate(ev[1])]
                    self.result_queue.put(("block", "Manager (plan)",
                                           "\n".join(lines) or "(empty plan)"))
                elif kind == "step":
                    self.result_queue.put(("block", ev[1]["display_name"],
                                           f"(assignment: {ev[2]})"))
                elif kind == "synthesis":
                    self.result_queue.put(("block", "Manager (synthesis)", None))
                elif kind == "await_user":
                    self.result_queue.put(("status", ev[1], None))
                elif kind == "user":
                    self.result_queue.put(("block", "You", ev[1]))
                elif kind == "delta":
                    self.result_queue.put(("delta", ev[1]["display_name"], ev[2]))
                elif kind == "done":
                    self.result_queue.put(("done", None, None))
        except Exception as exc:
            self.result_queue.put(("error", "orchestrator", f"{type(exc).__name__}: {exc}"))

    def _ask_user(self, prompt):
        holder, ev = {}, threading.Event()

        def do():
            dlg = ctk.CTkInputDialog(text=prompt, title="The team needs your input")
            holder["v"] = dlg.get_input()
            ev.set()
        self.after(0, do)
        ev.wait()
        return holder.get("v") or ""

    def _poll(self):
        try:
            while True:
                kind, a, b = self.result_queue.get_nowait()
                if kind == "block":
                    self._start(a)
                    if b:
                        self._text(b + "\n")
                    self._current = ""
                elif kind == "delta":
                    self._current += b
                    self._text(b)
                    self.last_response = self._current.strip()
                    self.last_persona = a
                    self.status.configure(text=f"Streaming...  {len(self._current.split())} words")
                elif kind == "status":
                    self.status.configure(text=a)
                elif kind == "done":
                    self._set_busy(False, f"Done.  {len(self.last_response.split())} words.")
                elif kind == "error":
                    self._start(a)
                    self._text(f"[ERROR] {b}")
                    self._set_busy(False, "Error.")
        except queue.Empty:
            pass
        self.after(60, self._poll)

    def _speak_last(self):
        if not self.last_response:
            self.status.configure(text="Nothing to speak yet.")
            return
        threading.Thread(target=lambda: self.app.tts.speak(self.last_response),
                         daemon=True).start()
        self.status.configure(text="Speaking...")

    # ----------------------- textbox helpers -------------------------------
    def _block(self, who, text):
        self._start(who)
        self._text(text)

    def _start(self, who):
        self.chat.configure(state="normal")
        if self.chat.index("end-1c") != "1.0":
            self.chat.insert("end", "\n\n")
        self.chat.insert("end", f"[{who}]\n")
        self._scroll_chat()
        self.chat.configure(state="disabled")

    def _text(self, text):
        self.chat.configure(state="normal")
        self.chat.insert("end", text)
        self._scroll_chat()
        self.chat.configure(state="disabled")

    def _clear(self):
        self.chat.configure(state="normal")
        self.chat.delete("1.0", "end")
        self.chat.configure(state="disabled")

    def _set_busy(self, busy, status):
        self._busy = busy
        self.send_btn.configure(state="disabled" if busy else "normal",
                                text="Working..." if busy else "Execute")
        self.status.configure(text=status)
