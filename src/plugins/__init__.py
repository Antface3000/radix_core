"""Optional capability packs: Local LLM, Image, Audio."""

from __future__ import annotations

PACKS = ("llm", "image", "audio")

PACK_LABELS = {
    "llm": "Local LLM",
    "image": "Image",
    "audio": "Audio",
}

PACK_PANELS = {
    "llm": ("Team",),
    "image": ("Image Gen",),
    "audio": ("Voice",),
}


def is_enabled(settings, pack: str) -> bool:
    return bool(settings.get(f"plugins.{pack}", False))


def extra_paths(settings) -> list[str]:
    raw = settings.get("plugins.extra_paths") or []
    if isinstance(raw, str):
        return [p.strip() for p in raw.split(";") if p.strip()]
    return [str(p).strip() for p in raw if str(p).strip()]


def panel_allowed(settings, panel_name: str) -> bool:
    for pack, names in PACK_PANELS.items():
        if panel_name in names:
            return is_enabled(settings, pack)
    return True
