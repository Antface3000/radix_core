"""Lore Book panel - browse/edit characters & world entries, generate images."""

import base64
import os
import threading

import customtkinter as ctk

from gui import theme
from gui.panels.base import BasePanel, bind_scroll_width
from gui.tooltip import attach
from gui.widgets.generate_field import GenerateRegistry, attach_field_generate, refresh_textbox_scroll
from src import lore, worldcontext

try:
    from PIL import Image
    PIL_OK = True
except Exception:
    Image = None
    PIL_OK = False

# Short labels in the UI; full descriptions in tooltips (narrow dock friendly).
_FIELDS = [
    ("name", "Name", False, ""),
    ("type", "Type", False, "character or world"),
    ("notes", "Notes", True, ""),
    ("appearance", "Appearance", True, "Used for image generation"),
    ("goals", "Goals", True, ""),
    ("imagePrompt", "Image prompt", True, "Optional override for ComfyUI image generation"),
]

_STACK_BELOW = 620


class LoreBookPanel(BasePanel):
    title = "Lore Book"

    def __init__(self, master, app, embedded=False):
        super().__init__(master, app)
        self.embedded = embedded
        self._stacked = False
        self.current_id = None
        self._dirty = False
        self._gen_registry = GenerateRegistry()

        content_row = 0
        if not embedded:
            self.grid_rowconfigure(1, weight=1)
            self.header("Lore Book", "Canonical characters and world entries. Flag "
                                     "entries 'always include' to inject them into agents.")
            content_row = 1
        else:
            self.grid_rowconfigure(0, weight=1)

        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=2)

        self._body = ctk.CTkFrame(self, fg_color="transparent")
        self._body.grid(row=content_row, column=0, columnspan=2, sticky="nsew")
        self._body.grid_columnconfigure(0, weight=1)
        self._body.grid_columnconfigure(1, weight=2)
        self._body.grid_rowconfigure(0, weight=1)

        self._build_list(self._body)
        self._build_form(self._body)
        self.bind("<Configure>", self._reflow_layout, add="+")
        self.on_show()

    def _paths(self):
        return self.app.engine.paths

    def _reflow_layout(self, event=None):
        if event is not None and event.widget is not self:
            return
        w = self.winfo_width()
        if w < 2:
            return
        stack = w < _STACK_BELOW
        if stack == self._stacked:
            return
        self._stacked = stack
        if stack:
            self._body.grid_columnconfigure(1, weight=0)
            self.list_frame.grid(row=0, column=0, sticky="nsew", padx=(4, 4), pady=(0, 4))
            self.form.grid(row=1, column=0, sticky="nsew", padx=(4, 4), pady=(4, 4))
            self._body.grid_rowconfigure(0, weight=0)
            self._body.grid_rowconfigure(1, weight=1)
        else:
            self._body.grid_rowconfigure(0, weight=1)
            self._body.grid_rowconfigure(1, weight=0)
            self._body.grid_columnconfigure(1, weight=2)
            self.list_frame.grid(row=0, column=0, sticky="nsew", padx=(4, 8), pady=4)
            self.form.grid(row=0, column=1, sticky="nsew", padx=(4, 4), pady=4)

    # ----------------------- list ------------------------------------------
    def _build_list(self, parent):
        self.list_frame = ctk.CTkFrame(parent, fg_color=theme.BG_CARD)
        self.list_frame.grid(row=0, column=0, sticky="nsew", padx=(4, 8), pady=4)
        self.list_frame.grid_rowconfigure(1, weight=1)
        self.list_frame.grid_columnconfigure(0, weight=1)

        topbar = ctk.CTkFrame(self.list_frame, fg_color="transparent")
        topbar.grid(row=0, column=0, sticky="ew", padx=8, pady=8)
        ctk.CTkButton(topbar, text="+ Character", width=100,
                      command=lambda: self._new("character"),
                      **theme.secondary_btn()).pack(side="left", padx=2)
        ctk.CTkButton(topbar, text="+ World", width=88,
                      command=lambda: self._new("world"),
                      **theme.secondary_btn()).pack(side="left", padx=2)

        self.listbox = ctk.CTkScrollableFrame(self.list_frame, fg_color=theme.BG_SIDEBAR)
        self.listbox.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 8))
        self.listbox.grid_columnconfigure(0, weight=1)
        bind_scroll_width(self.listbox)

    def _build_form(self, parent):
        self.form = ctk.CTkScrollableFrame(parent, fg_color=theme.BG_CARD)
        self.form.grid(row=0, column=1, sticky="nsew", padx=(4, 4), pady=4)
        self.form.grid_columnconfigure(0, weight=1)
        bind_scroll_width(self.form)
        self.widgets = {}
        row = 0
        for key, label, multiline, tip in _FIELDS:
            if multiline:
                box_h, min_h, max_h = 100, 72, 320
            else:
                box_h, min_h, max_h = 40, 32, 100
            block = attach_field_generate(
                self.form, self.app, label, multiline=multiline,
                height=box_h, min_height=min_h, max_height=max_h,
                context_fn=self._lore_context,
                registry=self._gen_registry,
                tooltip=tip,
            )
            block.grid(row=row, column=0, sticky="ew", padx=8, pady=(0, 6))
            if key == "imagePrompt" and tip:
                attach(block.widget, tip)
            self.widgets[key] = block.widget
            block.widget._textbox.bind("<KeyRelease>", self._mark_dirty, add="+")
            row += 1

        flags = ctk.CTkFrame(self.form, fg_color="transparent")
        flags.grid(row=row, column=0, sticky="ew", padx=8, pady=6)
        self.always = ctk.BooleanVar()
        self.pinned = ctk.BooleanVar()
        always_cb = ctk.CTkCheckBox(flags, text="Always include", variable=self.always)
        always_cb.pack(side="left", padx=4)
        attach(always_cb, "Always inject this entry into agent prompts.")
        always_cb.configure(command=self._mark_dirty)
        pinned_cb = ctk.CTkCheckBox(flags, text="Pinned", variable=self.pinned)
        pinned_cb.pack(side="left", padx=4)
        attach(pinned_cb, "Pin for priority in agent context.")
        pinned_cb.configure(command=self._mark_dirty)

        btns = ctk.CTkFrame(self.form, fg_color="transparent")
        btns.grid(row=row + 1, column=0, sticky="ew", padx=8, pady=8)
        btns.grid_columnconfigure(0, weight=1)
        btn_inner = ctk.CTkFrame(btns, fg_color="transparent")
        btn_inner.grid(row=0, column=0, sticky="ew")
        self.save_btn = ctk.CTkButton(btn_inner, text="Save", width=88, command=self._save,
                                      **theme.primary_btn())
        self.save_btn.pack(side="left", padx=2, pady=2)
        ctk.CTkButton(btn_inner, text="Delete", width=88, command=self._delete,
                      **theme.danger_btn()).pack(side="left", padx=2, pady=2)
        gen_img_btn = ctk.CTkButton(btn_inner, text="Generate Image", command=self._generate,
                                    **theme.accent_btn(theme.PURPLE, "#5e1f96"))
        gen_img_btn.pack(side="left", padx=2, pady=2)
        attach(gen_img_btn, "Render via ComfyUI using appearance/notes.")

        self.image_label = ctk.CTkLabel(self.form, text="(no image)", text_color=theme.TEXT_MUTED)
        self.image_label.grid(row=row + 2, column=0, sticky="ew", padx=8, pady=8)
        self.gen_status = ctk.CTkLabel(self.form, text="", text_color=theme.TEXT_MUTED,
                                         wraplength=360, justify="left", anchor="w")
        self.gen_status.grid(row=row + 3, column=0, sticky="ew", padx=8, pady=(0, 8))

    def _lore_context(self):
        paths = self._paths()
        base = worldcontext.assemble(paths) if paths else ""
        name = self.widgets.get("name")
        typ = self.widgets.get("type")
        parts = [base] if base else []
        if name:
            n = name.get("1.0", "end").strip()
            if n:
                parts.append(f"Current entry name: {n}")
        if typ:
            t = typ.get("1.0", "end").strip()
            if t:
                parts.append(f"Current entry type: {t}")
        return "\n\n".join(parts)

    def _mark_dirty(self, _event=None):
        if not self._dirty:
            self._dirty = True
            self.save_btn.configure(text="Save *")

    def _clear_dirty(self):
        self._dirty = False
        self.save_btn.configure(text="Save")

    # ----------------------- data ------------------------------------------
    def on_show(self):
        self._reload_list()
        self.after_idle(self._reflow_layout)

    def on_project_change(self):
        self.current_id = None
        self._reload_list()
        self._load_entry(None)

    def _reload_list(self):
        for w in self.listbox.winfo_children():
            w.destroy()
        data = lore.read(self._paths()["lore"])
        row = 0
        for section, entries in (("Characters", data["characters"]),
                                 ("World", data["world"])):
            ctk.CTkLabel(self.listbox, text=section.upper(), anchor="w",
                         text_color=theme.LIME, font=ctk.CTkFont(size=12, weight="bold")
                         ).grid(row=row, column=0, sticky="ew", padx=6, pady=(8, 2))
            row += 1
            for e in entries:
                mark = " *" if e.get("alwaysInclude") else ""
                full = e["name"] + mark
                btn = ctk.CTkButton(
                    self.listbox, text=full, anchor="w",
                    **theme.ghost_btn())
                btn.configure(height=28)
                btn.grid(row=row, column=0, sticky="ew", padx=4, pady=1)
                attach(btn, full)
                btn.configure(command=lambda x=e["id"]: self._select(x))
                row += 1

    def _select(self, entry_id):
        data = lore.read(self._paths()["lore"])
        entry = next((e for e in data["characters"] + data["world"]
                      if e["id"] == entry_id), None)
        self._load_entry(entry)

    def _load_entry(self, entry):
        self.current_id = entry["id"] if entry else None
        for key, w in self.widgets.items():
            val = str((entry or {}).get(key, "") or "")
            w.delete("1.0", "end")
            w.insert("1.0", val)
            refresh_textbox_scroll(w)
        self.always.set(bool((entry or {}).get("alwaysInclude")))
        self.pinned.set(bool((entry or {}).get("pinned")))
        self._clear_dirty()
        self._show_image((entry or {}).get("portraitPath"))

    def _collect(self):
        out = {}
        for key, w in self.widgets.items():
            out[key] = w.get("1.0", "end").strip()
        out["alwaysInclude"] = self.always.get()
        out["pinned"] = self.pinned.get()
        if out.get("type") not in ("character", "world"):
            out["type"] = "character"
        return out

    def _new(self, kind):
        entry = lore.add(self._paths()["lore"], {"type": kind, "name": "New " + kind})
        self._reload_list()
        self._load_entry(entry)

    def _save(self):
        data = self._collect()
        if not self.current_id:
            entry = lore.add(self._paths()["lore"], data)
        else:
            data["id"] = self.current_id
            entry = lore.update(self._paths()["lore"], data)
        self.current_id = entry["id"]
        self._reload_list()
        self._clear_dirty()
        self.app.status(f"Saved lore entry '{entry['name']}'.")
        if hasattr(self.app, "refresh_setting_previews"):
            self.app.refresh_setting_previews()

    def flush_if_dirty(self):
        if not self._dirty:
            return
        data = self._collect()
        if not data.get("name"):
            return
        self._save()

    def _delete(self):
        if not self.current_id:
            return
        lore.remove(self._paths()["lore"], self.current_id)
        self.current_id = None
        self._reload_list()
        self._load_entry(None)
        self.app.status("Lore entry deleted.")

    # ----------------------- image generation ------------------------------
    def _generate(self):
        if not self.current_id:
            self.gen_status.configure(text="Save the entry first.")
            return
        data = self._collect()
        prompt_text = data.get("imagePrompt") or data.get("appearance") \
            or data.get("notes") or data.get("name")
        kind = "character" if data.get("type") == "character" else "background"
        self.gen_status.configure(text="Rendering via ComfyUI...")
        threading.Thread(target=self._render_worker,
                         args=(prompt_text, kind, self.current_id), daemon=True).start()

    def _render_worker(self, prompt_text, kind, entry_id):
        def on_progress(u):
            self.after(0, lambda: self.gen_status.configure(
                text=f"{u.get('label', 'working')}  ({u.get('value', 0)}/{u.get('max', 0)})"))

        def on_image(b64, _pid):
            self.after(0, lambda: self._save_image(b64, entry_id, kind))

        def on_error(err):
            self.after(0, lambda: self.gen_status.configure(
                text="Error: " + str(err.get('message', err))))
        try:
            self.app.comfy.render(prompt_text, render_options={"subjectKind": kind},
                                  on_progress=on_progress, on_image=on_image,
                                  on_error=on_error)
        except Exception as exc:
            self.after(0, lambda: self.gen_status.configure(text=f"Error: {exc}"))

    def _save_image(self, b64, entry_id, kind):
        folder = self._paths()["portraits"] if kind == "character" else self._paths()["backgrounds"]
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, f"{entry_id}.png")
        with open(path, "wb") as f:
            f.write(base64.b64decode(b64))
        try:
            lore.update(self._paths()["lore"], {"id": entry_id, "portraitPath": path})
        except ValueError:
            pass
        self.gen_status.configure(text="Image saved.")
        self._show_image(path)

    def _show_image(self, path):
        if path and PIL_OK and os.path.exists(path):
            try:
                img = Image.open(path)
                ctk_img = ctk.CTkImage(light_image=img, dark_image=img, size=(220, 220))
                self.image_label.configure(image=ctk_img, text="")
                self.image_label.image = ctk_img
                return
            except Exception:
                pass
        self.image_label.configure(image=None, text="(no image)")
