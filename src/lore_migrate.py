"""Lore migration helpers — infer entry types and persist normalized canon."""

from __future__ import annotations

from dataclasses import dataclass, field

from src import lore, lore_types


@dataclass
class MigrateReport:
    dry_run: bool = True
    total: int = 0
    changed: int = 0
    bucket_moves: int = 0
    type_inferences: dict[str, int] = field(default_factory=dict)
    details: list[str] = field(default_factory=list)


def infer_entry_type(entry: dict) -> str:
    """Heuristic re-inference beyond coarse bucket defaults."""
    explicit = (entry.get("entryType") or "").strip().lower()
    if explicit in lore_types.ENTRY_TYPE_KEYS and explicit not in ("character", "place"):
        return explicit

    storage = entry.get("type") or "world"
    if entry.get("creatureType") or entry.get("species") or entry.get("powers"):
        if entry.get("role") or entry.get("pronouns") or entry.get("relationships"):
            return "character"
        return "creature"
    if entry.get("when") or entry.get("outcome") or entry.get("participants"):
        return "event"
    if entry.get("leadership") and entry.get("goals") and not entry.get("role"):
        return "faction"
    if entry.get("territory") or entry.get("climate") or entry.get("inhabitants"):
        return "place"
    if entry.get("history") and entry.get("appearance") and not entry.get("role"):
        if entry.get("powers") or entry.get("origin"):
            return "thing"
    if entry.get("powers") and entry.get("origin") and not entry.get("role"):
        return "thing"

    tags = " ".join(str(t) for t in (entry.get("tags") or [])).lower()
    name = (entry.get("name") or "").lower()
    notes = (entry.get("notes") or entry.get("content") or "").lower()
    blob = f"{name} {notes} {tags}"
    if any(w in blob for w in ("dragon", "beast", "monster", "creature", "demon")):
        return "creature"
    if any(w in blob for w in ("kingdom", "city", "village", "realm", "forest", "tower")):
        return "place"
    if any(w in blob for w in ("guild", "order", "clan", "army", "cult")):
        return "faction"

    if storage == "character":
        return "character"
    if explicit in lore_types.ENTRY_TYPE_KEYS:
        return explicit
    return "place"


def migrate_lore(paths, *, dry_run: bool = True) -> MigrateReport:
    """Re-infer entryType, fix buckets, optionally write lore.json."""
    report = MigrateReport(dry_run=dry_run)
    if not paths:
        return report

    book = lore.read(paths["lore"])
    raw_entries = []
    for section in ("characters", "world"):
        for e in book.get(section, []):
            raw_entries.append((section, e))

    report.total = len(raw_entries)
    new_chars = []
    new_world = []

    for section, raw in raw_entries:
        before_type = raw.get("entryType") or (
            "character" if section == "characters" else "place")
        inferred = infer_entry_type(raw)
        normalized = lore.normalize_entry({**raw, "entryType": inferred})
        after_type = normalized["entryType"]
        after_bucket = normalized["type"]

        changed = (
            before_type != after_type
            or section != after_bucket
            or raw.get("entryType") != after_type
        )
        if changed:
            report.changed += 1
            if section != after_bucket:
                report.bucket_moves += 1
            report.type_inferences[after_type] = (
                report.type_inferences.get(after_type, 0) + 1)
            name = normalized.get("name", "?")
            report.details.append(
                f"{name}: {before_type} ({section}) → {after_type} ({after_bucket})")

        if after_bucket == "characters":
            new_chars.append(normalized)
        else:
            new_world.append(normalized)

    if not dry_run:
        lore.write(paths["lore"], {"characters": new_chars, "world": new_world})

    return report


def dedupe_by_name(entries: list[dict], strategy: str = "flag") -> list[dict]:
    """Return duplicate name groups. strategy flag only — no auto-merge."""
    seen: dict[str, list[dict]] = {}
    for e in entries:
        key = (e.get("name") or "").strip().lower()
        if not key:
            continue
        seen.setdefault(key, []).append(e)
    return [group for group in seen.values() if len(group) > 1]
