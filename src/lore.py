"""Lore book CRUD - ported from unblocker's src/lore.js.

A project's lore.json holds two lists: `characters` and `world`. Each entry is
normalized to a consistent shape so the GUI and image pipeline can rely on the
fields. JSON is kept compatible with unblocker so projects are portable.
"""

import json
import os
import uuid
from datetime import datetime, timezone

from src import lore_types


def _now():
    return datetime.now(timezone.utc).isoformat()


def _to_array(value):
    if isinstance(value, list):
        return value
    if value in (None, ""):
        return []
    if isinstance(value, str):
        return [v.strip() for v in value.split(",") if v.strip()]
    return [value]


def wrap_bracket_prompt(raw):
    s = str(raw or "").strip()
    if not s:
        return ""
    if s.startswith("[") and s.endswith("]"):
        return s
    return f"[{s.strip('[]').strip()}]"


def derive_image_prompt(entry):
    name = str(entry.get("name") or "Untitled").strip() or "Untitled"
    body = str(entry.get("appearance") or entry.get("description")
               or entry.get("notes") or "").strip()
    if not body:
        return f"[{name}]"
    return f"[{name}, {body}]"


def normalize_entry(entry, fallback_type="character"):
    entry = entry or {}
    storage_type = entry.get("type") or fallback_type
    if storage_type not in ("character", "world"):
        storage_type = "character" if storage_type == "character" else "world"
    now = _now()
    entry_type = lore_types.normalize_entry_type(
        entry.get("entryType"), storage_type)

    scope = entry.get("chapterScope")
    if isinstance(scope, dict):
        chapter_scope = {
            "mode": "chapter" if scope.get("mode") == "chapter" else "global",
            "chapterId": scope.get("chapterId"),
        }
    else:
        chapter_scope = {"mode": "global", "chapterId": None}

    keywords_src = entry.get("keywords")
    if not keywords_src:
        keywords_src = [entry.get("name")]

    notes = entry.get("notes") or entry.get("content") or entry.get("description") or ""

    rel = entry.get("relationships")
    if isinstance(rel, list):
        relationships = rel
    elif isinstance(rel, str) and rel.strip():
        relationships = lore_types.parse_relationships(rel)
    else:
        relationships = []

    return {
        "id": entry.get("id") or str(uuid.uuid4()),
        "name": entry.get("name") or "Untitled",
        "notes": notes,
        "description": entry.get("description") or notes,
        "keywords": [k for k in _to_array(keywords_src) if k],
        "type": lore_types.storage_for_entry_type(entry_type),
        "entryType": entry_type,
        "aliases": _to_array(entry.get("aliases")),
        "pronouns": entry.get("pronouns") or "",
        "role": entry.get("role") or "",
        "appearance": entry.get("appearance") or "",
        "goals": entry.get("goals") or "",
        "relationships": relationships,
        "voiceStyle": entry.get("voiceStyle") or "",
        "creatureType": entry.get("creatureType") or entry.get("species") or "",
        "chapterScope": chapter_scope,
        "tags": _to_array(entry.get("tags")),
        "timelineNotes": _to_array(entry.get("timelineNotes")),
        "portraitPath": entry.get("portraitPath"),
        "imagePaths": [p for p in (entry.get("imagePaths") or []) if p],
        "customFields": entry.get("customFields") if isinstance(
            entry.get("customFields"), dict) else {},
        "imagePrompt": wrap_bracket_prompt(entry["imagePrompt"]) if entry.get(
            "imagePrompt") else "",
        "imageNegativePrompt": entry.get("imageNegativePrompt") if isinstance(
            entry.get("imageNegativePrompt"), str) else "",
        "climate": entry.get("climate") or "",
        "inhabitants": entry.get("inhabitants") or "",
        "history": entry.get("history") or "",
        "leadership": entry.get("leadership") or "",
        "territory": entry.get("territory") or "",
        "origin": entry.get("origin") or "",
        "powers": entry.get("powers") or "",
        "when": entry.get("when") or "",
        "participants": entry.get("participants") or "",
        "outcome": entry.get("outcome") or "",
        "priority": entry.get("priority") if isinstance(
            entry.get("priority"), (int, float)) else 0,
        "pinned": bool(entry.get("pinned")),
        "alwaysInclude": bool(entry.get("alwaysInclude")),
        "createdAt": entry.get("createdAt") or now,
        "updatedAt": entry.get("updatedAt") or now,
    }


def read(lore_path):
    try:
        with open(lore_path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        characters = [normalize_entry(e, "character")
                      for e in raw.get("characters", [])]
        world = [normalize_entry(e, "world") for e in raw.get("world", [])]
        return {"characters": characters, "world": world}
    except (OSError, json.JSONDecodeError):
        return {"characters": [], "world": []}


def write(lore_path, data):
    os.makedirs(os.path.dirname(lore_path), exist_ok=True)
    with open(lore_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def add(lore_path, entry):
    data = read(lore_path)
    entry_type = lore_types.normalize_entry_type(
        entry.get("entryType"), entry.get("type") or "world")
    storage_type = lore_types.storage_for_entry_type(entry_type)
    new_entry = normalize_entry(
        {**entry, "id": str(uuid.uuid4()), "entryType": entry_type,
         "type": storage_type, "createdAt": _now(), "updatedAt": _now()},
        storage_type,
    )
    bucket = "world" if storage_type == "world" else "characters"
    data[bucket].append(new_entry)
    write(lore_path, data)
    return new_entry


def update(lore_path, entry):
    data = read(lore_path)
    for key in ("characters", "world"):
        for i, existing in enumerate(data[key]):
            if existing["id"] == entry.get("id"):
                merged = normalize_entry(
                    {**existing, **entry, "updatedAt": _now()},
                    existing.get("type") or "character",
                )
                data[key][i] = merged
                write(lore_path, data)
                return merged
    raise ValueError("Lore entry not found: " + str(entry.get("id")))


def remove(lore_path, entry_id):
    data = read(lore_path)
    data["characters"] = [e for e in data["characters"] if e["id"] != entry_id]
    data["world"] = [e for e in data["world"] if e["id"] != entry_id]
    write(lore_path, data)
    return True


def _norm_name(name):
    return (name or "").strip().lower()


def _merge_notes(old, new):
    old = (old or "").strip()
    new = (new or "").strip()
    if not new:
        return old
    if not old:
        return new
    if new == old or new in old:
        return old
    if old in new:
        return new
    seen = set()
    merged = []
    for para in old.split("\n\n") + new.split("\n\n"):
        chunk = para.strip()
        if not chunk:
            continue
        key = chunk.lower()
        if key in seen:
            continue
        seen.add(key)
        merged.append(chunk)
    return "\n\n".join(merged)


def _append_notes(old, new, source="agent"):
    old = (old or "").strip()
    new = (new or "").strip()
    if not new:
        return old
    if not old:
        return new
    src = (source or "agent").strip() or "agent"
    return old + "\n\n" + f"--- Added from {src} ---" + "\n\n" + new


def upsert(lore_path, entry, mode="merge", source="agent"):
    """Insert or merge a lore entry matched by normalized name + storage bucket."""
    entry_type = lore_types.normalize_entry_type(
        entry.get("entryType"), entry.get("type") or "world")
    storage_type = lore_types.storage_for_entry_type(entry_type)
    bucket = "world" if storage_type == "world" else "characters"
    name = (entry.get("name") or "").strip()
    if not name:
        return add(lore_path, {**entry, "entryType": entry_type})
    data = read(lore_path)
    key = _norm_name(name)
    capture_mode = mode if mode in ("empty", "append", "merge") else "merge"
    for i, existing in enumerate(data[bucket]):
        if _norm_name(existing.get("name")) != key:
            continue
        if existing.get("entryType") != entry_type and entry.get("entryType"):
            pass  # same name different type — still merge into same named row
        merged = dict(existing)
        for field in _LORE_MERGE_TEXT_FIELDS:
            new_val = (entry.get(field) or "").strip()
            old_val = (existing.get(field) or "").strip()
            if not new_val:
                continue
            if field == "notes" and capture_mode == "empty" and old_val:
                continue
            if not old_val:
                merged[field] = new_val
            elif capture_mode == "append":
                merged[field] = _append_notes(old_val, new_val, source)
            else:
                merged[field] = _merge_notes(old_val, new_val)
        for field in ("keywords", "aliases", "tags"):
            if entry.get(field):
                combined = list(dict.fromkeys(
                    _to_array(existing.get(field)) + _to_array(entry.get(field))))
                merged[field] = combined
        if entry.get("entryType"):
            merged["entryType"] = entry_type
        updated = normalize_entry({**merged, "updatedAt": _now()}, storage_type)
        data[bucket][i] = updated
        write(lore_path, data)
        return updated
    return add(lore_path, {**entry, "entryType": entry_type})


def save_entry(lore_path, entry):
    """Upsert by id; moves between characters/world buckets when entryType changes."""
    data = read(lore_path)
    eid = entry.get("id")
    normalized = normalize_entry(entry, entry.get("type") or "world")
    if not eid:
        return add(lore_path, normalized)
    bucket = "world" if normalized["type"] == "world" else "characters"
    for bkey in ("characters", "world"):
        data[bkey] = [e for e in data[bkey] if e.get("id") != eid]
    data[bucket].append(normalized)
    write(lore_path, data)
    return normalized


def all_entries(lore_path):
    data = read(lore_path)
    return data["characters"] + data["world"]


def entries_by_type(lore_path, entry_type: str | None = None):
    """All entries, optionally filtered by entryType ('all' or None = no filter)."""
    entries = all_entries(lore_path)
    if not entry_type or entry_type == "all":
        return entries
    return [e for e in entries if e.get("entryType") == entry_type]


_LORE_MERGE_TEXT_FIELDS = (
    "notes", "description", "appearance", "goals", "history", "powers",
    "origin", "climate", "inhabitants", "leadership", "territory",
    "participants", "outcome", "when", "role", "voiceStyle", "creatureType",
    "pronouns",
)
