"""Font size and auto-scroll prefs for panel CTkTextboxes (not the main tk.Text editor)."""

import customtkinter as ctk

import config


def font_size(settings):
    try:
        return int(settings.get("ui.panel_font_size", config.PANEL_FONT_SIZE))
    except (TypeError, ValueError):
        return config.PANEL_FONT_SIZE


def font(settings):
    return (config.PANEL_FONT_FAMILY, font_size(settings))


def auto_scroll(settings):
    return bool(settings.get("ui.panel_auto_scroll", config.PANEL_AUTO_SCROLL))


def new_textbox(master, settings, **kwargs):
    """Create a CTkTextbox using the configured panel font."""
    kwargs.setdefault("wrap", "word")
    return ctk.CTkTextbox(master, font=font(settings), **kwargs)


def configure(textbox, settings):
    """Apply the current panel font to an existing CTkTextbox."""
    textbox.configure(font=font(settings))
    return textbox


def scroll_end(textbox, settings):
    """Scroll to the end when auto-scroll is enabled."""
    if auto_scroll(settings):
        try:
            textbox.see("end")
        except Exception:
            pass


def apply_font_tree(root, settings):
    """Update every CTkTextbox under root (main manuscript uses tk.Text)."""
    if isinstance(root, ctk.CTkTextbox):
        try:
            root.configure(font=font(settings))
        except Exception:
            pass
    try:
        for child in root.winfo_children():
            apply_font_tree(child, settings)
    except Exception:
        pass
