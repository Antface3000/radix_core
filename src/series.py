"""Series canon: a book project can share lore/bible/world-state with a parent."""

from __future__ import annotations

from src import projects

CANON_KEYS = ("lore", "bible", "world_state")


def share_from(paths) -> str | None:
    cfg = projects.read_json_safe(paths["config"], {})
    parent = (cfg.get("series") or {}).get("share_from")
    return parent or None


def set_share_from(paths, parent_id: str | None) -> None:
    cfg = projects.read_json_safe(paths["config"], {})
    series = dict(cfg.get("series") or {})
    if parent_id:
        series["share_from"] = parent_id
    else:
        series.pop("share_from", None)
    cfg["series"] = series
    projects.write_json(paths["config"], cfg)


def overlay_canon_paths(paths, project_id: str) -> dict:
    """Rewrite lore/bible/world_state paths to the series parent when set."""
    parent = share_from(paths)
    if not parent or parent == project_id:
        return paths
    parent_paths = projects.project_paths(parent)
    out = dict(paths)
    for key in CANON_KEYS:
        out[key] = parent_paths[key]
    return out
