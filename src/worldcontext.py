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

BIBLE_KEYS = {key for _label, key in BIBLE_FIELD_ORDER} | {"themes"}
BIBLE_ALIASES = {
    "premise": "premise",
    "logline": "logline",
    "genretone": "genreTone",
    "genre": "genreTone",
    "genre_tone": "genreTone",
    "pov": "pointOfView",
    "pointofview": "pointOfView",
    "tense": "tense",
    "worldrules": "worldRules",
    "world_rules": "worldRules",
    "stylenotes": "styleNotes",
    "style_notes": "styleNotes",
    "synopsis": "synopsis",
    "themes": "themes",
}

WORLD_STATE_KEYS = {
    "currentdate": "currentDate",
    "date": "currentDate",
    "currentlocation": "currentLocation",
    "location": "currentLocation",
    "scene": "scene",
    "timeline": "timeline",
    "factions": "factions",
    "ongoingevents": "ongoingEvents",
    "events": "ongoingEvents",
    "facts": "facts",
}

WORLD_STATE_LIST_KEYS = {"timeline", "factions", "ongoingEvents", "facts"}


def _marker_regex(marker):
    m = re.escape(marker)
    return re.compile(rf"\[\[{m}\]\](.*?)\[\[/{m}\]\]", re.DOTALL | re.IGNORECASE)


def _named_marker_regex(tag):
    t = re.escape(tag)
    return re.compile(
        rf"\[\[{t}(?::([^\]]+))?\]\](.*?)\[\[/{t}\]\]",
        re.DOTALL | re.IGNORECASE,
    )


_MARKER_RES = {tag: _marker_regex(tag) for tag in CAPTURE_MARKERS}
_GENERIC_RE = _marker_regex(GENERIC_MARKER)
_NAMED_LORE_RES = {tag: _named_marker_regex(tag) for tag in CAPTURE_MARKERS}
_BIBLE_RE = re.compile(
    r"\[\[BIBLE:(?P<field>[^\]]+)\]\](?P<body>.*?)\[\[/BIBLE\]\]",
    re.DOTALL | re.IGNORECASE,
)
_BIBLE_SHORT_RE = re.compile(
    r"\[\[(?P<field>PREMISE|LOGLINE|GENRETONE|GENRE|POV|POINTOFVIEW|TENSE|"
    r"WORLDRULES|STYLENOTES|SYNOPSIS|THEMES)\]\](?P<body>.*?)\[\[/\1\]\]",
    re.DOTALL | re.IGNORECASE,
)
_WORLDSTATE_RE = re.compile(
    r"\[\[WORLDSTATE:(?P<field>[^\]]+)\]\](?P<body>.*?)\[\[/WORLDSTATE\]\]",
    re.DOTALL | re.IGNORECASE,
)
_WORLDSTATE_SHORT_RE = re.compile(
    r"\[\[(?P<field>DATE|LOCATION|SCENE|TIMELINE|FACTIONS|EVENTS|FACTS)\]\]"
    r"(?P<body>.*?)\[\[/\1\]\]",
    re.DOTALL | re.IGNORECASE,
)


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


def _name_from_block(block, explicit_name=None):
    """Derive an entry name from a captured block's first line/sentence."""
    if explicit_name and explicit_name.strip():
        return explicit_name.strip()[:60]
    first = block.strip().splitlines()[0].strip() if block.strip() else "Note"
    if ":" in first and len(first.split(":", 1)[0]) <= 60:
        first = first.split(":", 1)[0]
    first = re.sub(r"^[#*\-\s]+", "", first)
    return (first[:60] or "Note").strip()


def _normalize_capture_text(text):
    """Strip common markdown wrappers around capture tags."""
    if not text:
        return ""
    cleaned = re.sub(r"\*+\[\[([^\]]+)\]\]\*+", r"[[\1]]", text)
    cleaned = re.sub(r"_+\[\[([^\]]+)\]\]_+", r"[[\1]]", cleaned)
    return cleaned


def _paragraph_after_open(text, open_tag):
    """Fallback: text after unclosed [[TAG]] until blank line or end."""
    pattern = re.compile(rf"\[\[{re.escape(open_tag)}\]\]\s*", re.IGNORECASE)
    match = pattern.search(text)
    if not match:
        return None
    rest = text[match.end():]
    close = re.search(rf"\[\[/{re.escape(open_tag)}\]\]", rest, re.IGNORECASE)
    if close:
        return None
    chunk = rest.split("\n\n", 1)[0].strip()
    chunk = re.sub(r"\*+$", "", chunk).strip()
    return chunk or None


def _resolve_bible_field(raw_field):
    key = (raw_field or "").strip()
    if not key:
        return None
    if key in BIBLE_KEYS:
        return key
    return BIBLE_ALIASES.get(key.lower().replace(" ", "").replace("&", ""))


CAPTURE_APPEND_NOTE = "--- Agent capture ---"


def _append_separator(source=None):
    src = (source or "agent").strip() or "agent"
    return f"--- Added from {src} ---"


def _merge_text_blocks(old, new):
    """Combine two text blocks into one entry, skipping duplicate paragraphs."""
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


def _apply_text_value(old, new_val, mode, source=None):
    """Merge captured text into an existing scalar field."""
    new_val = (new_val or "").strip()
    if not new_val:
        return old
    old = (old or "").strip() if isinstance(old, str) else ""
    if mode == "empty" and old:
        return old
    if not old:
        return new_val
    if mode == "append":
        return old + "\n\n" + _append_separator(source) + "\n\n" + new_val
    if mode == "merge":
        return _merge_text_blocks(old, new_val)
    # Legacy "replace" -> merge behavior
    return _merge_text_blocks(old, new_val)


def _resolve_world_field(raw_field):
    key = (raw_field or "").strip()
    if not key:
        return None
    if key in world_state.DEFAULT_STATE:
        return key
    return WORLD_STATE_ALIASES.get(key.lower().replace(" ", ""))


def _apply_bible_value(current, field, new_val, mode, source=None):
    new_val = (new_val or "").strip()
    if not new_val:
        return current
    if field == "themes":
        if isinstance(new_val, str):
            items = [t.strip() for t in re.split(r"[,;\n]+", new_val) if t.strip()]
        else:
            items = new_val
        old = current.get("themes") or []
        if mode == "empty" and old:
            return current
        if not old:
            current["themes"] = items
            return current
        if mode == "append":
            note = _append_separator(source)
            old_text = ", ".join(old)
            combined = _apply_text_value(old_text, ", ".join(items), "append", source)
            current["themes"] = [t.strip() for t in combined.split(",") if t.strip()]
        else:
            current["themes"] = list(dict.fromkeys(old + items))
        return current
    old = (current.get(field) or "").strip() if isinstance(current.get(field), str) else ""
    current[field] = _apply_text_value(old, new_val, mode, source)
    return current


def _apply_world_value(current, field, new_val, mode, source=None):
    new_val = (new_val or "").strip()
    if not new_val:
        return current
    if field in WORLD_STATE_LIST_KEYS:
        items = [ln.strip() for ln in new_val.splitlines() if ln.strip()]
        if not items and new_val:
            items = [new_val]
        old = current.get(field) or []
        if mode == "empty" and old:
            return current
        if not old:
            current[field] = items
            return current
        if mode == "append":
            note = _append_separator(source)
            current[field] = list(dict.fromkeys(old + [note] + items))
        else:
            current[field] = list(dict.fromkeys(old + items))
        return current
    old = (current.get(field) or "").strip()
    current[field] = _apply_text_value(old, new_val, mode, source)
    return current


def empty_capture_summary():
    return {"lore": [], "bible": {}, "world_state": {}}


def merge_capture_summaries(base, extra):
    out = empty_capture_summary()
    out["lore"] = list(base.get("lore") or []) + list(extra.get("lore") or [])
    out["bible"] = {**(base.get("bible") or {}), **(extra.get("bible") or {})}
    out["world_state"] = {
        **(base.get("world_state") or {}),
        **(extra.get("world_state") or {}),
    }
    return out


def format_capture_summary(summary):
    """Human-readable one-liner for toasts."""
    parts = []
    lore = summary.get("lore") or []
    if lore:
        names = [e.get("name", "?") for e in lore[:4]]
        label = f"{len(lore)} lore entr{'y' if len(lore) == 1 else 'ies'}"
        if names:
            label += f" ({', '.join(names)}"
            if len(lore) > 4:
                label += ", ..."
            label += ")"
        parts.append(label)
    bible = summary.get("bible") or {}
    if bible:
        parts.append(", ".join(bible.keys()))
    ws = summary.get("world_state") or {}
    if ws:
        parts.append(", ".join(ws.keys()))
    if not parts:
        return ""
    return "Canon updated: " + "; ".join(parts)


def capture_from_agent(paths, raw_text, default_kind="world", source="agent",
                       bible_mode="empty"):
    """Extract tagged blocks and apply to lore, story bible, and world state."""
    summary = empty_capture_summary()
    if not raw_text or not paths:
        return summary

    mode = bible_mode if bible_mode in ("empty", "append", "merge") else "merge"
    if mode == "replace":
        mode = "merge"

    text = _normalize_capture_text(raw_text)
    lore_path = paths["lore"]
    seen_lore = set()

    def _file_lore(kind, block, explicit_name=None):
        block = (block or "").strip()
        if not block:
            return
        name = _name_from_block(block, explicit_name)
        dedupe = (kind, name.lower())
        if dedupe in seen_lore:
            return
        seen_lore.add(dedupe)
        entry = lore.upsert(lore_path, {
            "type": kind,
            "name": name,
            "notes": block,
            "keywords": [name],
        }, mode=mode, source=source)
        summary["lore"].append(entry)

    for tag, kind in CAPTURE_MARKERS.items():
        matched = False
        for match in _NAMED_LORE_RES[tag].finditer(text):
            matched = True
            explicit = match.group(1)
            block = match.group(2)
            _file_lore(kind, block, explicit)
        if not matched:
            unclosed = _paragraph_after_open(text, tag)
            if unclosed:
                _file_lore(kind, unclosed)

    if default_kind:
        matched = False
        for match in _GENERIC_RE.finditer(text):
            matched = True
            _file_lore(default_kind, match.group(1))
        if not matched:
            unclosed = _paragraph_after_open(text, GENERIC_MARKER)
            if unclosed:
                _file_lore(default_kind, unclosed)

    bible_patch = {}
    bible_current = story_bible.read(paths["bible"])
    for match in _BIBLE_RE.finditer(text):
        field = _resolve_bible_field(match.group("field"))
        if field:
            bible_current = _apply_bible_value(
                bible_current, field, match.group("body"), mode, source=source)
            bible_patch[field] = bible_current.get(field)
    for match in _BIBLE_SHORT_RE.finditer(text):
        field = _resolve_bible_field(match.group("field"))
        if field:
            bible_current = _apply_bible_value(
                bible_current, field, match.group("body"), mode, source=source)
            bible_patch[field] = bible_current.get(field)
    if bible_patch:
        story_bible.write(paths["bible"], bible_current)
        summary["bible"] = bible_patch

    ws_patch = {}
    ws_current = world_state.read(paths["world_state"])
    for match in _WORLDSTATE_RE.finditer(text):
        field = _resolve_world_field(match.group("field"))
        if field:
            ws_current = _apply_world_value(
                ws_current, field, match.group("body"), mode, source=source)
            ws_patch[field] = ws_current.get(field)
    for match in _WORLDSTATE_SHORT_RE.finditer(text):
        field = _resolve_world_field(match.group("field"))
        if field:
            ws_current = _apply_world_value(
                ws_current, field, match.group("body"), mode, source=source)
            ws_patch[field] = ws_current.get(field)
    if ws_patch:
        world_state.write(paths["world_state"], ws_current)
        summary["world_state"] = ws_patch

    return summary


def capture_to_lore(paths, raw_text, default_kind="world", source="agent"):
    """Legacy wrapper: lore-only capture."""
    summary = capture_from_agent(paths, raw_text, default_kind, source)
    return summary.get("lore") or []
