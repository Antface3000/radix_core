"""Project-wide search/replace across chapters, lore, and story bible."""

from __future__ import annotations

import json
import re

from src import chapters, lore, projects, story_bible


def _iter_chapter_hits(paths, pattern: re.Pattern) -> list[dict]:
    hits = []
    for ch in chapters.list_chapters(paths["chapters"]):
        data = chapters.read(paths["chapters"], ch["id"])
        text = data.get("content") or ""
        for m in pattern.finditer(text):
            start = max(0, m.start() - 40)
            end = min(len(text), m.end() + 40)
            hits.append({
                "kind": "chapter",
                "id": ch["id"],
                "name": ch["name"],
                "offset": m.start(),
                "match": m.group(),
                "snippet": text[start:end].replace("\n", " "),
            })
    return hits


def _walk_strings(obj, path=""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _walk_strings(v, f"{path}.{k}" if path else k)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _walk_strings(v, f"{path}[{i}]")
    elif isinstance(obj, str):
        yield path, obj


def search(paths, query: str, *, case: bool = False, regex: bool = False) -> list[dict]:
    if not query:
        return []
    flags = 0 if case else re.IGNORECASE
    pattern = re.compile(query if regex else re.escape(query), flags)
    hits = _iter_chapter_hits(paths, pattern)

    book = lore.read(paths["lore"])
    for section in ("characters", "world"):
        for entry in book.get(section) or []:
            for field, text in _walk_strings(entry):
                for m in pattern.finditer(text):
                    hits.append({
                        "kind": "lore",
                        "id": entry.get("id"),
                        "name": entry.get("name"),
                        "field": field,
                        "offset": m.start(),
                        "match": m.group(),
                        "snippet": text[max(0, m.start() - 40):m.end() + 40],
                    })

    bible = story_bible.read(paths["bible"])
    for field, text in _walk_strings(bible):
        if not isinstance(text, str):
            continue
        for m in pattern.finditer(text):
            hits.append({
                "kind": "bible",
                "id": field,
                "name": field,
                "field": field,
                "offset": m.start(),
                "match": m.group(),
                "snippet": text[max(0, m.start() - 40):m.end() + 40],
            })
    return hits


def replace_in_chapters(paths, query: str, replacement: str, *,
                        case: bool = False, regex: bool = False) -> int:
    if not query:
        return 0
    flags = 0 if case else re.IGNORECASE
    pattern = re.compile(query if regex else re.escape(query), flags)
    count = 0
    for ch in chapters.list_chapters(paths["chapters"]):
        data = chapters.read(paths["chapters"], ch["id"])
        text = data.get("content") or ""
        new, n = pattern.subn(replacement, text)
        if n:
            chapters.write(paths["chapters"], ch["id"], new)
            count += n
    return count
