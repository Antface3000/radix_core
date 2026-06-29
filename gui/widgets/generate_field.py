"""Per-field Generate UI for Story Bible panels (T1/T2/T3/Orchestrated)."""

import queue
import threading

import customtkinter as ctk

from gui import theme
from gui.tooltip import attach
from src import story_bible_gen

_MODES = story_bible_gen.MODE_LABELS


class GenerateRegistry:
    """Accordion: only one prompt row open per panel."""

    def __init__(self):
        self._open = None

    def open(self, block):
        if self._open and self._open is not block:
            self._open.collapse()
        self._open = block

    def close(self, block):
        if self._open is block:
            self._open = None


class FieldGenerateBlock(ctk.CTkFrame):
    """Label + target widget + collapsible Generate prompt row."""

    def __init__(self, master, app, field_label, multiline=True, height=70,
                 context_fn=None, registry=None):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.field_label = field_label
        self.context_fn = context_fn or (lambda: "")
        self.registry = registry
        self._busy = False
        self._expanded = False
        self._queue = queue.Queue()
        self._append_mode = False

        self.grid_columnconfigure(0, weight=1)

        if multiline:
            self.widget = ctk.CTkTextbox(self, height=height, wrap="word")
        else:
            self.widget = ctk.CTkEntry(self)

        head = ctk.CTkFrame(self, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew")
        head.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(head, text=field_label, anchor="w",
                     text_color=theme.TEXT_PRIMARY).grid(row=0, column=0, sticky="w")
        self.gen_btn = ctk.CTkButton(head, text="Generate", width=88,
                                     command=self._toggle_prompt,
                                     **theme.secondary_btn())
        self.gen_btn.grid(row=0, column=1, sticky="e", padx=(8, 0))
        attach(self.gen_btn, "Generate AI text for this field (T1/T2/T3 or "
                            "Orchestrated).")

        self.widget.grid(row=1, column=0, sticky="ew", pady=(2, 0))

        self.prompt_frame = ctk.CTkFrame(self, fg_color=theme.BG_ELEVATED,
                                         corner_radius=8)
        self.prompt_frame.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(self.prompt_frame, text="Prompt", anchor="w",
                     text_color=theme.TEXT_MUTED).grid(row=0, column=0,
                                                       sticky="w", padx=10, pady=(8, 2))
        self.prompt_entry = ctk.CTkEntry(
            self.prompt_frame,
            placeholder_text="What should this field contain?")
        self.prompt_entry.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 6))
        self.prompt_entry.bind("<Return>", lambda _e: self._run())

        mode_row = ctk.CTkFrame(self.prompt_frame, fg_color="transparent")
        mode_row.grid(row=2, column=0, sticky="ew", padx=10, pady=(0, 8))
        ctk.CTkLabel(mode_row, text="Mode", text_color=theme.TEXT_MUTED).pack(
            side="left", padx=(0, 8))
        self.mode_menu = ctk.CTkOptionMenu(mode_row, values=list(_MODES), width=160)
        self.mode_menu.set(_MODES[0])
        self.mode_menu.pack(side="left", padx=(0, 8))
        self.run_btn = ctk.CTkButton(mode_row, text="Run", width=70,
                                     command=self._run, **theme.primary_btn())
        self.run_btn.pack(side="left", padx=4)
        self.cancel_btn = ctk.CTkButton(mode_row, text="Cancel", width=70,
                                        command=self.collapse,
                                        **theme.secondary_btn())
        self.cancel_btn.pack(side="left", padx=4)

        self.after(80, self._poll)

    def _toggle_prompt(self):
        if self._expanded:
            self.collapse()
        else:
            self.expand()

    def expand(self):
        if self.registry:
            self.registry.open(self)
        self._expanded = True
        self.prompt_frame.grid(row=2, column=0, sticky="ew", pady=(6, 0))
        self.prompt_entry.focus_set()

    def collapse(self):
        self._expanded = False
        self.prompt_frame.grid_forget()
        if self.registry:
            self.registry.close(self)

    def _read_widget(self):
        w = self.widget
        if isinstance(w, ctk.CTkTextbox):
            return w.get("1.0", "end").strip()
        return w.get().strip()

    def _write_start(self):
        existing = self._read_widget()
        self._append_mode = bool(existing)
        if isinstance(self.widget, ctk.CTkTextbox):
            if self._append_mode:
                self.widget.insert("end", "\n\n")
            else:
                self.widget.delete("1.0", "end")
        else:
            if not self._append_mode:
                self.widget.delete(0, "end")

    def _write_delta(self, text):
        if isinstance(self.widget, ctk.CTkTextbox):
            self.widget.insert("end", text)
            self.widget.see("end")
        else:
            cur = self.widget.get()
            self.widget.delete(0, "end")
            self.widget.insert(0, cur + text)

    def _set_busy(self, busy, msg=""):
        self._busy = busy
        state = "disabled" if busy else "normal"
        self.gen_btn.configure(state=state)
        self.run_btn.configure(state=state)
        self.prompt_entry.configure(state=state)
        self.mode_menu.configure(state=state)
        if msg:
            self.app.status(msg)

    def _ask_user(self, prompt):
        holder, ev = {}, threading.Event()

        def do():
            dlg = ctk.CTkInputDialog(text=prompt, title="The team needs input")
            holder["v"] = dlg.get_input()
            ev.set()
        self.after(0, do)
        ev.wait()
        return holder.get("v") or ""

    def _run(self):
        if self._busy:
            return
        prompt = self.prompt_entry.get().strip()
        if not prompt:
            self.app.status("Enter a prompt for Generate.")
            return
        mode = self.mode_menu.get()
        existing = self._read_widget()
        extra = self.context_fn()
        paths = self.app.engine.paths
        engine = self.app.engine

        self._set_busy(True, f"Generating {self.field_label}...")
        self.after(0, self._write_start)

        def worker():
            try:
                if mode == "Orchestrated":
                    task = story_bible_gen.build_orchestrated_task(
                        paths, self.field_label, prompt, existing, extra)
                    for kind, payload in story_bible_gen.orchestrate_field(
                            engine, task, ask_user=self._ask_user):
                        if kind == "delta":
                            self._queue.put(("delta", payload))
                    self._queue.put(("done", None))
                else:
                    for delta in story_bible_gen.stream_field(
                            engine, paths, self.field_label, prompt, mode,
                            existing, extra):
                        self._queue.put(("delta", delta))
                    self._queue.put(("done", None))
            except Exception as exc:
                self._queue.put(("error", str(exc)))

        threading.Thread(target=worker, daemon=True).start()

    def _poll(self):
        try:
            while True:
                kind, payload = self._queue.get_nowait()
                if kind == "delta":
                    self._write_delta(payload)
                elif kind == "done":
                    self._set_busy(False, f"{self.field_label} generated.")
                    self.collapse()
                elif kind == "error":
                    self._set_busy(False, f"Generate failed: {payload}")
        except queue.Empty:
            pass
        self.after(60, self._poll)


def attach_field_generate(parent, app, field_label, multiline=True, height=70,
                          context_fn=None, registry=None):
    """Create a field block with label, widget, and Generate controls."""
    return FieldGenerateBlock(
        parent, app, field_label, multiline=multiline, height=height,
        context_fn=context_fn, registry=registry)
