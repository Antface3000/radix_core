"""Transient toast notifications (save confirmations, etc.)."""

import customtkinter as ctk

from gui import theme

_STYLES = {
    "success": {"border": theme.LIME, "icon": "\u2713"},
    "error": {"border": theme.RED, "icon": "!"},
    "info": {"border": theme.BORDER_ACTIVE, "icon": ""},
}


class ToastOverlay:
    """Bottom-center toast on the main app window."""

    def __init__(self, root):
        self.root = root
        self._hide_job = None
        self._frame = None

    def show(self, message, kind="success", duration_ms=2600):
        if self._hide_job:
            try:
                self.root.after_cancel(self._hide_job)
            except Exception:
                pass
            self._hide_job = None

        if self._frame is not None:
            try:
                if self._frame.winfo_exists():
                    self._frame.destroy()
            except Exception:
                pass
            self._frame = None

        style = _STYLES.get(kind, _STYLES["info"])
        self._frame = ctk.CTkFrame(
            self.root,
            fg_color=theme.BG_ELEVATED,
            border_color=style["border"],
            border_width=2,
            corner_radius=10,
        )
        row = ctk.CTkFrame(self._frame, fg_color="transparent")
        row.pack(padx=16, pady=10)
        if style["icon"]:
            ctk.CTkLabel(
                row, text=style["icon"], width=18,
                text_color=style["border"],
                font=ctk.CTkFont(size=15, weight="bold"),
            ).pack(side="left", padx=(0, 8))
        ctk.CTkLabel(
            row, text=message, text_color=theme.TEXT_PRIMARY,
            font=ctk.CTkFont(size=13, weight="bold"),
        ).pack(side="left")

        self._frame.place(relx=0.5, rely=1.0, anchor="s", y=-34)
        self._frame.lift()
        self._hide_job = self.root.after(duration_ms, self.hide)

    def hide(self):
        self._hide_job = None
        if self._frame is not None:
            try:
                if self._frame.winfo_exists():
                    self._frame.destroy()
            except Exception:
                pass
            self._frame = None
