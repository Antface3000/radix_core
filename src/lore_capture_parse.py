"""Parse structured agent capture blocks into lore entry fields."""

from __future__ import annotations

import re

from src import lore_types

_FIELD_LINE_RE = re.compile(
    r"^([A-Za-z][A-Za-z0-9 _/-]*)\s*:\s*(.*)$",
)


def _allowed_field_keys(entry_type: str) -> set[str]:
    keys = {key for key, _, _ in lore_types.fields_for_entry_type(entry_type)}
    keys.add("description")
    return keys


def _resolve_field_key(raw: str, allowed: set[str]) -> str | None:
    key = (raw or "").strip().lower().replace(" ", "").replace("-", "").replace("_", "")
    if not key:
        return None
    canonical = lore_types.FIELD_ALIASES.get(key, raw.strip())
    # Normalize camelCase keys from alias map values
    if canonical in allowed:
        return canonical
    # Try direct match on allowed keys (case-insensitive)
    for ak in allowed:
        if ak.lower().replace("_", "") == key:
            return ak
    return None


def _multiline_keys(entry_type: str) -> set[str]:
    return {key for key, _, multi in lore_types.fields_for_entry_type(entry_type) if multi}


def _assign_field(entry: dict, key: str, value: str) -> None:
    val = (value or "").strip()
    if not val:
        return
    if key in ("keywords", "aliases", "tags"):
        parts = [v.strip() for v in val.split(",") if v.strip()]
        existing = list(entry.get(key) or [])
        entry[key] = list(dict.fromkeys(existing + parts))
    elif key in entry and entry[key]:
        old = str(entry[key]).strip()
        if val not in old:
            entry[key] = old + "\n\n" + val
    else:
        entry[key] = val


def _try_field_segment(segment: str, allowed: set[str]) -> tuple[str | None, str]:
    segment = segment.strip()
    match = _FIELD_LINE_RE.match(segment)
    if not match:
        return None, segment
    key = _resolve_field_key(match.group(1), allowed)
    if not key:
        return None, segment
    return key, match.group(2).strip()


def parse_capture_block(block: str, entry_type: str, name: str) -> dict:
    """Turn a capture body into lore field dict (may include notes)."""
    text = (block or "").strip()
    if not text:
        return {"notes": ""}

    et = lore_types.normalize_entry_type(entry_type)
    allowed = _allowed_field_keys(et)
    multi = _multiline_keys(et)

    lines = text.splitlines()
    if lines and lines[0].strip().lower() == (name or "").strip().lower():
        lines = lines[1:]

    entry: dict = {}
    notes_lines: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i].rstrip()
        stripped = line.strip()
        if not stripped:
            i += 1
            continue

        if "|" in stripped and ":" in stripped:
            segments = [s.strip() for s in stripped.split("|") if s.strip()]
            field_hits = 0
            for seg in segments:
                fkey, fval = _try_field_segment(seg, allowed)
                if fkey:
                    _assign_field(entry, fkey, fval)
                    field_hits += 1
            if field_hits:
                i += 1
                continue

        fkey, fval = _try_field_segment(stripped, allowed)
        if fkey:
            if fkey in multi:
                buf = [fval] if fval else []
                i += 1
                while i < len(lines):
                    nxt_raw = lines[i]
                    nxt = nxt_raw.strip()
                    if not nxt:
                        i += 1
                        break
                    nk, _ = _try_field_segment(nxt, allowed)
                    if nk:
                        break
                    # Continuation lines must be indented or bullet lists.
                    if nxt_raw.startswith((" ", "\t")) or nxt.startswith("- "):
                        buf.append(nxt_raw.rstrip())
                        i += 1
                    else:
                        break
                _assign_field(entry, fkey, "\n".join(buf).strip())
            else:
                _assign_field(entry, fkey, fval)
                i += 1
            continue

        notes_lines.append(stripped)
        i += 1

    prose = "\n".join(notes_lines).strip()
    if prose:
        if entry.get("notes"):
            entry["notes"] = str(entry["notes"]).strip() + "\n\n" + prose
        else:
            entry["notes"] = prose

    if not entry:
        entry["notes"] = text

    return entry


def build_capture_entry(
    block: str,
    entry_type: str,
    name: str,
    storage: str,
) -> dict:
    """Full lore upsert payload from a validated capture block."""
    parsed = parse_capture_block(block, entry_type, name)
    keywords = parsed.pop("keywords", None) or [name]
    if name not in keywords:
        keywords = [name] + [k for k in keywords if k != name]
    return {
        "type": storage,
        "entryType": entry_type,
        "name": name,
        "keywords": keywords,
        **parsed,
    }
