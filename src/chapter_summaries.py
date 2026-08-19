"""Rolling per-chapter summaries powering the PREVIOUSLY context section.

Stored per project in chapter_summaries.json:
    {"<chapterId>": {"summary": "...", "updatedAt": iso, "sourceChars": 1234}}

These are generated recaps (via the Session Summarizer), separate from the
user-authored outline summaries in outlines.json.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from src import chapters


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_all(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _write(path: str, data: dict) -> None:
    parent = os.path.dirname(path)
    if parent and not os.path.exists(parent):
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)


def get(path: str, chapter_id: str) -> dict | None:
    return read_all(path).get(chapter_id)


def set_summary(path: str, chapter_id: str, summary: str,
                source_chars: int = 0) -> None:
    data = read_all(path)
    data[chapter_id] = {
        "summary": (summary or "").strip(),
        "updatedAt": _now(),
        "sourceChars": int(source_chars),
    }
    _write(path, data)


def remove(path: str, chapter_id: str) -> None:
    data = read_all(path)
    if chapter_id in data:
        del data[chapter_id]
        _write(path, data)


def is_stale(entry: dict | None, current_chars: int,
             threshold: float = 0.15) -> bool:
    """True when the chapter has grown/shrunk noticeably since the summary."""
    if not entry or not entry.get("summary"):
        return False
    src = int(entry.get("sourceChars") or 0)
    if src <= 0:
        return current_chars > 400
    return abs(current_chars - src) / max(src, 1) > threshold


def previously_block(paths: dict, chapter_id: str | None,
                     max_chars: int = 1200) -> str:
    """Summaries of chapters *before* the current one, most recent last.

    When the budget is tight, nearest previous chapters win.
    """
    if not chapter_id:
        return ""
    data = read_all(paths["chapter_summaries"])
    if not data:
        return ""
    ordered = chapters.list_chapters(paths["chapters"])
    ids = [c["id"] for c in ordered]
    if chapter_id not in ids:
        return ""
    names = {c["id"]: c["name"] for c in ordered}
    prior = ids[:ids.index(chapter_id)]

    lines: list[str] = []
    used = 0
    for cid in reversed(prior):
        entry = data.get(cid)
        summary = (entry or {}).get("summary", "").strip()
        if not summary:
            continue
        line = f"[{names.get(cid, cid)}] {summary}"
        if used + len(line) > max_chars and lines:
            break
        lines.insert(0, line)
        used += len(line)
    return "\n".join(lines)
