"""Lightweight hover tooltips for CustomTkinter widgets.

Pure Tkinter/CTk - no extra dependency. Usage:

    from gui.tooltip import attach
    attach(my_button, "What this control does")

The tooltip shows after a short delay when the pointer rests on the widget and
hides on leave / click / destroy. It guards against destroyed widgets so it is
safe to attach to controls that get rebuilt (panels, pop-outs).
"""

import customtkinter as ctk

from gui import theme


class _ToolTip:
    def __init__(self, widget, text, delay=450, wrap=260):
        self.widget = widget
        self.text = text
        self.delay = delay
        self.wrap = wrap
        self._after_id = None
        self._tip = None
        self._bind_targets(widget)

    def _bind_targets(self, widget, depth=0):
        """Bind hover events on the widget AND its children.

        CTk controls are composites (a CTkButton wraps a canvas + label; a
        CTkFrame holds child widgets that cover it), so the container often
        never sees <Enter>/<Leave> - the inner child does. Binding children
        too makes the tooltip fire reliably. Depth-limited to stay cheap."""
        try:
            widget.bind("<Enter>", self._schedule, add="+")
            widget.bind("<Leave>", self._hide, add="+")
            widget.bind("<ButtonPress>", self._hide, add="+")
            widget.bind("<Destroy>", self._hide, add="+")
        except Exception:
            pass
        if depth >= 4:
            return
        try:
            children = widget.winfo_children()
        except Exception:
            children = []
        for child in children:
            self._bind_targets(child, depth + 1)

    def _schedule(self, _event=None):
        self._cancel()
        try:
            self._after_id = self.widget.after(self.delay, self._show)
        except Exception:
            self._after_id = None

    def _cancel(self):
        if self._after_id is not None:
            try:
                self.widget.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None

    def _show(self):
        if self._tip is not None or not self.text:
            return
        try:
            if not self.widget.winfo_exists():
                return
            x = self.widget.winfo_rootx() + 14
            y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
        except Exception:
            return
        tip = ctk.CTkToplevel(self.widget)
        tip.overrideredirect(True)
        try:
            tip.attributes("-topmost", True)
        except Exception:
            pass
        tip.configure(fg_color=theme.BORDER_ACTIVE)
        ctk.CTkLabel(
            tip, text=self.text, justify="left", wraplength=self.wrap,
            text_color=theme.TEXT_PRIMARY, fg_color=theme.BG_SIDEBAR,
            corner_radius=6, font=ctk.CTkFont(size=11),
        ).pack(padx=1, pady=1, ipadx=6, ipady=4)
        tip.update_idletasks()
        tip.geometry(f"+{x}+{y}")
        self._tip = tip

    def _hide(self, _event=None):
        self._cancel()
        if self._tip is not None:
            try:
                self._tip.destroy()
            except Exception:
                pass
            self._tip = None


def attach(widget, text, delay=450, wrap=260):
    """Attach a hover tooltip to a widget. Returns the _ToolTip handle."""
    return _ToolTip(widget, text, delay=delay, wrap=wrap)
