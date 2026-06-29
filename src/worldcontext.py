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


def assemble(paths, max_chars=6000):
    """Build the SETTING system block for the project at `paths`."""
    bible = story_bible.read(paths["bible"])
    world = world_state.read(paths["world_state"])
    book = lore.read(paths["lore"])

    parts = ["=== SETTING (established canon - treat as ground truth) ==="]

    def add(label, value):
        value = (value or "").strip() if isinstance(value, str) else value
        if value:
            parts.append(f"{label}: {value}")

    add("Premise", bible.get("premise"))
    add("Logline", bible.get("logline"))
    add("Genre & Tone", bible.get("genreTone"))
    if bible.get("themes"):
        add("Themes", ", ".join(bible["themes"]))
    add("Point of View", bible.get("pointOfView"))
    add("Tense", bible.get("tense"))
    add("World Rules", bible.get("worldRules"))
    add("Style Notes", bible.get("styleNotes"))

    # Pinned / always-include lore.
    canon = [e for e in (book["characters"] + book["world"])
             if e.get("alwaysInclude") or e.get("pinned")]
    canon.sort(key=lambda e: (not e.get("alwaysInclude"),
                              -(e.get("priority") or 0)))
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

    # Current world state.
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
        # Nothing configured yet - keep agents generic but honest.
        text += "\n(No setting configured yet. Use the Story Bible panel to "
        text += "define the world.)"
    if max_chars and len(text) > max_chars:
        text = text[:max_chars] + "\n...(setting trimmed)..."
    return text


def _name_from_block(block):
    """Derive an entry name from a captured block's first line/sentence."""
    first = block.strip().splitlines()[0].strip() if block.strip() else "Note"
    # If "Name: details" form, take the name part.
    if ":" in first and len(first.split(":", 1)[0]) <= 60:
        first = first.split(":", 1)[0]
    first = re.sub(r"^[#*\-\s]+", "", first)
    return (first[:60] or "Note").strip()


def capture_to_lore(paths, raw_text, default_kind="world", source="agent"):
    """Extract tagged blocks from `raw_text` and append them to lore.json.

    Category markers ([[CHARACTER]], [[WORLD]], ...) set the kind; the generic
    [[REMEMBER]] marker uses `default_kind` (the persona's capture_kind).
    Returns the list of created entry dicts.
    """
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

    if default_kind:  # generic REMEMBER -> persona's home kind
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
