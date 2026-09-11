"""Fill Story Bible / world / outline / lore from manuscript chapters.

Extracts only fields the text can support. Apply is merge-without-clobber
unless the caller asks to replace.
"""

from __future__ import annotations

import re

from src import chapters, lore, lore_types, lore_wizard, outline
from src import story_bible, world_state, worldcontext

BIBLE_KEYS = (
    "premise", "logline", "genreTone", "themes", "worldRules",
    "styleNotes", "pointOfView", "tense", "synopsis",
)
WORLD_KEYS = (
    "currentLocation", "currentDate", "scene",
    "timeline", "factions", "ongoingEvents", "facts",
)
CHAPTER_KEYS = ("pov", "location", "storyDate")
OUTLINE_KEYS = ("summary", "beats")
_LIST_KEYS = lore_wizard._LIST_KEYS | {"themes", "beats", "timeline"}
_MAX_LORE = 8
PER_CHAPTER_CHARS = 6000
TOTAL_CHARS = 14000

FIELD_LABELS = {
    "premise": "Premise",
    "logline": "Logline",
    "genreTone": "Genre & tone",
    "themes": "Themes",
    "worldRules": "World rules",
    "styleNotes": "Style notes",
    "pointOfView": "Point of view",
    "tense": "Tense",
    "synopsis": "Synopsis",
    "currentLocation": "Current location",
    "currentDate": "Current date",
    "scene": "Scene notes",
    "timeline": "Timeline",
    "factions": "Factions",
    "ongoingEvents": "Ongoing events",
    "facts": "Facts",
    "pov": "Perspective / POV",
    "location": "Location",
    "storyDate": "Story date",
    "summary": "Summary",
    "beats": "Beats",
}

_DIALOGUE_RE = re.compile(r'"[^"]*"|“[^”]*”')
_FIRST_RE = re.compile(
    r"\b(I|I'm|I've|I'd|I'll|me|my|mine|myself)\b", re.I)
_SECOND_RE = re.compile(r"\b(you|your|yours|yourself)\b", re.I)
_THIRD_RE = re.compile(
    r"\b(he|she|they|him|her|them|his|hers|their|himself|herself|themselves)\b",
    re.I)
_PAST_RE = re.compile(
    r"\b(was|were|had|did|said|looked|walked|turned|took|went|came|saw|"
    r"felt|knew|thought|asked|told|stood|sat|heard|left|made)\b",
    re.I)
_PRESENT_RE = re.compile(
    r"\b(is|are|am|says|looks|walks|turns|takes|goes|comes|sees|"
    r"feels|knows|thinks|asks|tells|stands|sits|hears|leaves|makes|"
    r"say|look|walk|turn|take|go|come|see|feel|know|think|ask|tell|"
    r"stand|sit|hear|leave|make)\b",
    re.I)


def empty_payload() -> dict:
    return {
        "bible": {},
        "world": {},
        "chapter": {},
        "outline": {},
        "lore": [],
    }


def _narrative(text: str) -> str:
    return _DIALOGUE_RE.sub(" ", text or "")


def infer_tense(text: str) -> str:
    body = _narrative(text)
    past = len(_PAST_RE.findall(body))
    present = len(_PRESENT_RE.findall(body))
    if past >= 8 and past >= present * 2:
        return "past"
    if present >= 8 and present >= past * 2:
        return "present"
    return ""


def infer_point_of_view(text: str) -> str:
    body = _narrative(text)
    first = len(_FIRST_RE.findall(body))
    second = len(_SECOND_RE.findall(body))
    third = len(_THIRD_RE.findall(body))
    total = first + second + third
    if total < 10:
        return ""
    if first >= 8 and first >= max(second, third) * 2:
        return "first person"
    if second >= 8 and second >= max(first, third) * 2:
        return "second person"
    if third >= 8 and third >= max(first, second) * 2:
        return "third person"
    return ""


def infer_craft(text: str) -> dict:
    out = {}
    pov = infer_point_of_view(text)
    tense = infer_tense(text)
    if pov:
        out["pointOfView"] = pov
    if tense:
        out["tense"] = tense
    return out


def collect_manuscript(paths, chapter_ids, *, prefer_id: str | None = None,
                       per_chapter: int = PER_CHAPTER_CHARS,
                       total: int = TOTAL_CHARS) -> dict:
    """Return {text, chapters: [{id, name, content}], used_ids}."""
    if not paths:
        return {"text": "", "chapters": [], "used_ids": []}
    wanted = [cid for cid in (chapter_ids or []) if cid]
    if not wanted:
        return {"text": "", "chapters": [], "used_ids": []}
    order = chapters.list_chapters(paths["chapters"])
    by_id = {c["id"]: c for c in order}
    ids = [cid for cid in wanted if cid in by_id]
    if prefer_id and prefer_id in ids:
        ids = [prefer_id] + [cid for cid in ids if cid != prefer_id]
    chunks = []
    used = []
    used_chars = 0
    for cid in ids:
        meta = chapters.read(paths["chapters"], cid)
        body = (meta.get("content") or "").strip()
        if not body:
            continue
        if per_chapter and len(body) > per_chapter:
            body = body[:per_chapter].rstrip() + "\n…"
        block = f"=== CHAPTER: {meta.get('name') or cid} ===\n{body}"
        if used_chars and used_chars + len(block) > total:
            remain = total - used_chars
            if remain < 400:
                break
            block = block[:remain].rstrip() + "\n…"
        chunks.append(block)
        used.append(cid)
        used_chars += len(block)
        if used_chars >= total:
            break
    return {
        "text": "\n\n".join(chunks),
        "chapters": chunks,
        "used_ids": used,
    }


def existing_names(paths) -> list[tuple[str, str]]:
    if not paths:
        return []
    book = lore.read(paths["lore"])
    out = []
    for entry in (book.get("characters") or []) + (book.get("world") or []):
        name = (entry.get("name") or "").strip()
        if name:
            et = entry.get("entryType") or "character"
            out.append((name, et))
    return out


def _normalize_field(key: str, value):
    if key in _LIST_KEYS:
        return lore_wizard._as_list(value)
    return lore_wizard._normalize_value(key, value)


def _filter_dict(raw, allowed: tuple[str, ...]) -> dict:
    if not isinstance(raw, dict):
        return {}
    out = {}
    for key in allowed:
        if key not in raw:
            continue
        norm = _normalize_field(key, raw.get(key))
        if lore_wizard._empty(norm):
            continue
        out[key] = norm
    return out


def _parse_lore_item(raw) -> dict | None:
    if not isinstance(raw, dict):
        return None
    name = (raw.get("name") or "").strip()
    if not name:
        return None
    et = lore_types.normalize_entry_type(
        raw.get("entryType") or raw.get("type"), "world")
    allowed = lore_wizard.known_keys(et)
    fields = _filter_dict(raw, allowed)
    fields["name"] = name
    fields["entryType"] = et
    return fields


def parse_payload(text: str) -> dict:
    """Parse model JSON into a typed payload (known keys only)."""
    out = empty_payload()
    data = lore_wizard.parse_json_payload(text)
    if not isinstance(data, dict):
        return out
    bible = data.get("bible") or data.get("storyBible") or {}
    if not isinstance(bible, dict) and any(k in data for k in BIBLE_KEYS):
        bible = data
    out["bible"] = _filter_dict(bible, BIBLE_KEYS)
    out["world"] = _filter_dict(data.get("world") or data.get("worldState"), WORLD_KEYS)
    out["chapter"] = _filter_dict(data.get("chapter") or data.get("chapterMeta"), CHAPTER_KEYS)
    outline_raw = data.get("outline") or {}
    out["outline"] = _filter_dict(outline_raw, OUTLINE_KEYS)
    lore_raw = data.get("lore") or data.get("entries") or []
    if isinstance(lore_raw, dict):
        lore_raw = [lore_raw]
    seen = set()
    for item in lore_raw[:_MAX_LORE * 2]:
        parsed = _parse_lore_item(item)
        if not parsed:
            continue
        key = lore._norm_name(parsed["name"])
        if key in seen:
            continue
        seen.add(key)
        out["lore"].append(parsed)
        if len(out["lore"]) >= _MAX_LORE:
            break
    return out


def merge_heuristics(payload: dict, craft: dict | None) -> dict:
    """Fill bible POV/tense from heuristics only when the model omitted them."""
    out = {
        "bible": dict((payload or {}).get("bible") or {}),
        "world": dict((payload or {}).get("world") or {}),
        "chapter": dict((payload or {}).get("chapter") or {}),
        "outline": dict((payload or {}).get("outline") or {}),
        "lore": list((payload or {}).get("lore") or []),
    }
    for key, value in (craft or {}).items():
        if value and lore_wizard._empty(out["bible"].get(key)):
            out["bible"][key] = value
    return out


def payload_has_proposals(payload: dict | None) -> bool:
    p = payload or {}
    return bool(
        p.get("bible") or p.get("world") or p.get("chapter")
        or p.get("outline") or p.get("lore"))


def merge_section(existing: dict | None, generated: dict | None,
                  replace: bool = False) -> dict:
    return lore_wizard.merge_without_clobber(existing, generated, replace=replace)


def format_value(value) -> str:
    if isinstance(value, list):
        return ", ".join(str(v) for v in value if v)
    return str(value or "").strip()


def build_fill_prompt(paths, manuscript: str, *, existing_lore=None,
                      setting: str = "") -> tuple[str, str]:
    persona = lore_wizard.persona_for_kind("canon")
    system = (
        (persona.get("system_prompt") or "").strip()
        + "\n\nThis task is a manuscript audit. Output STRICT JSON only. "
        "No markdown fences, no preamble, no [[REMEMBER]] markers. "
        "Extract ONLY facts the manuscript states or makes unmistakable. "
        "Omit a field rather than guess, infer a theme, or invent lore."
    ).strip()
    names = existing_lore if existing_lore is not None else existing_names(paths)
    name_line = ", ".join(f"{n} ({t})" for n, t in names[:40]) or "(none yet)"
    user = "\n\n".join([
        "Read the chapter text and fill this JSON (omit empty keys and empty objects):",
        '{"bible":{"premise":"","logline":"","genreTone":"","themes":[],'
        '"worldRules":"","styleNotes":"","pointOfView":"","tense":"","synopsis":""},'
        '"world":{"currentLocation":"","currentDate":"","scene":"",'
        '"timeline":[],"factions":[],"ongoingEvents":[],"facts":[]},'
        '"chapter":{"pov":"","location":"","storyDate":""},'
        '"outline":{"summary":"","beats":[]},'
        '"lore":[{"name":"","entryType":"character","notes":""}]}',
        "Rules:",
        "- bible.pointOfView is grammatical (first person / close third / …).",
        "- chapter.pov is the perspective character's name if one is clear.",
        "- bible.tense is past, present, or present perfect — only if consistent.",
        "- synopsis / outline.summary / beats cover ONLY these chapters, not a guessed series.",
        "- lore: at most 8 entries; names that appear in the text; entryType from "
        + ", ".join(lore_types.ENTRY_TYPE_KEYS) + ".",
        "- Prefer updating these existing names: " + name_line,
        "- List fields must be JSON arrays of short strings.",
        "MANUSCRIPT:\n" + (manuscript or "").strip(),
        (setting.strip()[:2000] if setting.strip() else ""),
        "Output the JSON object now.",
    ])
    return system, user


def apply_payload(paths, payload: dict, *, replace: bool = False,
                  chapter_id: str | None = None) -> dict:
    """Write accepted fields to disk. Returns per-section apply counts."""
    counts = {"bible": 0, "world": 0, "chapter": 0, "outline": 0, "lore": 0}
    if not paths or not payload:
        return counts

    bible_gen = payload.get("bible") or {}
    if bible_gen:
        current = story_bible.read(paths["bible"])
        merged = merge_section(current, bible_gen, replace=replace)
        changed = {k: merged[k] for k in bible_gen if merged.get(k) != current.get(k)}
        if changed:
            story_bible.write(paths["bible"], merged)
            counts["bible"] = len(changed)

    world_gen = payload.get("world") or {}
    if world_gen:
        current = world_state.read(paths["world_state"])
        merged = merge_section(current, world_gen, replace=replace)
        changed = {k: merged[k] for k in world_gen if merged.get(k) != current.get(k)}
        if changed:
            world_state.write(paths["world_state"], merged)
            counts["world"] = len(changed)

    if chapter_id:
        ch_gen = payload.get("chapter") or {}
        if ch_gen:
            try:
                meta = chapters.read(paths["chapters"], chapter_id)
            except ValueError:
                meta = {}
            patch = {}
            for key in CHAPTER_KEYS:
                val = ch_gen.get(key)
                if lore_wizard._empty(val):
                    continue
                if replace or lore_wizard._empty(meta.get(key)):
                    patch[key] = val if isinstance(val, str) else format_value(val)
            if patch:
                chapters.update_meta(paths["chapters"], chapter_id, **patch)
                counts["chapter"] = len(patch)

        ol_gen = payload.get("outline") or {}
        if ol_gen:
            current = outline.read_chapter(paths["outlines"], chapter_id)
            merged = merge_section(current, ol_gen, replace=replace)
            if merged.get("beats") is not None and not isinstance(merged["beats"], list):
                merged["beats"] = lore_wizard._as_list(merged["beats"])
            if merged != current:
                outline.write_chapter(paths["outlines"], chapter_id, merged)
                counts["outline"] = sum(
                    1 for k in ol_gen if not lore_wizard._empty(merged.get(k)))

    for entry in payload.get("lore") or []:
        name = (entry.get("name") or "").strip()
        if not name:
            continue
        book = lore.read(paths["lore"])
        existing = None
        needle = lore._norm_name(name)
        for row in book["characters"] + book["world"]:
            if lore._norm_name(row.get("name")) == needle:
                existing = row
                break
        if existing:
            merged = merge_section(existing, entry, replace=replace)
            merged["id"] = existing.get("id")
            lore.save_entry(paths["lore"], merged)
        else:
            lore.add(paths["lore"], entry)
        counts["lore"] += 1
    return counts


def gather_setting(paths) -> str:
    if not paths:
        return ""
    return worldcontext.assemble(paths) or ""
