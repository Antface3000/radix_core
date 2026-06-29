"""Image Gen panel - freeform ComfyUI rendering with live progress."""

import base64
import os
import threading
import time

import customtkinter as ctk

from gui import theme
from gui.panels.base import BasePanel
from gui.tooltip import attach

try:
    from PIL import Image
    PIL_OK = True
except Exception:
    Image = None
    PIL_OK = False


class ImageGenPanel(BasePanel):
    title = "Image Gen"

    def __init__(self, master, app):
        super().__init__(master, app)
        self.grid_rowconfigure(2, weight=1)
        self.grid_columnconfigure(0, weight=1)
        self.last_b64 = None
        self.header("Image Generation", "Renders through your local ComfyUI server "
                                        "using the configured workflow.")
        self._build_controls()
        self.image_label = ctk.CTkLabel(self, text="(render to preview)",
                                        text_color=theme.TEXT_MUTED)
        self.image_label.grid(row=2, column=0, sticky="nsew", padx=16, pady=8)

    def _build_controls(self):
        box = ctk.CTkFrame(self, fg_color=theme.BG_CARD)
        box.grid(row=1, column=0, sticky="ew", padx=16, pady=6)
        box.grid_columnconfigure(0, weight=1)

        self.prompt = ctk.CTkTextbox(box, height=80, wrap="word")
        self.prompt.grid(row=0, column=0, columnspan=4, sticky="ew", padx=10, pady=10)
        self.prompt.insert("1.0", "A lone figure on a rain-slick street at night")

        ctk.CTkLabel(box, text="Subject:").grid(row=1, column=0, sticky="e", padx=6)
        self.kind = ctk.CTkOptionMenu(box, values=["character", "background", "location",
                                                   "item", "faction", "event", "world"],
                                      width=130)
        self.kind.grid(row=1, column=1, sticky="w", padx=6, pady=6)
        self.kind.set("character")
        attach(self.kind, "Subject kind picks the right workflow/tags (e.g. "
                          "character = portrait framing, background = scenery).")

        sizebar = ctk.CTkFrame(box, fg_color="transparent")
        sizebar.grid(row=1, column=2, columnspan=2, sticky="e", padx=6)
        self.width = ctk.CTkEntry(sizebar, width=70, placeholder_text="W")
        self.width.pack(side="left", padx=2)
        self.width.insert(0, str(self.app.settings.get("image.width", 1024)))
        self.height = ctk.CTkEntry(sizebar, width=70, placeholder_text="H")
        self.height.pack(side="left", padx=2)
        self.height.insert(0, str(self.app.settings.get("image.height", 1024)))
        self.seed = ctk.CTkEntry(sizebar, width=110, placeholder_text="seed (blank=random)")
        self.seed.pack(side="left", padx=2)
        attach(self.seed, "Fix the seed to reproduce the exact same image; leave "
                          "blank for a random result each render.")

        actions = ctk.CTkFrame(box, fg_color="transparent")
        actions.grid(row=2, column=0, columnspan=4, sticky="ew", padx=10, pady=(0, 10))
        self.render_btn = ctk.CTkButton(actions, text="Render", width=120, command=self._render)
        self.render_btn.pack(side="left")
        ctk.CTkButton(actions, text="Save As...", width=100, command=self._save_as,
                      **theme.secondary_btn()).pack(side="left", padx=8)
        self.progress = ctk.CTkProgressBar(actions)
        self.progress.pack(side="left", fill="x", expand=True, padx=8)
        self.progress.set(0)
        self.status_lbl = ctk.CTkLabel(box, text="", text_color=theme.TEXT_MUTED)
        self.status_lbl.grid(row=3, column=0, columnspan=4, sticky="w", padx=12, pady=(0, 8))

    def _render(self):
        text = self.prompt.get("1.0", "end").strip()
        if not text:
            return
        opts = {"subjectKind": self.kind.get()}
        try:
            opts["width"] = int(self.width.get())
            opts["height"] = int(self.height.get())
        except ValueError:
            pass
        if self.seed.get().strip():
            opts["seedOverride"] = self.seed.get().strip()
        self.render_btn.configure(state="disabled", text="Rendering...")
        self.progress.set(0)
        self.status_lbl.configure(text="Submitting to ComfyUI...")
        threading.Thread(target=self._worker, args=(text, opts), daemon=True).start()

    def _worker(self, text, opts):
        def on_progress(u):
            val, mx = u.get("value", 0), u.get("max", 0)
            frac = (val / mx) if mx else 0
            self.after(0, lambda: (self.progress.set(frac),
                                   self.status_lbl.configure(text=u.get("label", "working"))))

        def on_image(b64, _pid):
            self.after(0, lambda: self._show(b64))

        def on_error(err):
            self.after(0, lambda: self._done("Error: " + str(err.get("message", err))))
        try:
            self.app.comfy.render(text, render_options=opts, on_progress=on_progress,
                                  on_image=on_image, on_error=on_error)
        except Exception as exc:
            self.after(0, lambda: self._done(f"Error: {exc}"))

    def _show(self, b64):
        self.last_b64 = b64
        self.progress.set(1)
        if PIL_OK:
            import io
            try:
                img = Image.open(io.BytesIO(base64.b64decode(b64)))
                ctk_img = ctk.CTkImage(light_image=img, dark_image=img, size=(512, 512))
                self.image_label.configure(image=ctk_img, text="")
                self.image_label.image = ctk_img
            except Exception:
                pass
        self._done("Render complete.")

    def _done(self, msg):
        self.render_btn.configure(state="normal", text="Render")
        self.status_lbl.configure(text=msg)

    def _save_as(self):
        if not self.last_b64:
            self.status_lbl.configure(text="Nothing to save yet.")
            return
        folder = self.app.engine.paths["backgrounds"]
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, f"render_{int(time.time())}.png")
        with open(path, "wb") as f:
            f.write(base64.b64decode(self.last_b64))
        self.status_lbl.configure(text=f"Saved: {path}")
