"""Lorebook entry types and field metadata for UI + capture."""

from __future__ import annotations

# (entryType key, display label, JSON storage bucket)
ENTRY_TYPES: tuple[tuple[str, str, str], ...] = (
    ("character", "Person", "characters"),
    ("creature", "Creature", "characters"),
    ("place", "Place", "world"),
    ("thing", "Thing / Object", "world"),
    ("faction", "Faction / Group", "world"),
    ("event", "Event", "world"),
    ("concept", "Concept / Idea", "world"),
)

ENTRY_TYPE_KEYS = {t[0] for t in ENTRY_TYPES}
ENTRY_TYPE_LABELS = {k: label for k, label, _ in ENTRY_TYPES}
STORAGE_BUCKET = {k: bucket for k, _, bucket in ENTRY_TYPES}

FILTER_OPTIONS: tuple[tuple[str, str], ...] = (
    ("all", "All entries"),
    ("character", "People"),
    ("creature", "Creatures"),
    ("place", "Places"),
    ("thing", "Things / Objects"),
    ("faction", "Factions"),
    ("event", "Events"),
    ("concept", "Concepts"),
)

# Fields shown in the lore editor per entry type (widget key -> label, multiline)
FIELD_SPECS: dict[str, tuple[tuple[str, str, bool], ...]] = {
    "_common": (
        ("keywords", "Keywords (comma-separated)", False),
        ("aliases", "Aliases (comma-separated)", False),
        ("tags", "Tags (comma-separated)", False),
        ("portraitPath", "Portrait image path", False),
        ("notes", "Notes / summary", True),
    ),
    "character": (
        ("role", "Role in story", False),
        ("pronouns", "Pronouns", False),
        ("appearance", "Appearance", True),
        ("goals", "Goals & motivations", True),
        ("relationships", "Relationships", True),
        ("voiceStyle", "Voice / speech style", False),
    ),
    "creature": (
        ("creatureType", "Creature type (species, class, taxonomy)", False),
        ("appearance", "Appearance", True),
        ("powers", "Abilities / powers", True),
        ("origin", "Origin / habitat", True),
        ("notes", "Behavior & lore", True),
    ),
    "place": (
        ("territory", "Region / territory", False),
        ("climate", "Climate & atmosphere", False),
        ("inhabitants", "Inhabitants", True),
        ("history", "History", True),
        ("leadership", "Ruler / governance", False),
    ),
    "thing": (
        ("origin", "Origin / maker", False),
        ("powers", "Properties / powers", True),
        ("appearance", "Physical description", True),
        ("history", "History & provenance", True),
    ),
    "faction": (
        ("leadership", "Leadership", False),
        ("territory", "Territory / base", False),
        ("goals", "Goals & agenda", True),
        ("history", "History", True),
    ),
    "event": (
        ("when", "When (date / era)", False),
        ("participants", "Participants", True),
        ("outcome", "Outcome / consequences", True),
    ),
    "concept": (
        ("notes", "Explanation", True),
    ),
}

# Capture tag -> (storage type, entryType)
CAPTURE_TAG_ENTRY: dict[str, tuple[str, str]] = {
    "CHARACTER": ("character", "character"),
    "NPC": ("character", "character"),
    "CREATURE": ("character", "creature"),
    "PLACE": ("world", "place"),
    "WORLD": ("world", "place"),
    "THING": ("world", "thing"),
    "ITEM": ("world", "thing"),
    "OBJECT": ("world", "thing"),
    "FACTION": ("world", "faction"),
    "EVENT": ("world", "event"),
    "LORE": ("world", "concept"),
    "QUEST": ("world", "event"),
    "SPECIES": ("character", "creature"),
}


def normalize_entry_type(raw, storage_type: str = "world") -> str:
    key = (raw or "").strip().lower()
    if key in ENTRY_TYPE_KEYS:
        return key
    if storage_type == "character":
        return "character"
    return "place"


def storage_for_entry_type(entry_type: str) -> str:
    return STORAGE_BUCKET.get(entry_type, "world")


# Quick-add line prefix -> entryType (case-insensitive, trailing colon required)
QUICK_ADD_PREFIXES: dict[str, str] = {
    "person": "character",
    "character": "character",
    "char": "character",
    "creature": "creature",
    "monster": "creature",
    "place": "place",
    "world": "place",
    "thing": "thing",
    "item": "thing",
    "object": "thing",
    "faction": "faction",
    "group": "faction",
    "event": "event",
    "quest": "event",
    "concept": "concept",
    "lore": "concept",
}

# Pipe-segment field aliases in quick-add micro-syntax
FIELD_ALIASES: dict[str, str] = {
    "type": "creatureType",
    "species": "creatureType",
    "creaturetype": "creatureType",
    "notes": "notes",
    "summary": "notes",
    "desc": "description",
    "description": "description",
    "role": "role",
    "appearance": "appearance",
    "goals": "goals",
    "powers": "powers",
    "origin": "origin",
    "territory": "territory",
    "climate": "climate",
    "history": "history",
    "leadership": "leadership",
    "when": "when",
    "outcome": "outcome",
    "participants": "participants",
    "tags": "tags",
    "keywords": "keywords",
    "aliases": "aliases",
    "pronouns": "pronouns",
    "relationships": "relationships",
    "relationship": "relationships",
    "voice": "voiceStyle",
    "voicestyle": "voiceStyle",
}


def fields_for_entry_type(entry_type: str) -> list[tuple[str, str, bool]]:
    """Return ordered (key, label, multiline) fields for the editor."""
    et = normalize_entry_type(entry_type)
    seen = set()
    out: list[tuple[str, str, bool]] = []
    for key, label, multi in FIELD_SPECS.get("_common", ()):
        if key == "notes" and et in FIELD_SPECS and any(
                f[0] == "notes" for f in FIELD_SPECS[et]):
            continue
        if key not in seen:
            seen.add(key)
            out.append((key, label, multi))
    for key, label, multi in FIELD_SPECS.get(et, ()):
        if key not in seen:
            seen.add(key)
            out.append((key, label, multi))
    return out


def format_relationships(value) -> str:
    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, dict):
                who = item.get("who") or item.get("name") or "?"
                rel = item.get("relation") or item.get("type") or ""
                parts.append(f"{who}: {rel}".strip(": "))
            else:
                parts.append(str(item))
        return "\n".join(parts)
    return str(value or "")


def parse_relationships(text: str) -> list:
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    out = []
    for ln in lines:
        if ":" in ln:
            who, rel = ln.split(":", 1)
            out.append({"who": who.strip(), "relation": rel.strip()})
        else:
            out.append({"who": ln, "relation": ""})
    return out


def entry_display_name(entry) -> str:
    name = entry.get("name") or "Untitled"
    et = entry.get("entryType") or entry.get("type") or "?"
    label = ENTRY_TYPE_LABELS.get(et, et.title())
    return f"{name}  [{label}]"
