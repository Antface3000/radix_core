"""Story Bible CRUD - ported from unblocker's src/storyBible.js.

The story bible defines the *setting* for a project: premise, genre/tone,
themes, world rules, and style notes. This (plus pinned lore + world state) is
what makes the agents genre-agnostic - the world comes from here, not from a
hardcoded persona prompt.
"""

import json
import os
from datetime import datetime, timezone


def _now():
    return datetime.now(timezone.utc).isoformat()


EMPTY = {
    "premise": "",
    "logline": "",
    "genreTone": "",
    "themes": [],
    "worldRules": "",
    "styleNotes": "",
    "pointOfView": "",
    "tense": "",
    "synopsis": "",
    "updatedAt": None,
}


def _normalize(raw):
    raw = raw or {}
    themes = raw.get("themes")
    if isinstance(themes, str):
        themes = [t.strip() for t in themes.split(",") if t.strip()]
    elif not isinstance(themes, list):
        themes = []
    merged = {**EMPTY, **{k: v for k, v in raw.items() if k in EMPTY}}
    merged["themes"] = themes
    return merged


def read(bible_path):
    try:
        with open(bible_path, "r", encoding="utf-8") as f:
            return _normalize(json.load(f))
    except (OSError, json.JSONDecodeError):
        return dict(EMPTY)


def write(bible_path, data):
    os.makedirs(os.path.dirname(bible_path), exist_ok=True)
    normalized = _normalize(data)
    normalized["updatedAt"] = _now()
    with open(bible_path, "w", encoding="utf-8") as f:
        json.dump(normalized, f, indent=2, ensure_ascii=False)
    return normalized


def update(bible_path, patch):
    current = read(bible_path)
    current.update({k: v for k, v in (patch or {}).items()})
    return write(bible_path, current)
