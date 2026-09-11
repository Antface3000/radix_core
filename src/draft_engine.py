"""Draft lightbox — Generate Scenes beats and Plan Draft direction."""

from __future__ import annotations

import os
import re

from src import lore, outline, story_bible, story_context, worldcontext
from src import personas

PARKING_CAP = 4000
PARKING_NAME = "parking_lot.txt"

_SCENE_LINE_RE = re.compile(
    r"^(?:[-*•]\s+|\d+[.)]\s+|scene\s+\d+\s*[:.)-]\s*)",
    re.IGNORECASE,
)


def parking_lot_path(paths) -> str | None:
    if not paths or not paths.get("root"):
        return None
    return os.path.join(paths["root"], PARKING_NAME)


def read_parking_lot(paths, max_chars: int = PARKING_CAP) -> str:
    path = parking_lot_path(paths)
    if not path:
        return ""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            text = fh.read()
    except OSError:
        return ""
    text = text.strip()
    if max_chars and len(text) > max_chars:
        return text[:max_chars].rstrip() + "\n…"
    return text


def _chapter_outline(paths, chapter_id: str) -> dict:
    if not paths or not chapter_id:
        return {"summary": "", "beats": []}
    return outline.read_chapter(paths["outlines"], chapter_id)


def _beat_text(beat) -> str:
    if isinstance(beat, dict):
        return str(beat.get("text") or beat.get("beat") or "").strip()
    return str(beat or "").strip()


def format_outline_block(chapter: dict) -> str:
    parts = []
    summary = (chapter.get("summary") or "").strip()
    if summary:
        parts.append("Summary: " + summary)
    beats = [_beat_text(b) for b in (chapter.get("beats") or [])]
    beats = [b for b in beats if b]
    if beats:
        parts.append("Existing beats:")
        parts.extend(f"- {b}" for b in beats)
    return "\n".join(parts)


def _bible_snippets(paths) -> str:
    if not paths:
        return ""
    bible = story_bible.read(paths["bible"])
    lines = []
    for key, label in (("genreTone", "Genre & tone"), ("styleNotes", "Style")):
        val = (bible.get(key) or "").strip()
        if val:
            lines.append(f"{label}: {val[:400]}")
    return "\n".join(lines)


def _character_names(paths) -> list[str]:
    if not paths:
        return []
    book = lore.read(paths["lore"])
    names = []
    for entry in book.get("characters") or []:
        name = (entry.get("name") or "").strip()
        if name:
            names.append(name)
    return names


def _scored_lore_block(paths, query: str, max_cards: int = 8) -> str:
    if not paths:
        return ""
    entries = story_context.rank_active_lore(
        paths, query, inject_mode="smart", max_cards=max_cards)
    return story_context._lore_summary(entries)


def parse_scene_lines(text: str) -> list[str]:
    """Turn model output into one beat per line."""
    out = []
    seen = set()
    for raw in str(text or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("```"):
            continue
        if re.match(r"^#{1,6}\s+", line):
            continue
        if re.match(r"^(scenes?|beats?)\s*:?\s*$", line, re.I):
            continue
        line = _SCENE_LINE_RE.sub("", line).strip()
        line = line.strip("\"'`")
        if not line:
            continue
        key = line.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(line)
    return out


def write_chapter_beats(paths, chapter_id: str, beats, summary: str | None = None) -> dict:
    """Save beats to outlines.json, leaving summary unchanged unless given."""
    current = _chapter_outline(paths, chapter_id)
    clean = []
    for beat in beats or []:
        text = _beat_text(beat)
        if text:
            clean.append(text)
    outline.write_chapter(paths["outlines"], chapter_id, {
        "summary": current["summary"] if summary is None else (summary or ""),
        "beats": clean,
    })
    return {"summary": current["summary"] if summary is None else (summary or ""),
            "beats": clean}


def _plot_persona() -> dict:
    for persona in personas.PERSONAS:
        if persona.get("key") == "quest_architect":
            return persona
    return {
        "key": "quest_architect",
        "display_name": "Plot Designer",
        "model_key": "operator",
        "temperature": 0.6,
        "system_prompt": "",
    }


def build_generate_scenes_prompts(
        paths, chapter_id: str, extra: str = "", pov: str = "",
        tense: str = "", perspective: str = "",
        parking: str | None = None) -> tuple[str, str]:
    """System + user prompts for Generate Scenes (plain beat lines)."""
    chapter = _chapter_outline(paths, chapter_id)
    dump = parking if parking is not None else read_parking_lot(paths)
    query = " ".join(filter(None, [
        chapter.get("summary") or "",
        " ".join(_beat_text(b) for b in (chapter.get("beats") or [])),
        dump,
        extra,
    ]))
    lore_txt = _scored_lore_block(paths, query)
    bible_txt = _bible_snippets(paths)
    persona = _plot_persona()
    system = (
        (persona.get("system_prompt") or "").strip()
        + "\n\nYou are listing chapter scenes/beats for a novelist. "
        "Output ONLY plain lines — one beat per line. No numbering required, "
        "no headers, no commentary, no canon markers."
    ).strip()
    parts = ["Write 6–12 scene beats for this chapter."]
    outline_txt = format_outline_block(chapter)
    if outline_txt:
        parts.append("CHAPTER OUTLINE:\n" + outline_txt)
    if dump.strip():
        parts.append("BRAIN DUMP (Focus research — not canon):\n" + dump.strip())
    if lore_txt.strip():
        parts.append("RELEVANT LORE:\n" + lore_txt.strip())
    if bible_txt.strip():
        parts.append(bible_txt.strip())
    craft = []
    if pov.strip():
        craft.append("POV: " + pov.strip())
    if perspective.strip():
        craft.append("Perspective character: " + perspective.strip())
    if tense.strip():
        craft.append("Tense: " + tense.strip())
    if extra.strip():
        craft.append("Extra instructions: " + extra.strip())
    if craft:
        parts.append("\n".join(craft))
    setting = ""
    if paths:
        setting = worldcontext.assemble(paths) or ""
    if setting.strip():
        parts.append(setting.strip()[:2500])
    parts.append(
        "Output one beat per line. Each beat is a concrete action or turn "
        "(who does what, where). Do not write prose paragraphs.")
    return system, "\n\n".join(parts)


def stream_generate_scenes(
        engine, paths, chapter_id: str, extra: str = "", pov: str = "",
        tense: str = "", perspective: str = "", parking: str | None = None):
    """Yield text deltas for Generate Scenes."""
    system, user = build_generate_scenes_prompts(
        paths, chapter_id, extra=extra, pov=pov, tense=tense,
        perspective=perspective, parking=parking)
    persona = _plot_persona()
    yield from engine.stream_prompt(
        persona.get("model_key") or "operator", system, user,
        temperature=persona.get("temperature") or 0.6,
        max_tokens=900, show_think=False)


def build_plan_draft_direction(
        beats, extra: str = "", pov: str = "", tense: str = "",
        perspective: str = "") -> str:
    """Single-pass Write direction covering every scene."""
    lines = [_beat_text(b) for b in (beats or [])]
    lines = [b for b in lines if b]
    if not lines:
        return extra.strip()
    numbered = "\n".join(f"{i + 1}. {beat}" for i, beat in enumerate(lines))
    parts = [
        "Write the next passage covering ALL of these scenes in order as one "
        "continuous draft (not a list). Do not skip a scene; do not add a "
        "heading per scene.",
        numbered,
    ]
    craft = []
    if pov.strip():
        craft.append("Point of view: " + pov.strip())
    if perspective.strip():
        craft.append("Perspective character: " + perspective.strip())
    if tense.strip():
        craft.append("Tense: " + tense.strip())
    if extra.strip():
        craft.append(extra.strip())
    if craft:
        parts.append(" ".join(craft) if len(craft) == 1 else "\n".join(craft))
    return "\n\n".join(parts)
