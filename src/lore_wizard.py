"""Story Bible generation wizards — question packs, prompts, and JSON fill."""

from __future__ import annotations

import json
import re

from src import lore_types, personas

CANON_KIND = "canon"
WORLD_KIND = "world"

LORE_KINDS = tuple(k for k, _label, _bucket in lore_types.ENTRY_TYPES)
WIZARD_KINDS = LORE_KINDS + (CANON_KIND, WORLD_KIND)

PERSONA_FOR_KIND: dict[str, str] = {
    "character": "character_dev",
    "creature": "creature_dev",
    "place": "world_builder",
    "thing": "world_builder",
    "faction": "world_builder",
    "event": "quest_architect",
    "concept": "lore_curator",
    CANON_KIND: "lore_curator",
    WORLD_KIND: "world_builder",
}

CANON_KEYS = ("premise", "genreTone", "worldRules", "styleNotes", "synopsis")
WORLD_KEYS = ("currentLocation", "currentDate", "factions", "ongoingEvents", "facts")
_SKIP_FILL = {"portraitPath"}
_LIST_KEYS = frozenset({
    "keywords", "aliases", "tags", "groups",
    "factions", "ongoingEvents", "facts", "timeline",
})
_JSON_INSTRUCTION = (
    "This task is a structured interview / field-fill. Output STRICT JSON only. "
    "No markdown fences, no preamble, no Surface/Shadow sections, and no "
    "[[REMEMBER]], [[CHARACTER]], or other canon markers."
)
_WRAPPER_KEYS = (
    "fields", "entry", "card", "result", "data", "lore", "character", "person",
    "creature", "place", "thing", "faction", "event", "concept", "world",
    "bible", "canon", "storyBible", "worldState",
)
_FILL_KEY_ALIASES = {
    "title": "name",
    "fullname": "name",
    "charactername": "name",
    "entryname": "name",
    "displayname": "name",
    "description": "appearance",
    "desc": "appearance",
    "looks": "appearance",
    "physical": "appearance",
    "motivation": "goals",
    "motivations": "goals",
    "want": "goals",
    "backstory": "notes",
    "summary": "notes",
    "bio": "notes",
    "biography": "notes",
    "content": "notes",
    "explanation": "notes",
    "behavior": "notes",
    "surface": "personality",
    "shadow": "notes",
    "shadowlog": "notes",
    "speech": "voiceStyle",
    "hook": "premise",
    "tone": "genreTone",
    "genre": "genreTone",
    "stylenotes": "styleNotes",
    "where": "currentLocation",
    "location": "currentLocation",
    "date": "currentDate",
    "when": "currentDate",
}
_QUESTION_FIELD = {
    "character": {
        "role": "role", "drive": "goals", "mask": "personality",
        "looks": "appearance", "ties": "relationships",
    },
    "creature": {
        "type": "creatureType", "habitat": "origin", "powers": "powers",
        "looks": "appearance", "people": "notes",
    },
    "place": {
        "control": "leadership", "feel": "climate", "people": "inhabitants",
        "history": "history",
    },
    "thing": {
        "origin": "origin", "powers": "powers", "looks": "appearance",
        "history": "history",
    },
    "faction": {
        "lead": "leadership", "goals": "goals", "base": "territory",
        "history": "history",
    },
    "event": {
        "when": "when", "who": "participants", "outcome": "outcome",
        "matter": "notes",
    },
    "concept": {"core": "notes", "who": "notes", "rules": "notes"},
    CANON_KIND: {
        "hook": "premise", "tone": "genreTone", "rules": "worldRules",
        "style": "styleNotes", "synopsis": "synopsis",
    },
    WORLD_KIND: {
        "where": "currentLocation", "when": "currentDate",
        "factions": "factions", "events": "ongoingEvents", "facts": "facts",
    },
}
_CAPTURE_RE = re.compile(
    r"\[\[(CHARACTER|CREATURE|SPECIES|NPC|WORLD|PLACE|THING|FACTION|EVENT)"
    r"(?::([^\]]+))?\]\](.*?)\[\[/\1\]\]",
    re.I | re.S,
)

_KIND_LABELS = {
    **lore_types.ENTRY_TYPE_LABELS,
    CANON_KIND: "Story Bible (canon)",
    WORLD_KIND: "World State",
}


def kind_label(kind: str) -> str:
    return _KIND_LABELS.get(kind, (kind or "entry").title())


def normalize_kind(kind: str, default: str = "character") -> str:
    key = (kind or "").strip().lower()
    if key in WIZARD_KINDS:
        return key
    return lore_types.normalize_entry_type(key, "world") if key else default


def persona_for_kind(kind: str) -> dict:
    key = PERSONA_FOR_KIND.get(normalize_kind(kind), "lore_curator")
    for persona in personas.PERSONAS:
        if persona.get("key") == key:
            return persona
    return {
        "key": key,
        "display_name": key,
        "model_key": "architect",
        "temperature": 0.4,
        "system_prompt": "",
    }


def known_keys(kind: str) -> tuple[str, ...]:
    kind = normalize_kind(kind)
    if kind == CANON_KIND:
        return CANON_KEYS
    if kind == WORLD_KIND:
        return WORLD_KEYS
    keys = ["name"]
    for key, _label, _multi in lore_types.fields_for_entry_type(kind):
        if key not in _SKIP_FILL and key not in keys:
            keys.append(key)
    return tuple(keys)


def _empty(value) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, tuple, dict)):
        return len(value) == 0
    return False


def _as_list(value) -> list:
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, str):
        chunks = re.split(r"[\n,;]+", value)
        return [c.strip() for c in chunks if c.strip()]
    if value in (None, ""):
        return []
    return [str(value).strip()] if str(value).strip() else []


def _normalize_value(key: str, value):
    if value is None:
        return "" if key not in _LIST_KEYS else []
    if key in _LIST_KEYS:
        return _as_list(value)
    if key == "relationships":
        if isinstance(value, list):
            return value
        return str(value).strip()
    if isinstance(value, list):
        return "\n".join(str(v).strip() for v in value if str(v).strip())
    return str(value).strip()


def _strip_fences(text: str) -> str:
    raw = str(text or "").strip()
    raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.I | re.S)
    raw = re.sub(r"<thought>.*?</thought>", "", raw, flags=re.I | re.S)
    raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.I)
    raw = re.sub(r"\s*```$", "", raw)
    return raw.strip()


def _loads_json(raw: str):
    if not raw:
        return None
    for candidate in (raw, re.sub(r",\s*([}\]])", r"\1", raw)):
        try:
            data = json.loads(candidate)
        except (json.JSONDecodeError, ValueError, TypeError):
            continue
        if isinstance(data, (dict, list)):
            return data
    return None


def parse_json_payload(text: str):
    """Best-effort JSON object or array from model output."""
    raw = _strip_fences(text)
    if not raw:
        return None
    data = _loads_json(raw)
    if data is not None:
        return data
    for start_ch, end_ch in (("{", "}"), ("[", "]")):
        start, end = raw.find(start_ch), raw.rfind(end_ch)
        if start >= 0 and end > start:
            data = _loads_json(raw[start:end + 1])
            if data is not None:
                return data
    return None


def fallback_questions(kind: str) -> list[dict]:
    kind = normalize_kind(kind)
    packs = {
        "character": (
            ("role", "What is their role in the story?",
             ["protagonist", "antagonist", "mentor", "ally", "foil", "love interest"], False),
            ("drive", "What do they want most — and what wound drives it?",
             ["revenge", "duty", "belonging", "survival", "power", "love"], True),
            ("mask", "How do they present versus who they really are?",
             ["stoic", "charming", "invisible", "volatile"], False),
            ("looks", "How do they look, move, and speak?",
             ["weathered", "precise", "soft-spoken", "commanding"], True),
            ("ties", "Who are they bound to — loyalty, debt, or blood?",
             [], False),
        ),
        "creature": (
            ("type", "What kind of organism or construct is this?",
             ["predator", "scavenger", "parasite", "swarm", "augment"], False),
            ("habitat", "Where do they live, and what shaped them?",
             ["deep water", "ruins", "desert", "city underbelly"], False),
            ("powers", "What can they do, and what does it cost?",
             ["venom", "camouflage", "pack hunt", "psychic sense"], True),
            ("looks", "How do they look and hunt or behave?",
             [], False),
            ("people", "How do people in the setting treat them?",
             ["sacred", "vermin", "livestock", "weapon"], False),
        ),
        "place": (
            ("control", "Who controls this place, and who suffers under that?",
             ["crown", "guild", "gang", "church", "no one"], False),
            ("feel", "What does it feel like to stand here?",
             ["crowded", "abandoned", "sacred", "industrial", "rotten"], True),
            ("people", "Who lives here, who passes through, who is shut out?",
             [], False),
            ("history", "What history still marks the streets or walls?",
             ["war", "plague", "founding", "betrayal"], True),
        ),
        "thing": (
            ("origin", "Who made it, or where did it come from?",
             ["forged", "found", "stolen", "grown", "unknown"], False),
            ("powers", "What does it do — and what does using it cost?",
             [], False),
            ("looks", "What does it look, weigh, and feel like?",
             [], False),
            ("history", "What history, curse, or provenance is attached?",
             ["heirloom", "weapon", "relic", "contraband"], False),
        ),
        "faction": (
            ("lead", "Who leads them, and how is power kept?",
             ["council", "warlord", "matriarch", "figurehead"], False),
            ("goals", "What do they want this season — and at what cost?",
             ["territory", "legitimacy", "revenge", "survival"], True),
            ("base", "Where is their territory or seat?",
             [], False),
            ("history", "How did they form, and who still hates them?",
             [], False),
        ),
        "event": (
            ("when", "When did this happen (date, era, or relative time)?",
             ["last night", "a generation ago", "during the war"], False),
            ("who", "Who took part, and who was left out?",
             [], False),
            ("outcome", "What changed because of it?",
             ["victory", "massacre", "treaty", "vanishing"], False),
            ("matter", "Why does it still matter to the story now?",
             [], False),
        ),
        "concept": (
            ("core", "What is the idea in one plain sentence?",
             [], False),
            ("who", "Who believes, teaches, or exploits it?",
             [], False),
            ("rules", "What rules, limits, or costs apply?",
             [], False),
        ),
        CANON_KIND: (
            ("hook", "What is the story's hook — the premise in a few sentences?",
             [], False),
            ("tone", "What genre and tone should the prose keep?",
             ["grim", "lyrical", "dry", "pulp", "intimate"], True),
            ("rules", "What rules does this world never break?",
             [], False),
            ("style", "Any hard style notes for the writer (POV, diction, bans)?",
             [], False),
            ("synopsis", "What is the plot as you know it so far?",
             [], False),
        ),
        WORLD_KIND: (
            ("where", "Where is the story right now?",
             [], False),
            ("when", "What is the current date, season, or era?",
             [], False),
            ("factions", "Which factions are in play in this moment?",
             [], True),
            ("events", "What events are unfolding right now?",
             [], False),
            ("facts", "What facts are currently true that agents must not contradict?",
             [], False),
        ),
    }
    rows = packs.get(kind, packs["concept"])
    out = []
    for qid, prompt, chips, multi in rows:
        out.append({
            "id": qid,
            "prompt": prompt,
            "chips": list(chips),
            "multi": bool(multi),
        })
    return out


def _normalize_question(raw, index: int) -> dict | None:
    if isinstance(raw, str) and raw.strip():
        return {
            "id": f"q{index + 1}",
            "prompt": raw.strip(),
            "chips": [],
            "multi": False,
        }
    if not isinstance(raw, dict):
        return None
    prompt = (raw.get("prompt") or raw.get("question") or raw.get("text") or "").strip()
    if not prompt:
        return None
    chips_raw = raw.get("chips") or raw.get("options") or raw.get("choices") or []
    chips = []
    if isinstance(chips_raw, str):
        chips = _as_list(chips_raw)
    elif isinstance(chips_raw, list):
        chips = [str(c).strip() for c in chips_raw if str(c).strip()]
    qid = str(raw.get("id") or raw.get("key") or f"q{index + 1}").strip() or f"q{index + 1}"
    multi = bool(raw.get("multi") or raw.get("multiSelect") or raw.get("multiple"))
    return {"id": qid, "prompt": prompt, "chips": chips, "multi": multi}


def parse_questions(text: str, kind: str) -> list[dict]:
    """Parse a questions JSON payload; fall back to the static pack."""
    data = parse_json_payload(text)
    rows = None
    if isinstance(data, list):
        rows = data
    elif isinstance(data, dict):
        for key in ("questions", "items", "steps"):
            if isinstance(data.get(key), list):
                rows = data[key]
                break
    out = []
    seen = set()
    if rows:
        for i, raw in enumerate(rows):
            q = _normalize_question(raw, i)
            if not q or q["id"] in seen:
                continue
            seen.add(q["id"])
            out.append(q)
    return out or fallback_questions(kind)


def _canonical_fill_key(raw_key: str, allowed: set[str]) -> str | None:
    raw = str(raw_key or "").strip()
    if raw in allowed:
        return raw
    compact = raw.lower().replace(" ", "").replace("-", "").replace("_", "")
    if not compact:
        return None
    mapped = _FILL_KEY_ALIASES.get(compact)
    if mapped == "appearance" and "appearance" not in allowed:
        mapped = "notes" if "notes" in allowed else mapped
    if mapped == "currentDate" and "currentDate" not in allowed and "when" in allowed:
        mapped = "when"
    if mapped in allowed:
        return mapped
    aliased = lore_types.FIELD_ALIASES.get(compact)
    if aliased == "description":
        aliased = "appearance" if "appearance" in allowed else "notes"
    if aliased in allowed:
        return aliased
    for key in allowed:
        if key.lower().replace("_", "") == compact:
            return key
    return None


def _coerce_fill_dict(data, kind: str) -> dict:
    if isinstance(data, list) and data and isinstance(data[0], dict):
        merged = {}
        for item in data:
            if isinstance(item, dict):
                merged.update(item)
        data = merged
    if not isinstance(data, dict):
        return {}
    allowed = set(known_keys(kind))
    if not any(_canonical_fill_key(key, allowed) for key in data):
        for wrap in _WRAPPER_KEYS:
            inner = data.get(wrap)
            if isinstance(inner, dict):
                data = inner
                break
        else:
            nested = [v for v in data.values() if isinstance(v, dict)]
            if len(nested) == 1:
                data = nested[0]
    out = {}
    for key, value in data.items():
        canon = _canonical_fill_key(key, allowed)
        if not canon:
            continue
        norm = _normalize_value(canon, value)
        if _empty(norm):
            continue
        if canon in out and not _empty(out[canon]):
            continue
        out[canon] = norm
    return out


def parse_fill(text: str, kind: str) -> dict:
    """Parse fill JSON and keep only known keys for the wizard kind."""
    return _coerce_fill_dict(parse_json_payload(text), kind)


def _fields_from_capture(text: str, kind: str) -> dict:
    kind = normalize_kind(kind)
    if kind not in LORE_KINDS:
        return {}
    from src.lore_capture_parse import parse_capture_block

    allowed = set(known_keys(kind))
    out = {}
    for match in _CAPTURE_RE.finditer(text or ""):
        name = (match.group(2) or "").strip()
        body = match.group(3) or ""
        if name and "name" in allowed and _empty(out.get("name")):
            out["name"] = name
        parsed = parse_capture_block(body, kind, name)
        for key, value in parsed.items():
            canon = _canonical_fill_key(key, allowed)
            if not canon or not _empty(out.get(canon)):
                continue
            norm = _normalize_value(canon, value)
            if not _empty(norm):
                out[canon] = norm
    return out


def _fields_from_prose(text: str, kind: str) -> dict:
    kind = normalize_kind(kind)
    raw = _strip_fences(text)
    if not raw or ":" not in raw or raw.lstrip()[:1] in "{[":
        return {}
    from src.lore_capture_parse import parse_capture_block

    allowed = set(known_keys(kind))
    entry_kind = kind if kind in LORE_KINDS else "concept"
    parsed = parse_capture_block(raw, entry_kind, "")
    out = {}
    for key, value in parsed.items():
        canon = _canonical_fill_key(key, allowed)
        if not canon:
            continue
        norm = _normalize_value(canon, value)
        if not _empty(norm):
            out[canon] = norm
    return out


def _answer_shown(item: dict) -> str:
    chips = [str(c).strip() for c in (item.get("chips") or []) if str(c).strip()]
    text = (item.get("text") or "").strip()
    if text:
        extra = [c for c in chips if not phrase_in_answer(text, c)]
        return text if not extra else text + "; " + "; ".join(extra)
    return "; ".join(chips)


def fields_from_interview(kind: str, seed: str = "", answers=None) -> dict:
    """Build a card from the seed + interview when the model returns no JSON."""
    kind = normalize_kind(kind)
    allowed = set(known_keys(kind))
    out = {}
    seed = (seed or "").strip()
    if seed:
        first = seed.splitlines()[0].strip()
        name_part = re.split(r"\s+[—–-]\s+", first, maxsplit=1)[0].strip()
        if kind not in (CANON_KIND, WORLD_KIND) and "name" in allowed and name_part:
            if len(name_part) <= 80:
                out["name"] = name_part
        elif kind == CANON_KIND and "premise" in allowed:
            out["premise"] = seed
        elif kind == WORLD_KIND and "facts" in allowed:
            out["facts"] = [ln.strip() for ln in seed.splitlines() if ln.strip()][:8]

    leftover = []
    qmap = _QUESTION_FIELD.get(kind, {})
    for qid, item in (answers or {}).items():
        if not isinstance(item, dict):
            continue
        shown = _answer_shown(item)
        if not shown:
            continue
        field = qmap.get(str(qid))
        if not field and str(qid) in allowed:
            field = str(qid)
        if field in allowed and field != "name" and _empty(out.get(field)):
            out[field] = _normalize_value(field, shown)
        else:
            prompt = (item.get("prompt") or str(qid)).strip()
            leftover.append(f"{prompt}: {shown}")

    dump_key = (
        "notes" if "notes" in allowed
        else "synopsis" if "synopsis" in allowed
        else "facts" if "facts" in allowed
        else None
    )
    if leftover and dump_key and _empty(out.get(dump_key)):
        if dump_key == "facts":
            out[dump_key] = leftover
        else:
            out[dump_key] = "\n\n".join(leftover)
    return {key: value for key, value in out.items()
            if key in allowed and not _empty(value)}


def complete_fill(text: str, kind: str, seed: str = "", answers=None) -> dict:
    """Parse model fill output and backfill blanks from the interview."""
    out = parse_fill(text, kind)
    for extra in (
            _fields_from_capture(text, kind),
            _fields_from_prose(text, kind),
            fields_from_interview(kind, seed, answers)):
        out = merge_without_clobber(out, extra, replace=False)
    return out


def fill_has_content(fields: dict | None) -> bool:
    skip = {"id", "entryType", "type", "portraitPath", "chapterScope"}
    for key, value in (fields or {}).items():
        if key in skip or _empty(value):
            continue
        if key == "name" and str(value).strip().lower() in {"new entry", "untitled"}:
            continue
        return True
    return False


def merge_without_clobber(existing: dict | None, generated: dict | None,
                          replace: bool = False) -> dict:
    """Merge generated fields into existing. Empty generated values never win.

    When replace is False, skip keys that already have content.
    """
    base = dict(existing or {})
    gen = dict(generated or {})
    out = dict(base)
    for key, value in gen.items():
        if _empty(value):
            continue
        if replace or _empty(base.get(key)):
            out[key] = value
    return out


def _answer_segments(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"[\n,;]+", text or "") if p.strip()]


def phrase_in_answer(text: str, phrase: str) -> bool:
    needle = (phrase or "").strip().lower()
    if not needle:
        return False
    raw = (text or "").strip()
    if raw.lower() == needle:
        return True
    return needle in {p.lower() for p in _answer_segments(raw)}


def insert_chip_phrase(text: str, phrase: str) -> str:
    """Add a chip label to the answer box without duplicating it."""
    label = (phrase or "").strip()
    raw = text or ""
    if not label or phrase_in_answer(raw, label):
        return raw
    if not raw.strip():
        return label
    if "\n" in raw:
        return raw.rstrip() + "\n" + label
    return raw.rstrip() + ", " + label


def remove_chip_phrase(text: str, phrase: str) -> str:
    """Drop a chip label that was inserted as its own answer segment."""
    label = (phrase or "").strip()
    raw = text or ""
    if not label or not raw.strip():
        return raw
    parts = _answer_segments(raw)
    kept = [p for p in parts if p.lower() != label.lower()]
    if len(kept) == len(parts):
        return raw
    if "\n" in raw:
        return "\n".join(kept)
    return ", ".join(kept)


def format_answers(answers: dict | None) -> str:
    """Turn stepper answers into a prompt block."""
    lines = []
    for item in (answers or {}).values():
        if not isinstance(item, dict):
            continue
        prompt = (item.get("prompt") or item.get("id") or "Question").strip()
        chips = [str(c).strip() for c in (item.get("chips") or []) if str(c).strip()]
        text = (item.get("text") or "").strip()
        if text:
            extra = [c for c in chips if not phrase_in_answer(text, c)]
            shown = text if not extra else text + "; " + "; ".join(extra)
        else:
            shown = "; ".join(chips)
        if not shown:
            continue
        lines.append(f"Q: {prompt}\nA: {shown}")
    return "\n\n".join(lines)


def _existing_block(existing: dict | None, kind: str) -> str:
    if not existing:
        return ""
    allowed = set(known_keys(kind))
    lines = []
    for key in known_keys(kind):
        val = existing.get(key)
        if key not in allowed or _empty(val):
            continue
        if isinstance(val, list):
            shown = ", ".join(str(v) for v in val if v)
        else:
            shown = str(val).strip()
        if shown:
            lines.append(f"- {key}: {shown}")
    return "\n".join(lines)


def _wizard_system(kind: str) -> str:
    persona = persona_for_kind(kind)
    name = persona.get("display_name") or "specialist"
    return (
        f"ROLE: You are {name} filling a structured Story Bible form.\n"
        "BEHAVIOR:\n"
        "- Output a single JSON object (or a questions array) only.\n"
        "- Use the exact field keys requested. Omit empty keys.\n"
        "- Stay consistent with SETTING and the author's answers.\n"
        + _JSON_INSTRUCTION
    )


def build_questions_prompt(kind: str, seed: str = "", existing: dict | None = None,
                           setting: str = "") -> tuple[str, str]:
    kind = normalize_kind(kind)
    keys = ", ".join(known_keys(kind))
    user_parts = [
        f"KIND: {kind_label(kind)} ({kind})",
        "Ask 4–6 short interview questions that will let you fill these fields: "
        + keys + ".",
        "Return JSON only in this shape:",
        '{"questions":[{"id":"short_key","prompt":"...","chips":["opt"],"multi":false}]}',
        "chips are optional suggested answers (2–6). Set multi true when several "
        "chips can apply at once.",
    ]
    if seed.strip():
        user_parts.append("AUTHOR SEED:\n" + seed.strip())
    existing_txt = _existing_block(existing, kind)
    if existing_txt:
        user_parts.append("ALREADY FILLED (do not re-ask these unless thin):\n" + existing_txt)
    if setting.strip():
        user_parts.append(setting.strip())
    user_parts.append("Output the JSON now.")
    return _wizard_system(kind), "\n\n".join(user_parts)


def build_fill_prompt(kind: str, seed: str = "", answers: dict | None = None,
                      existing: dict | None = None, setting: str = "") -> tuple[str, str]:
    kind = normalize_kind(kind)
    keys = ", ".join(known_keys(kind))
    user_parts = [
        f"KIND: {kind_label(kind)} ({kind})",
        "Fill a JSON object using ONLY these keys (omit empty ones): " + keys + ".",
        "Use the author's answers. Stay consistent with SETTING. Invent only what "
        "the answers imply — do not pad.",
        "List fields (keywords, aliases, tags, groups, factions, ongoingEvents, "
        "facts) must be JSON arrays of short strings.",
        "Example keys only: " + json.dumps({
            key: ([] if key in _LIST_KEYS else "…")
            for key in list(known_keys(kind))[:8]
        }),
    ]
    if seed.strip():
        user_parts.append("AUTHOR SEED:\n" + seed.strip())
    answers_txt = format_answers(answers)
    if answers_txt:
        user_parts.append("INTERVIEW ANSWERS:\n" + answers_txt)
    existing_txt = _existing_block(existing, kind)
    if existing_txt:
        user_parts.append("EXISTING CARD (extend; do not contradict):\n" + existing_txt)
    if setting.strip():
        user_parts.append(setting.strip())
    user_parts.append("Output the JSON object now.")
    return _wizard_system(kind), "\n\n".join(user_parts)


def preview_fields(fields: dict | None) -> str:
    """Human-readable preview of a fill payload."""
    lines = []
    for key, value in (fields or {}).items():
        if _empty(value):
            continue
        if isinstance(value, list):
            shown = ", ".join(str(v) for v in value if v)
        else:
            shown = str(value).strip()
        if shown:
            lines.append(f"{key}:\n{shown}")
    return "\n\n".join(lines)
