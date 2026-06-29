"""SDXL/Pony booru-tag generation - ported from unblocker/sdxl-tagifier.js.

Converts scene prose into bracket-segment SDXL tags. Uses the radix_core engine
(local llama-cpp) instead of Ollama/Gemini; falls back to a heuristic if the LLM
is unavailable or returns junk. Results are LRU-cached.
"""

import hashlib
import json
import re
from collections import OrderedDict

_CACHE_MAX = 64
_cache = OrderedDict()


def _sha1(s):
    return hashlib.sha1(str(s).encode("utf-8")).hexdigest()


def sanitize_booru_tag(tag):
    t = str(tag or "").lower().strip()
    if not t:
        return ""
    t = re.sub(r"\s+", "_", t)
    t = re.sub(r"_+", "_", t)
    t = re.sub(r"[^\w_]", "", t)
    t = t.strip("_")
    if len(t) < 2 or len(t) > 60:
        return ""
    if not re.fullmatch(r"[a-z0-9_]+", t):
        return ""
    return t


def sanitize_tag_list(items, max_tags):
    out, seen = [], set()
    for item in (items or []):
        clean = sanitize_booru_tag(item)
        if not clean or clean in seen:
            continue
        seen.add(clean)
        out.append(clean)
        if len(out) >= max_tags:
            break
    return out


def _extract_json_object(text):
    raw = str(text or "").strip()
    if not raw:
        return None
    raw = re.sub(r"^```json\s*", "", raw, flags=re.I)
    raw = re.sub(r"^```\s*", "", raw)
    raw = re.sub(r"```$", "", raw)
    start, end = raw.find("{"), raw.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    return raw[start:end + 1]


def _heuristic_tags(prose):
    """Crude fallback: comma/space split into booru tags."""
    words = re.split(r"[,;|]+|\s+", str(prose or "").lower())
    tags = sanitize_tag_list(words, 14)
    return {"subject": tags[:8], "details": tags[8:12], "scene": tags[12:],
            "lighting": [], "engine": None, "fellBack": True}


_SYSTEM_PROMPT = "\n".join([
    "You convert prose into SDXL/Pony booru-style tags.",
    "Output STRICT JSON only (no markdown, no commentary).",
    "Return exactly this shape:",
    '{"subject":[],"details":[],"scene":[],"lighting":[]}',
    "",
    "Rules:",
    "- Each tag is 1-4 words, lowercase, spaces become underscores.",
    "- No sentences, no commas inside a tag, no quotes, no markdown fences.",
    "- No duplicates within or across arrays.",
    "- Do NOT include score tags (score_9..score_1).",
    "- subject = the main entity (e.g. 1girl, orange_cat, cell_phone).",
    "- details = clothing/material/distinguishing features.",
    "- scene = action + setting/activity.",
    "- lighting = time of day + lighting style.",
])


def tagify_scene(engine, prose, subject_kind="character", lore_context=""):
    """Return {subject, details, scene, lighting, fellBack}.

    `engine` is an AgentEngine (uses run_tool); if None, heuristic is used.
    """
    pro = str(prose or "").strip()
    if not pro:
        return {"subject": [], "details": [], "scene": [], "lighting": [],
                "engine": None, "fellBack": True}

    kind = str(subject_kind or "character").strip().lower()
    lore = str(lore_context or "").strip()[:500]
    cache_key = _sha1(f"{pro}|{kind}|{lore}")
    if cache_key in _cache:
        _cache.move_to_end(cache_key)
        return _cache[cache_key]

    if engine is None:
        result = _heuristic_tags(pro)
    else:
        user = "\n".join([f"Subject kind: {kind}",
                          f"Lore context: {lore or '(none)'}", "", "PROSE:", pro])
        try:
            text = engine.run_tool(_SYSTEM_PROMPT, user, model_key="operator",
                                   temperature=0.2, max_tokens=600)
            json_str = _extract_json_object(text)
            data = json.loads(json_str) if json_str else None
            if not isinstance(data, dict):
                raise ValueError("non-JSON payload")
            result = {
                "subject": sanitize_tag_list(data.get("subject"), 14),
                "details": sanitize_tag_list(data.get("details"), 10),
                "scene": sanitize_tag_list(data.get("scene"), 12),
                "lighting": sanitize_tag_list(data.get("lighting"), 8),
                "engine": "radix-core",
                "fellBack": False,
            }
        except Exception:
            result = _heuristic_tags(pro)

    _cache[cache_key] = result
    if len(_cache) > _CACHE_MAX:
        _cache.popitem(last=False)
    return result
