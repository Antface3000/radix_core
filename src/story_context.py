"""story_context - assemble LLM context for the editor's AI actions.

Ported in spirit from unblocker's renderer/story-context.js. Builds the layered
prompt context (Story Bible + Chapter Outline + scored Lorebook + World State +
Author's Note + the prose so far) and the Write / Brainstorm / Chat prompts.
The same lore scoring drives the editor's live "active lore" auto-scan.

All functions are pure given the project `paths` dict (from projects.project_paths)
so they are easy to call from the GUI thread or a worker thread.
"""

import re

import config
from src import story_bible, outline, lore, world_state
from src.worldcontext import format_bible

DEFAULT_WRITE_SYSTEM = (
    "You are a skilled ghostwriter continuing a work of fiction. Write vivid, "
    "publishable prose that flows naturally from where the manuscript stops. "
    "Match the established voice, tense, and point of view. Honor the SETTING, "
    "LOREBOOK, OUTLINE, and AUTHOR'S NOTE as ground truth. Do not summarize, "
    "explain, or address the reader - only produce the next passage of the "
    "story. Never repeat, paraphrase, or quote sentences from STORY SO FAR. "
    "Each sentence must advance the scene with new action, detail, or dialogue."
)

_NEUTRAL_VOICE = ("Write clear, grounded literary prose. Vary sentence rhythm; "
                  "avoid cliche and purple excess.")

# Budgets (characters).
_BIBLE_CHARS = 2400
_OUTLINE_CHARS = 1000
_LORE_CHARS = 2200
_AUTHOR_CHARS = 800
_RECENT_SCAN_CHARS = 1600
_PREVIOUSLY_CHARS = 1200


# ======================= lore scoring / selection ==========================
def _entry_keywords(entry):
    words = list(entry.get("keywords") or [])
    if entry.get("name"):
        words.append(entry["name"])
    words.extend(entry.get("aliases") or [])
    return [w.lower() for w in words if w]


def _keyword_hits(keyword: str, text_lower: str, match_mode: str = "substring") -> bool:
    kw = (keyword or "").strip()
    if not kw:
        return False
    if match_mode == "word_boundary":
        return bool(re.search(r"\b" + re.escape(kw.lower()) + r"\b", text_lower))
    if match_mode == "regex":
        if kw.startswith("/") and kw.endswith("/") and len(kw) > 2:
            pattern = kw[1:-1]
        else:
            pattern = re.escape(kw.lower())
        try:
            return bool(re.search(pattern, text_lower, re.IGNORECASE))
        except re.error:
            return kw.lower() in text_lower
    return kw.lower() in text_lower


def score_lore_entry(entry, recent_lower, match_mode: str = "substring"):
    """Higher = more relevant to the recent text. Mirrors unblocker weights."""
    hits = 0
    for kw in set(_entry_keywords(entry)):
        if _keyword_hits(kw, recent_lower, match_mode):
            hits += 1
    score = hits * 14
    if entry.get("alwaysInclude"):
        score += 25
    if entry.get("pinned"):
        score += 20
    score += int(entry.get("priority") or 0) * 6
    return score, hits


def rank_active_lore(
        paths, recent_text, inject_mode="smart", max_cards=5,
        match_mode="substring"):
    """Return lore entries relevant to `recent_text`, scored + ordered."""
    recent_lower = (recent_text or "").lower()
    book = lore.read(paths["lore"])
    entries = book["characters"] + book["world"]
    scored = []
    for e in entries:
        score, hits = score_lore_entry(e, recent_lower, match_mode)
        scored.append((score, hits, e))

    always = [t for t in scored if t[2].get("alwaysInclude") or t[2].get("pinned")]
    hitting = [t for t in scored if t[1] > 0 and t not in always]
    hitting.sort(key=lambda t: t[0], reverse=True)
    always.sort(key=lambda t: t[0], reverse=True)

    if inject_mode == "alwaysIncludeOnly":
        chosen = always
    elif inject_mode == "pinnedAndActive":
        chosen = always + hitting
    else:  # smart
        chosen = always + hitting[:max_cards]
    return [t[2] for t in chosen]


def _lore_body(entry) -> str:
    et = entry.get("entryType") or "character"
    parts = []
    if et == "creature" and entry.get("creatureType"):
        parts.append(f"Type: {entry['creatureType']}")
    for key in ("role", "appearance", "goals", "powers", "history", "notes",
                "territory", "climate", "when", "outcome", "origin"):
        val = (entry.get(key) or "").strip()
        if val:
            parts.append(val.replace("\n", " ")[:200])
    return " · ".join(parts[:3])


def _lore_summary(entries, max_chars=_LORE_CHARS):
    from src import lore_types
    lines = []
    for e in entries:
        et = e.get("entryType") or "character"
        kind = lore_types.ENTRY_TYPE_LABELS.get(et, et.title())
        body = _lore_body(e)
        line = f"- [{kind}] {e.get('name')}"
        if body:
            line += f": {body}"
        lines.append(line)
    text = "\n".join(lines)
    return text[:max_chars]


# ======================= section builders ==================================
def _bible_block(paths, max_chars=_BIBLE_CHARS):
    b = story_bible.read(paths["bible"])
    return format_bible(b, max_chars=max_chars)


def _outline_block(paths, chapter_id, max_chars=_OUTLINE_CHARS):
    if not chapter_id:
        return ""
    o = outline.read_chapter(paths["outlines"], chapter_id)
    parts = []
    if o.get("summary"):
        parts.append("Synopsis: " + o["summary"])
    beats = o.get("beats") or []
    if beats:
        parts.append("Beats:")
        for beat in beats:
            text = beat.get("text") if isinstance(beat, dict) else str(beat)
            if text:
                parts.append(f"- {text}")
    return "\n".join(parts)[:max_chars]


def _previously_block(paths, chapter_id, max_chars=_PREVIOUSLY_CHARS):
    if not chapter_id or "chapter_summaries" not in paths:
        return ""
    try:
        from src import chapter_summaries
        return chapter_summaries.previously_block(
            paths, chapter_id, max_chars=max_chars)
    except Exception:
        return ""


def _world_block(paths):
    w = world_state.read(paths["world_state"])
    lines = []
    if w.get("currentDate"):
        lines.append(f"Date: {w['currentDate']}")
    if w.get("currentLocation"):
        lines.append(f"Location: {w['currentLocation']}")
    if w.get("scene"):
        lines.append(f"Scene: {w['scene']}")
    facts = w.get("facts") or []
    for f in facts[:6]:
        lines.append(f"- {f}")
    return "\n".join(lines)


# ======================= context assembly ==================================
def build_story_context(paths, before_cursor="", chapter_id=None, author_note="",
                        inject_mode="smart", max_cards=5, total_chars=8000,
                        use_retrieval=False):
    """Assemble the labeled context body for a Write generation.

    Returns dict: {"text": <str>, "lore": [entries]}.
    """
    recent = (before_cursor or "")[-_RECENT_SCAN_CHARS:]
    active_lore = rank_active_lore(paths, recent, inject_mode, max_cards)

    sections = []
    bible = _bible_block(paths)
    if bible:
        sections.append("=== STORY BIBLE ===\n" + bible)
    outline_txt = _outline_block(paths, chapter_id)
    if outline_txt:
        sections.append("=== CHAPTER OUTLINE ===\n" + outline_txt)
    previously = _previously_block(paths, chapter_id)
    if previously:
        sections.append("=== PREVIOUSLY (earlier chapters) ===\n" + previously)
    if use_retrieval:
        try:
            from src import retrieval
            retrieved = retrieval.previously_from_retrieval(
                paths, recent or author_note or "story", max_chars=1200)
            if retrieved:
                sections.append("=== RETRIEVED CONTEXT ===\n" + retrieved)
        except Exception:
            pass
    lore_txt = _lore_summary(active_lore)
    if lore_txt:
        sections.append("=== LOREBOOK (relevant entries) ===\n" + lore_txt)
    world_txt = _world_block(paths)
    if world_txt:
        sections.append("=== WORLD STATE ===\n" + world_txt)
    if author_note:
        sections.append("=== AUTHOR'S NOTE (obey) ===\n"
                        + str(author_note)[:_AUTHOR_CHARS])

    head = "\n\n".join(sections)
    # Reserve the remaining budget for the prose so far.
    remaining = max(800, total_chars - len(head))
    story_so_far = (before_cursor or "").strip()[-remaining:]
    if story_so_far:
        head += "\n\n=== STORY SO FAR ===\n" + story_so_far

    return {"text": head, "lore": active_lore}


def build_write_prompt(context_text, voice_preset="my", style_my="",
                       style_alt="", direction="", system_override=""):
    system = system_override or DEFAULT_WRITE_SYSTEM
    if voice_preset == "my" and style_my.strip():
        system += "\n\nVOICE / STYLE (write in this voice):\n" + style_my.strip()
    elif voice_preset == "alt" and style_alt.strip():
        system += "\n\nVOICE / STYLE (write in this voice):\n" + style_alt.strip()
    elif voice_preset == "neutral":
        system += "\n\nVOICE / STYLE:\n" + _NEUTRAL_VOICE

    user = context_text + "\n\nContinue the narrative naturally from the end of "
    user += "STORY SO FAR. Write the next passage only — new prose that moves "
    user += "the scene forward."
    user += (
        "\n\nRULES: Do not repeat or lightly rephrase lines from STORY SO FAR. "
        "Do not restate the same beat twice. Stop when the passage feels complete "
        "rather than padding length."
    )
    if direction.strip():
        user += "\n\nOPTIONAL DIRECTION (incorporate): " + direction.strip()
    return system, user


def _strip_story_overlap(story_tail: str, draft: str) -> str:
    """Remove draft text that duplicates the end of the manuscript."""
    story = (story_tail or "").strip()
    text = (draft or "").strip()
    if not story or not text:
        return text
    max_chars = min(len(story), len(text), 600)
    for n in range(max_chars, 8, -1):
        if story[-n:].lower() == text[:n].lower():
            return text[n:].lstrip()
    story_words = story.split()
    draft_words = text.split()
    max_words = min(len(story_words), len(draft_words), 80)
    for n in range(max_words, 4, -1):
        if [w.lower() for w in story_words[-n:]] == [w.lower() for w in draft_words[:n]]:
            return " ".join(draft_words[n:]).lstrip()
    return text


def _strip_self_repetition(text: str) -> str:
    """Truncate when the model loops by repeating earlier paragraphs or halves."""
    t = (text or "").strip()
    if len(t) < 180:
        return t
    parts = re.split(r"\n\s*\n+", t)
    seen: set[str] = set()
    kept: list[str] = []
    for part in parts:
        norm = " ".join(part.split()).lower()
        if len(norm) >= 40 and norm in seen:
            break
        if len(norm) >= 40:
            seen.add(norm)
        kept.append(part)
    trimmed = "\n\n".join(kept).strip()
    if len(trimmed) < len(t) * 0.92:
        t = trimmed
    half = len(t) // 2
    lower = t.lower()
    for size in range(min(half, 500), 80, -15):
        chunk = lower[:size]
        idx = lower.find(chunk, max(size // 2, 40))
        if idx >= 40:
            return t[:idx].strip()
    return t


def build_brainstorm_prompt(recent_text, selection="", instruction=""):
    """Freeform idea prompt; no system prompt (mirrors unblocker)."""
    if selection.strip():
        prompt = (
            "I'm writing a story. Recent context:\n\n"
            f"\"{recent_text.strip()[-2000:]}\"\n\n"
            f"Selected passage: \"{selection.strip()}\"\n\n"
            "Give me 3 specific, creative continuations or ideas for this scene. "
            "Match the tone. Each should be 2-3 sentences and actionable.")
    else:
        prompt = (
            "I'm writing a story. Recent progress:\n\n"
            f"\"{recent_text.strip()[-2000:]}\"\n\n"
            "Give me 3 creative directions this could go next. Match the tone. "
            "Each should be 2-3 sentences and actionable.")
    if instruction.strip():
        prompt += "\n\nAdditional writer instructions: " + instruction.strip()
    return prompt


def build_chat_system(paths, manuscript_text="", chapter_id=None,
                      author_note="", max_chars=10000,
                      persona_system_prompt=""):
    """System prompt for the project-aware Chat: the entire project as context."""
    ctx = build_story_context(paths, before_cursor="", chapter_id=chapter_id,
                              author_note=author_note, inject_mode="pinnedAndActive",
                              max_cards=40, total_chars=max_chars)
    manuscript = (manuscript_text or "").strip()
    budget = max(1000, max_chars - len(ctx["text"]))
    if manuscript:
        manuscript = manuscript[-budget:]
    role = (persona_system_prompt or "").strip()
    if role:
        system = (
            role + "\n\n"
            "You have the full project context below (story bible, outline, lorebook, "
            "world state, author's note, and the manuscript). Discuss the project "
            "conversationally: plot, characters, pacing, consistency, ideas, and "
            "questions. Do NOT write new prose for the manuscript unless explicitly "
            "asked — this is a conversation about the work, not a continuation of it.\n\n"
            + ctx["text"])
    else:
        system = (
            "You are a thoughtful writing collaborator for this project. You have the "
            "full project context below (story bible, outline, lorebook, world state, "
            "author's note, and the manuscript). Discuss the project conversationally: "
            "plot, characters, pacing, consistency, ideas, and questions. Do NOT write "
            "new prose for the manuscript unless explicitly asked - this is a "
            "conversation about the work, not a continuation of it.\n\n"
            + ctx["text"])
    if manuscript:
        system += "\n\n=== MANUSCRIPT (current chapter) ===\n" + manuscript
    return system


def sanitize_write_output(text, story_tail=""):
    """Strip fences / wrapping quotes and overlap with the manuscript tail."""
    t = (text or "").strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else t.strip("`")
        if t.endswith("```"):
            t = t[:-3]
    t = t.strip()
    if len(t) > 1 and t[0] in "\"'" and t[-1] == t[0]:
        t = t[1:-1].strip()
    if story_tail:
        t = _strip_story_overlap(story_tail, t)
    t = _strip_self_repetition(t)
    return t
