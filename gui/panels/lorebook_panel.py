"""Lore Book panel - browse/edit characters & world entries, generate images."""

import base64
import os
import threading

import customtkinter as ctk

from gui import theme
from gui.panels.base import BasePanel, bind_scroll_width
from gui.tooltip import attach
from gui.widgets.generate_field import GenerateRegistry, attach_field_generate
from src import lore

try:
    from PIL import Image
    PIL_OK = True
except Exception:
    Image = None
    PIL_OK = False

_FIELDS = [
    ("name", "Name", False),
    ("type", "Type (character/world)", False),
    ("notes", "Notes", True),
    ("appearance", "Appearance (used for images)", True),
    ("goals", "Goals", True),
    ("imagePrompt", "Image prompt override", True),
]


class LoreBookPanel(BasePanel):
    title = "Lore Book"

    def __init__(self, master, app):
        super().__init__(master, app)
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=2)
        self.current_id = None
        self._gen_registry = GenerateRegistry()
        self.header("Lore Book", "Canonical characters and world entries. Flag "
                                 "entries 'always include' to inject them into agents.")
        self._build_list()
        self._build_form()
        self.on_show()

    def _paths(self):
        return self.app.engine.paths

    # ----------------------- list ------------------------------------------
    def _build_list(self):
        left = ctk.CTkFrame(self, fg_color=theme.BG_CARD)
        left.grid(row=1, column=0, sticky="nsew", padx=(16, 8), pady=(4, 16))
        left.grid_rowconfigure(1, weight=1)
        left.grid_columnconfigure(0, weight=1)
        topbar = ctk.CTkFrame(left, fg_color="transparent")
        topbar.grid(row=0, column=0, sticky="ew", padx=8, pady=8)
        ctk.CTkButton(topbar, text="+ Character", width=110,
                      command=lambda: self._new("character")).pack(side="left", padx=2)
        ctk.CTkButton(topbar, text="+ World", width=90,
                      command=lambda: self._new("world")).pack(side="left", padx=2)
        self.listbox = ctk.CTkScrollableFrame(left, fg_color=theme.BG_SIDEBAR)
        self.listbox.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 8))
        self.listbox.grid_columnconfigure(0, weight=1)

    def _build_form(self):
        right = ctk.CTkScrollableFrame(self, fg_color=theme.BG_CARD)
        right.grid(row=1, column=1, sticky="nsew", padx=(8, 16), pady=(4, 16))
        right.grid_columnconfigure(0, weight=1)
        bind_scroll_width(right)
        self.form = right
        self.widgets = {}
        row = 0
        for key, label, multiline in _FIELDS:
            block = attach_field_generate(
                right, self.app, label, multiline=multiline,
                context_fn=self._lore_context,
                registry=self._gen_registry,
            )
            block.grid(row=row, column=0, sticky="ew", padx=12, pady=(0, 4))
            if key == "imagePrompt":
                attach(block.widget, "Overrides the auto-built image prompt for this entry. "
                          "Leave blank to use Appearance/Notes.")
            self.widgets[key] = block.widget
            row += 1

        flags = ctk.CTkFrame(right, fg_color="transparent")
        flags.grid(row=row, column=0, sticky="ew", padx=12, pady=6)
        self.always = ctk.BooleanVar()
        self.pinned = ctk.BooleanVar()
        always_cb = ctk.CTkCheckBox(flags, text="Always include", variable=self.always)
        always_cb.pack(side="left", padx=4)
        attach(always_cb, "Always inject this entry into agent prompts, even if "
                          "auto-scan doesn't pick it up.")
        pinned_cb = ctk.CTkCheckBox(flags, text="Pinned", variable=self.pinned)
        pinned_cb.pack(side="left", padx=4)
        attach(pinned_cb, "Pin to the top of the lore list and give it priority "
                          "when context space is limited.")

        btns = ctk.CTkFrame(right, fg_color="transparent")
        btns.grid(row=row + 1, column=0, sticky="ew", padx=12, pady=8)
        ctk.CTkButton(btns, text="Save", width=90, command=self._save).pack(side="left", padx=2)
        ctk.CTkButton(btns, text="Delete", width=90, fg_color=theme.RED,
                      hover_color="#a82a2a", command=self._delete).pack(side="left", padx=2)
        gen_btn = ctk.CTkButton(btns, text="Generate Image", command=self._generate,
                                fg_color=theme.PURPLE, hover_color="#5e1f96")
        gen_btn.pack(side="left", padx=2)
        attach(gen_btn, "Render a portrait/image for this entry via ComfyUI using "
                        "its appearance/image prompt.")

        self.image_label = ctk.CTkLabel(right, text="(no image)", text_color=theme.TEXT_MUTED)
        self.image_label.grid(row=row + 2, column=0, sticky="ew", padx=12, pady=8)
        self.gen_status = ctk.CTkLabel(right, text="", text_color=theme.TEXT_MUTED)
        self.gen_status.grid(row=row + 3, column=0, sticky="ew", padx=12, pady=(0, 8))

    def _lore_context(self):
        name = self.widgets.get("name")
        typ = self.widgets.get("type")
        parts = ["Lorebook entry"]
        if name:
            parts.append(f"Name: {name.get().strip()}")
        if typ:
            parts.append(f"Type: {typ.get().strip()}")
        return "\n".join(parts)

    # ----------------------- data ------------------------------------------
    def on_show(self):
        self._reload_list()

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
                ctk.CTkButton(self.listbox, text=e["name"] + mark, anchor="w",
                              fg_color="transparent", border_width=0,
                              text_color=theme.TEXT_PRIMARY, hover_color=theme.BG_CARD,
                              command=lambda x=e["id"]: self._select(x)
                              ).grid(row=row, column=0, sticky="ew", padx=6, pady=1)
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
            if isinstance(w, ctk.CTkTextbox):
                w.delete("1.0", "end")
                w.insert("1.0", val)
            else:
                w.delete(0, "end")
                w.insert(0, val)
        self.always.set(bool((entry or {}).get("alwaysInclude")))
        self.pinned.set(bool((entry or {}).get("pinned")))
        self._show_image((entry or {}).get("portraitPath"))

    def _collect(self):
        out = {}
        for key, w in self.widgets.items():
            out[key] = (w.get("1.0", "end").strip() if isinstance(w, ctk.CTkTextbox)
                        else w.get().strip())
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
        self.app.status(f"Saved lore entry '{entry['name']}'.")

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
