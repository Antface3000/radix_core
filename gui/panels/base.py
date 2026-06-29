"""Shared base class + helpers for content panels."""

import customtkinter as ctk

from gui import theme


class BasePanel(ctk.CTkFrame):
    """A content panel. `app` exposes engine, settings, comfy, tts + status()."""

    title = "Panel"

    def __init__(self, master, app):
        super().__init__(master, fg_color=theme.BG_APP)
        self.app = app
        self.grid_columnconfigure(0, weight=1)

    def on_show(self):
        """Called each time the panel becomes visible."""

    def on_project_change(self):
        """Called when the active project changes."""

    # --- small UI helpers ---
    def header(self, text, subtitle=""):
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.grid(row=0, column=0, sticky="ew", padx=20, pady=(16, 4))
        ctk.CTkLabel(bar, text=text, font=ctk.CTkFont(size=22, weight="bold"),
                     text_color=theme.LIME).pack(anchor="w")
        if subtitle:
            sub = ctk.CTkLabel(bar, text=subtitle, text_color=theme.TEXT_MUTED,
                               font=ctk.CTkFont(size=12), justify="left",
                               anchor="w")
            sub.pack(anchor="w", fill="x")
            # Wrap to whatever width we're shown at (narrow dock or wide pop-out)
            # so long descriptions never clip off the edge.
            bar.bind("<Configure>",
                     lambda e, lbl=sub: lbl.configure(
                         wraplength=max(160, e.width - 8)))
        return bar

    def section(self, parent, text):
        return ctk.CTkLabel(parent, text=text, anchor="w",
                            font=ctk.CTkFont(size=14, weight="bold"),
                            text_color=theme.TEXT_PRIMARY)


def bind_wraplength(label, parent, pad=24):
    """Keep label text wrapping to the parent width (avoids clipping in narrow docks)."""
    def _resize(event, lbl=label, p=pad):
        lbl.configure(wraplength=max(120, event.width - p))
    parent.bind("<Configure>", _resize, add="+")
    if parent.winfo_width() > 1:
        label.configure(wraplength=max(120, parent.winfo_width() - pad))


def bind_scroll_width(scroll):
    """Sync CTkScrollableFrame inner width to its viewport (CTk version-safe)."""
    fit = getattr(scroll, "_fit_frame_dimensions_to_canvas", None)
    canvas = getattr(scroll, "_parent_canvas", None)
    if fit is None or canvas is None:
        return

    def _resize(event):
        fit(event)

    canvas.bind("<Configure>", _resize, add="+")
    if canvas.winfo_width() > 1:
        fit(None)
