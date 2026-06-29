"""Theme constants + loader for the Radix Core UI.

Mirrors unblocker's lime/dark palette. The CustomTkinter widget colors come from
assets/theme/radix_theme.json (loaded via apply_theme); these constants are for
widgets/states CTk themes don't cover (tags, status dots, accents).
"""

import os

import customtkinter as ctk

import config

# Core palette (from unblocker renderer/style.css).
BG_APP = "#080C08"
BG_SIDEBAR = "#0C140C"
BG_CARD = "#0E180E"
BG_INPUT = "#0A120A"
LIME = "#B8E800"
LIME_DIM = "#93BA00"
BLUE = "#2874D4"
ORANGE = "#FF5800"
PURPLE = "#7A28C0"
PINK = "#CC0066"
RED = "#E03A3A"
GREEN = "#46C24A"
TEXT_PRIMARY = "#E4ECD0"
TEXT_MUTED = "#4A6040"
BORDER = "#243018"
BORDER_ACTIVE = "#5B7A1E"
# Elevated surfaces for legible secondary/ghost buttons (the old transparent
# buttons vanished against the near-black background until hover).
BG_ELEVATED = "#1A2912"
BG_HOVER = "#243018"

# Tier accent colors for the agent UI.
TIER_COLORS = {
    "Tier 1 - Architects": PURPLE,
    "Tier 2 - Operators": BLUE,
    "Tier 3 - Flavor": ORANGE,
}

STATUS_OK = GREEN
STATUS_BAD = RED
STATUS_UNKNOWN = TEXT_MUTED


def apply_theme(settings=None):
    """Apply appearance mode + the Radix color theme. Falls back to a built-in
    CTk theme if the JSON is missing or the configured theme isn't 'radix'."""
    mode = config.APPEARANCE_MODE
    theme = config.COLOR_THEME
    if settings is not None:
        mode = settings.get("appearance_mode", mode)
        theme = settings.get("color_theme", theme)

    ctk.set_appearance_mode(mode)
    if theme == "radix" and os.path.exists(config.THEME_PATH):
        ctk.set_default_color_theme(config.THEME_PATH)
    elif theme in ("blue", "green", "dark-blue"):
        ctk.set_default_color_theme(theme)
    elif os.path.exists(config.THEME_PATH):
        ctk.set_default_color_theme(config.THEME_PATH)
    else:
        ctk.set_default_color_theme("blue")


# ----------------------- button style helpers -------------------------------
# Use these instead of bare fg_color="transparent" so every button stays
# legible at rest, not just on hover. Each returns kwargs for ctk.CTkButton.

def primary_btn():
    """Bright lime call-to-action."""
    return dict(fg_color=LIME, hover_color=LIME_DIM, text_color=BG_APP,
                corner_radius=8)


def secondary_btn():
    """Filled, elevated surface with a visible lime-tinted border."""
    return dict(fg_color=BG_ELEVATED, hover_color=BG_HOVER,
                text_color=TEXT_PRIMARY, border_color=BORDER_ACTIVE,
                border_width=1, corner_radius=8)


def ghost_btn():
    """Transparent fill but a clearly visible border at rest."""
    return dict(fg_color="transparent", hover_color=BG_HOVER,
                text_color=TEXT_PRIMARY, border_color=BORDER_ACTIVE,
                border_width=1, corner_radius=8)


def danger_btn():
    return dict(fg_color=RED, hover_color="#b32d2d", text_color="#FFFFFF",
                corner_radius=8)


def accent_btn(color=BLUE, hover=None):
    return dict(fg_color=color, hover_color=hover or LIME_DIM,
                text_color="#FFFFFF", corner_radius=8)


def _sync_segment_text_colors(segmented, selected_text, unselected_text):
    current = segmented._current_value
    for val, btn in segmented._buttons_dict.items():
        btn.configure(text_color=selected_text if val == current else unselected_text)


def style_segmented_button(segmented, selected_text=None, unselected_text=None):
    """CTk 5.x segmented controls use one text_color — force black on the active segment."""
    selected_text = selected_text or BG_APP
    unselected_text = unselected_text or TEXT_PRIMARY
    segmented._radix_selected_text = selected_text
    segmented._radix_unselected_text = unselected_text

    if not getattr(segmented, "_radix_text_patched", False):
        orig_select = segmented._select_button_by_value

        def _select_with_text(value):
            orig_select(value)
            _sync_segment_text_colors(
                segmented, segmented._radix_selected_text, segmented._radix_unselected_text)

        segmented._select_button_by_value = _select_with_text
        segmented._radix_text_patched = True

    if segmented._current_value:
        segmented._select_button_by_value(segmented._current_value)
    elif segmented._buttons_dict:
        _sync_segment_text_colors(segmented, selected_text, unselected_text)


def style_tabview(tabview, selected_text=None, unselected_text=None):
    """Readable tab labels: light text inactive, black text on lime active tab."""
    sb = tabview._segmented_button
    style_segmented_button(sb, selected_text, unselected_text)
    if not getattr(tabview, "_radix_tab_hook", False):
        prev_cmd = sb._command

        def _on_tab(value):
            if callable(prev_cmd):
                prev_cmd(value)
            style_segmented_button(sb, selected_text, unselected_text)

        sb.configure(command=_on_tab)
        tabview._radix_tab_hook = True
    try:
        tabview.after_idle(
            lambda: style_segmented_button(sb, selected_text, unselected_text))
    except Exception:
        pass
