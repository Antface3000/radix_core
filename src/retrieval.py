"""Naive retrieval over chapters + lore for long-book context."""

from __future__ import annotations

import re
from collections import Counter

from src import chapters, lore

_TOKEN = re.compile(r"[a-z0-9']{3,}")


def _tokens(text: str) -> list[str]:
    return _TOKEN.findall((text or "").lower())


def _score(query: Counter, doc: Counter) -> float:
    if not query or not doc:
        return 0.0
    return sum((query & doc).values()) / (sum(query.values()) or 1)


def search(paths, query: str, limit: int = 8) -> list[dict]:
    """Return scored snippets from chapters and lore."""
    q = Counter(_tokens(query))
    hits: list[dict] = []

    for ch in chapters.list_chapters(paths["chapters"]):
        data = chapters.read(paths["chapters"], ch["id"])
        body = data.get("content") or ""
        score = _score(q, Counter(_tokens(body)))
        if score <= 0:
            continue
        hits.append({
            "kind": "chapter",
            "id": ch["id"],
            "name": ch["name"],
            "score": score,
            "snippet": body.strip()[:400],
        })

    book = lore.read(paths["lore"])
    for section in ("characters", "world"):
        for entry in book.get(section) or []:
            blob = " ".join(str(v) for v in entry.values() if isinstance(v, str))
            score = _score(q, Counter(_tokens(blob)))
            if score <= 0:
                continue
            hits.append({
                "kind": "lore",
                "id": entry.get("id"),
                "name": entry.get("name"),
                "score": score,
                "snippet": (entry.get("notes") or blob)[:400],
            })

    hits.sort(key=lambda h: h["score"], reverse=True)
    return hits[:limit]


def previously_from_retrieval(paths, query: str, max_chars: int = 1600) -> str:
    parts = []
    used = 0
    for hit in search(paths, query, limit=12):
        line = f"[{hit['kind']}:{hit.get('name', '?')}] {hit['snippet']}"
        if used + len(line) > max_chars and parts:
            break
        parts.append(line)
        used += len(line)
    return "\n\n".join(parts)
