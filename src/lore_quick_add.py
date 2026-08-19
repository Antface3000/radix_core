"""Parse bulk Quick Add lore lines into entry dicts."""

from __future__ import annotations

from src import lore_types


def parse_quick_add_lines(text: str, default_type: str = "character") -> list[dict]:
    """Return one entry dict per non-empty, non-comment line."""
    default = lore_types.normalize_entry_type(default_type, "character")
    out: list[dict] = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parsed = _parse_line(line, default)
        if parsed:
            out.append(parsed)
    return out


def _parse_line(line: str, default_type: str) -> dict | None:
    entry_type = default_type
    body = line

    if ":" in line:
        prefix, rest = line.split(":", 1)
        prefix_key = prefix.strip().lower()
        if prefix_key in lore_types.QUICK_ADD_PREFIXES:
            entry_type = lore_types.QUICK_ADD_PREFIXES[prefix_key]
            body = rest.strip()
            if not body:
                return None

    if "|" in body:
        parts = [p.strip() for p in body.split("|") if p.strip()]
        if not parts:
            return None
        name_part = parts[0]
        field_parts = parts[1:]
    else:
        if ":" in body:
            name_part, notes = body.split(":", 1)
            name_part = name_part.strip()
            field_parts = [f"notes: {notes.strip()}"] if notes.strip() else []
        else:
            name_part = body.strip()
            field_parts = []

    if not name_part:
        return None

    entry: dict = {
        "name": name_part,
        "entryType": entry_type,
        "keywords": [name_part],
    }
    for seg in field_parts:
        if ":" not in seg:
            if not entry.get("notes"):
                entry["notes"] = seg
            continue
        fk, fv = seg.split(":", 1)
        key = lore_types.FIELD_ALIASES.get(fk.strip().lower(), fk.strip())
        val = fv.strip()
        if key in ("keywords", "aliases", "tags"):
            entry[key] = [v.strip() for v in val.split(",") if v.strip()]
        else:
            entry[key] = val
    return entry


def apply_quick_add(
    lore_path,
    text: str,
    *,
    default_type: str = "character",
    mode: str = "add",
    capture_mode: str = "empty",
) -> dict:
    """Bulk import lines. mode: add | upsert. Returns summary counts."""
    from src import lore

    lines = parse_quick_add_lines(text, default_type)
    added = 0
    updated = 0
    skipped = 0
    for entry in lines:
        if mode == "upsert":
            book = lore.read(lore_path)
            et = lore_types.normalize_entry_type(
                entry.get("entryType"), entry.get("type") or "world")
            bucket = "characters" if lore_types.storage_for_entry_type(et) == "character" else "world"
            name_key = (entry.get("name") or "").strip().lower()
            existed = any(
                (e.get("name") or "").strip().lower() == name_key
                for e in book.get(bucket, []))
            if existed:
                lore.upsert(lore_path, entry, mode=capture_mode, source="quick_add")
                updated += 1
            else:
                lore.upsert(lore_path, entry, mode=capture_mode, source="quick_add")
                added += 1
        else:
            lore.add(lore_path, entry)
            added += 1
    return {"added": added, "updated": updated, "skipped": skipped, "total": len(lines)}
