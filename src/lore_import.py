"""Import lore entries from Sudowrite (and similar) character CSVs."""

from __future__ import annotations

import csv
import io
import os

from src import lore, lore_types

# Sudowrite Story Bible → Radix character fields
_HEADER_MAP = {
    "name": "name",
    "role": "role",
    "pronouns": "pronouns",
    "groups": "groups",
    "group": "groups",
    "other names": "aliases",
    "othernames": "aliases",
    "aliases": "aliases",
    "personality": "personality",
    "physical description": "appearance",
    "physicaldescription": "appearance",
    "appearance": "appearance",
    "dialogue style": "voiceStyle",
    "dialoguestyle": "voiceStyle",
    "dialogue": "voiceStyle",
    "voice": "voiceStyle",
    "voicestyle": "voiceStyle",
    "notes": "notes",
    "goals": "goals",
    "keywords": "keywords",
    "tags": "tags",
}


def _norm_header(raw: str) -> str:
    return " ".join((raw or "").strip().lower().replace("_", " ").split())


def _map_header(raw: str) -> str | None:
    key = _norm_header(raw)
    if key in _HEADER_MAP:
        return _HEADER_MAP[key]
    compact = key.replace(" ", "")
    return lore_types.FIELD_ALIASES.get(compact) or _HEADER_MAP.get(compact)


def _split_list(val: str) -> list[str]:
    """Split comma lists without breaking quoted nicknames."""
    parts: list[str] = []
    current: list[str] = []
    in_quotes = False
    for ch in val or "":
        if ch == '"':
            in_quotes = not in_quotes
            continue
        if ch == "," and not in_quotes:
            piece = "".join(current).strip()
            if piece:
                parts.append(piece)
            current = []
            continue
        current.append(ch)
    piece = "".join(current).strip()
    if piece:
        parts.append(piece)
    return parts


def _overlay_character(existing: dict, incoming: dict) -> dict:
    """Fill a lore person from a Sudowrite row without globbing short labels."""
    out = dict(existing)
    list_keys = ("aliases", "groups", "keywords", "tags")
    replace_keys = ("personality", "appearance", "voiceStyle", "notes")
    fill_keys = ("role", "pronouns")
    for key, val in incoming.items():
        if key in ("id", "name", "entryType", "type"):
            continue
        if key in list_keys:
            if not val:
                continue
            out[key] = list(dict.fromkeys(
                list(out.get(key) or []) + list(val)))
        elif key in replace_keys:
            if str(val or "").strip():
                out[key] = val
        elif key in fill_keys:
            if str(val or "").strip() and not str(out.get(key) or "").strip():
                out[key] = val
        elif val not in (None, "", []):
            if not out.get(key):
                out[key] = val
    return out


def parse_character_csv(text: str) -> list[dict]:
    """Parse a Sudowrite-style character CSV into lore entry dicts."""
    sample = (text or "").lstrip("\ufeff")
    if not sample.strip():
        return []
    reader = csv.DictReader(io.StringIO(sample))
    if not reader.fieldnames:
        return []
    colmap: dict[str, str] = {}
    for header in reader.fieldnames:
        dest = _map_header(header)
        if dest:
            colmap[header] = dest

    out: list[dict] = []
    for row in reader:
        entry: dict = {"entryType": "character"}
        for header, dest in colmap.items():
            val = (row.get(header) or "").strip().strip('"')
            if not val:
                continue
            if dest in ("aliases", "groups", "keywords", "tags"):
                entry[dest] = _split_list(val)
            else:
                entry[dest] = val
        name = (entry.get("name") or "").strip()
        if not name:
            continue
        kws = list(entry.get("keywords") or [])
        if name not in kws:
            kws.insert(0, name)
        for alias in entry.get("aliases") or []:
            if alias not in kws:
                kws.append(alias)
        entry["keywords"] = kws
        out.append(entry)
    return out


def import_character_csv(
    lore_path: str,
    path_or_text: str,
    *,
    mode: str = "upsert",
) -> dict:
    """Import a CSV file (or raw CSV text) into lore.json. mode: add | upsert."""
    if os.path.isfile(path_or_text):
        with open(path_or_text, "r", encoding="utf-8-sig") as fh:
            text = fh.read()
    else:
        text = path_or_text
    rows = parse_character_csv(text)
    added = 0
    updated = 0
    for entry in rows:
        if mode == "add":
            lore.add(lore_path, entry)
            added += 1
            continue
        book = lore.read(lore_path)
        name_key = (entry.get("name") or "").strip().lower()
        existed = None
        for e in book.get("characters", []):
            if (e.get("name") or "").strip().lower() == name_key:
                existed = e
                break
        if existed is None:
            lore.add(lore_path, entry)
            added += 1
        else:
            merged = _overlay_character(existed, entry)
            lore.save_entry(lore_path, merged)
            updated += 1
    return {"added": added, "updated": updated, "total": len(rows)}
