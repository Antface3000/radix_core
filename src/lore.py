"""Lore book CRUD - ported from unblocker's src/lore.js.

A project's lore.json holds two lists: `characters` and `world`. Each entry is
normalized to a consistent shape so the GUI and image pipeline can rely on the
fields. JSON is kept compatible with unblocker so projects are portable.
"""

import json
import os
import uuid
from datetime import datetime, timezone


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
    entry_type = entry.get("type") or fallback_type
    now = _now()
    sub_entry_type = entry.get("entryType") or (
        "world" if entry_type == "world" else "character")

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

    return {
        "id": entry.get("id") or str(uuid.uuid4()),
        "name": entry.get("name") or "Untitled",
        "notes": entry.get("notes") or "",
        "keywords": [k for k in _to_array(keywords_src) if k],
        "type": entry_type,
        "entryType": sub_entry_type,
        "aliases": _to_array(entry.get("aliases")),
        "pronouns": entry.get("pronouns") or "",
        "appearance": entry.get("appearance") or "",
        "goals": entry.get("goals") or "",
        "relationships": entry.get("relationships") if isinstance(
            entry.get("relationships"), list) else [],
        "voiceStyle": entry.get("voiceStyle") or "",
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
        # World-entry fields.
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
    storage_type = entry.get("type") or (
        "character" if entry.get("entryType") == "character" else "world")
    new_entry = normalize_entry(
        {**entry, "id": str(uuid.uuid4()), "type": storage_type,
         "createdAt": _now(), "updatedAt": _now()},
        storage_type,
    )
    if storage_type == "world":
        data["world"].append(new_entry)
    else:
        data["characters"].append(new_entry)
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
    """Insert or merge a lore entry matched by normalized name + type."""
    storage_type = entry.get("type") or (
        "character" if entry.get("entryType") == "character" else "world")
    bucket = "world" if storage_type == "world" else "characters"
    name = (entry.get("name") or "").strip()
    if not name:
        return add(lore_path, entry)
    data = read(lore_path)
    key = _norm_name(name)
    capture_mode = mode if mode in ("empty", "append", "merge") else "merge"
    for i, existing in enumerate(data[bucket]):
        if _norm_name(existing.get("name")) != key:
            continue
        old_notes = (existing.get("notes") or "").strip()
        new_notes = (entry.get("notes") or "").strip()
        if capture_mode == "empty" and old_notes:
            return existing
        merged = dict(existing)
        for field in ("notes", "appearance", "goals"):
            new_val = (entry.get(field) or "").strip()
            old_val = (existing.get(field) or "").strip()
            if not new_val:
                continue
            if field == "notes":
                if not old_val:
                    merged[field] = new_val
                elif capture_mode == "append":
                    merged[field] = _append_notes(old_val, new_val, source)
                else:
                    merged[field] = _merge_notes(old_val, new_val)
            elif new_val != old_val:
                if not old_val:
                    merged[field] = new_val
                elif capture_mode == "append":
                    merged[field] = _append_notes(old_val, new_val, source)
                else:
                    merged[field] = _merge_notes(old_val, new_val)
        for field in ("keywords", "aliases"):
            if entry.get(field):
                combined = list(dict.fromkeys(
                    _to_array(existing.get(field)) + _to_array(entry.get(field))))
                merged[field] = combined
        updated = normalize_entry({**merged, "updatedAt": _now()}, storage_type)
        data[bucket][i] = updated
        write(lore_path, data)
        return updated
    return add(lore_path, entry)


def all_entries(lore_path):
    data = read(lore_path)
    return data["characters"] + data["world"]
