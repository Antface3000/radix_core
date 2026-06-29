"""worldcontext - the genre-decoupling core.

Assembles the runtime "SETTING" system block for the active project from three
sources, so the personas themselves stay genre-agnostic:

    story_bible.json  -> premise / genre / tone / themes / world rules / style
    lore.json         -> entries flagged alwaysInclude or pinned (the canon)
    world_state.json  -> the current mutable situation (timeline, factions...)

Also handles the reverse direction: capturing [[REMEMBER]] / category-marked
blocks an agent emits and filing them as lore.json entries.
"""

import re

from src import story_bible, world_state, lore

# Shared bible field order (single source of truth for agent + editor context).
BIBLE_FIELD_ORDER = (
    ("Premise", "premise"),
    ("Logline", "logline"),
    ("Genre & Tone", "genreTone"),
    ("Point of View", "pointOfView"),
    ("Tense", "tense"),
    ("World Rules", "worldRules"),
    ("Style Notes", "styleNotes"),
    ("Synopsis", "synopsis"),
)

# Marker tag -> lore entry kind. The generic REMEMBER routes to the persona's
# own capture_kind (handled in engine).
CAPTURE_MARKERS = {
    "CHARACTER": "character",
    "NPC": "character",
    "WORLD": "world",
    "CREATURE": "world",
    "LORE": "world",
    "QUEST": "world",
}
GENERIC_MARKER = "REMEMBER"


def _marker_regex(marker):
    m = re.escape(marker)
    return re.compile(rf"\[\[{m}\]\](.*?)\[\[/{m}\]\]", re.DOTALL | re.IGNORECASE)


_MARKER_RES = {tag: _marker_regex(tag) for tag in CAPTURE_MARKERS}
_GENERIC_RE = _marker_regex(GENERIC_MARKER)


def _bullet_list(items, limit=12):
    out = []
    for item in items[:limit]:
        if isinstance(item, dict):
            label = item.get("name") or item.get("title") or item.get("text") or ""
            detail = item.get("notes") or item.get("status") or item.get("summary") or ""
            line = label if not detail else f"{label}: {detail}"
        else:
            line = str(item)
        line = line.strip()
        if line:
            out.append(f"- {line}")
    return "\n".join(out)


def format_bible(bible, max_chars=None):
    """Format story bible dict as labeled lines."""
    parts = []
    for label, key in BIBLE_FIELD_ORDER:
        if key == "themes":
            continue
        val = bible.get(key)
        val = (val or "").strip() if isinstance(val, str) else val
        if val:
            parts.append(f"{label}: {val}")
    if bible.get("themes"):
        themes = bible["themes"]
        parts.append("Themes: " + (", ".join(themes) if isinstance(themes, list) else str(themes)))
    text = "\n".join(parts)
    if max_chars and len(text) > max_chars:
        text = text[:max_chars] + "\n...(bible trimmed)..."
    return text


def _pinned_lore(book):
    canon = [e for e in (book["characters"] + book["world"])
             if e.get("alwaysInclude") or e.get("pinned")]
    canon.sort(key=lambda e: (not e.get("alwaysInclude"), -(e.get("priority") or 0)))
    return canon


def summarize_injection(paths):
    """Short summary for UI: char count, filled bible labels, pinned lore count."""
    if not paths:
        return {"chars": 0, "labels": [], "pinned_lore": 0, "empty": True}
    bible = story_bible.read(paths["bible"])
    book = lore.read(paths["lore"])
    labels = []
    for label, key in BIBLE_FIELD_ORDER:
        val = bible.get(key)
        if isinstance(val, str) and val.strip():
            labels.append(label)
    if bible.get("themes"):
        labels.append("Themes")
    pinned = len(_pinned_lore(book))
    text = assemble(paths, max_chars=None)
    empty = len(labels) == 0 and pinned == 0 and "No setting configured" in text
    return {
        "chars": len(text),
        "labels": labels,
        "pinned_lore": pinned,
        "empty": empty,
    }


def assemble(paths, max_chars=6000, exclude_bible_keys=None):
    """Build the SETTING system block for the project at `paths`."""
    bible = story_bible.read(paths["bible"])
    if exclude_bible_keys:
        bible = {**bible, **{k: "" for k in exclude_bible_keys}}
    world = world_state.read(paths["world_state"])
    book = lore.read(paths["lore"])

    parts = ["=== SETTING (established canon - treat as ground truth) ==="]

    bible_text = format_bible(bible)
    if bible_text:
        parts.append(bible_text)

    canon = _pinned_lore(book)
    if canon:
        parts.append("\n--- KEY LORE ---")
        for e in canon[:20]:
            body = (e.get("appearance") or e.get("notes")
                    or e.get("history") or "").strip()
            kind = "Character" if e.get("type") == "character" else "World"
            line = f"- [{kind}] {e.get('name')}"
            if body:
                line += f": {body}"
            parts.append(line)

    ws_lines = []
    if world.get("currentDate"):
        ws_lines.append(f"- Current date: {world['currentDate']}")
    if world.get("currentLocation"):
        ws_lines.append(f"- Current location: {world['currentLocation']}")
    for label, key in (("Timeline", "timeline"), ("Factions", "factions"),
                       ("Ongoing events", "ongoingEvents"), ("Facts", "facts")):
        block = _bullet_list(world.get(key, []))
        if block:
            ws_lines.append(f"{label}:\n{block}")
    if ws_lines:
        parts.append("\n--- CURRENT WORLD STATE ---")
        parts.append("\n".join(ws_lines))

    text = "\n".join(parts).strip()
    if len(parts) == 1:
        text += "\n(No setting configured yet. Use the Story Bible panel to "
        text += "define the world.)"
    if max_chars and len(text) > max_chars:
        text = text[:max_chars] + "\n...(setting trimmed)..."
    return text


def _name_from_block(block):
    """Derive an entry name from a captured block's first line/sentence."""
    first = block.strip().splitlines()[0].strip() if block.strip() else "Note"
    if ":" in first and len(first.split(":", 1)[0]) <= 60:
        first = first.split(":", 1)[0]
    first = re.sub(r"^[#*\-\s]+", "", first)
    return (first[:60] or "Note").strip()


def capture_to_lore(paths, raw_text, default_kind="world", source="agent"):
    """Extract tagged blocks from `raw_text` and append them to lore.json."""
    if not raw_text:
        return []
    created = []

    for tag, kind in CAPTURE_MARKERS.items():
        for match in _MARKER_RES[tag].finditer(raw_text):
            block = match.group(1).strip()
            if not block:
                continue
            entry = lore.add(paths["lore"], {
                "type": kind,
                "name": _name_from_block(block),
                "notes": block,
                "keywords": [_name_from_block(block)],
            })
            created.append(entry)

    if default_kind:
        for match in _GENERIC_RE.finditer(raw_text):
            block = match.group(1).strip()
            if not block:
                continue
            entry = lore.add(paths["lore"], {
                "type": default_kind,
                "name": _name_from_block(block),
                "notes": block,
                "keywords": [_name_from_block(block)],
            })
            created.append(entry)

    return created
