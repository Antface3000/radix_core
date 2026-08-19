"""Schema-defined Python tools for agent orchestration."""

from __future__ import annotations

import re
from typing import Any, Callable

from src import lore, story_bible, world_state
from src.story_context import _keyword_hits


def _read_chapter(paths: dict, name: str) -> str:
    import os
    path = os.path.join(paths["chapters"], f"{name}.txt")
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read()
    except OSError:
        return ""


def _entry_search_text(entry) -> str:
    parts = [
        entry.get("name") or "",
        entry.get("notes") or entry.get("content") or "",
        entry.get("description") or "",
    ]
    return " ".join(parts)


def build_tools(paths: dict, match_mode: str = "substring") -> dict[str, Callable[..., Any]]:
    """Register built-in tools bound to a project."""

    def query_lore(query: str = "", kind: str = "") -> dict[str, Any]:
        data = lore.read(paths["lore"])
        results = []
        q = (query or "").strip()
        q_lower = q.lower()
        for section in ("characters", "world"):
            for entry in data.get(section, []):
                text = _entry_search_text(entry)
                text_lower = text.lower()
                if q:
                    if match_mode in ("word_boundary", "regex"):
                        if not _keyword_hits(q, text_lower, match_mode):
                            continue
                    elif q_lower not in text_lower:
                        continue
                et = entry.get("entryType") or entry.get("type")
                if kind and et != kind and kind != section:
                    continue
                results.append(entry)
        return {"matches": results[:20], "count": len(results)}

    def update_lore(name: str, content: str, section: str = "world") -> dict[str, Any]:
        data = lore.read(paths["lore"])
        lore.upsert(paths["lore"], {"name": name, "notes": content, "type": section},
                    mode="append", source="tool")
        return {"ok": True, "name": name}

    def read_bible() -> dict[str, Any]:
        return story_bible.read(paths["bible"])

    def read_world_state() -> dict[str, Any]:
        return world_state.read(paths["world_state"])

    def read_chapter(name: str) -> dict[str, Any]:
        return {"name": name, "text": _read_chapter(paths, name)}

    def search_manuscript(query: str) -> dict[str, Any]:
        import os
        hits = []
        root = paths["chapters"]
        if not os.path.isdir(root):
            return {"hits": hits}
        q = (query or "").strip()
        for fname in os.listdir(root):
            if not fname.endswith(".txt"):
                continue
            text = _read_chapter(paths, fname[:-4])
            text_lower = text.lower()
            if not q:
                continue
            if match_mode in ("word_boundary", "regex"):
                if not _keyword_hits(q, text_lower, match_mode):
                    continue
            elif q.lower() not in text_lower:
                continue
            hits.append({"chapter": fname[:-4], "snippet": text[:200]})
        return {"hits": hits[:10]}

    return {
        "query_lore": query_lore,
        "update_lore": update_lore,
        "read_bible": read_bible,
        "read_world_state": read_world_state,
        "read_chapter": read_chapter,
        "search_manuscript": search_manuscript,
    }
