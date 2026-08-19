"""Inline comments / fix-later notes that stay out of LLM context by default."""

from __future__ import annotations

import os
import uuid

from src import projects


def notes_path(paths, chapter_id: str) -> str:
    return os.path.join(paths["chapters"], f"{chapter_id}.notes.json")


def load(paths, chapter_id: str) -> list[dict]:
    data = projects.read_json_safe(notes_path(paths, chapter_id), {"notes": []})
    return list(data.get("notes") or [])


def save(paths, chapter_id: str, notes: list[dict]) -> None:
    projects.write_json(notes_path(paths, chapter_id), {"notes": notes})


def add(paths, chapter_id: str, text: str, offset: int = 0, length: int = 0) -> dict:
    notes = load(paths, chapter_id)
    item = {
        "id": uuid.uuid4().hex[:10],
        "text": (text or "").strip(),
        "offset": int(offset),
        "length": int(length),
        "status": "open",
    }
    notes.append(item)
    save(paths, chapter_id, notes)
    return item


def format_for_prompt(notes: list[dict]) -> str:
    open_notes = [n for n in notes if n.get("status") != "done" and n.get("text")]
    if not open_notes:
        return ""
    lines = ["AUTHOR MARGIN NOTES (do not treat as canon):"]
    for n in open_notes:
        lines.append(f"- {n['text']}")
    return "\n".join(lines)
