"""Outline CRUD - ported from unblocker's src/outline.js.

outlines.json stores a per-chapter outline keyed by chapter id:
    {"chapters": {"<chapterId>": {"beats": [...], "summary": "..."}}}
Plus an optional top-level "global" outline for the whole work.
"""

import json
import os
from datetime import datetime, timezone


def _now():
    return datetime.now(timezone.utc).isoformat()


DEFAULT = {"global": {"summary": "", "beats": []}, "chapters": {}}


def read_all(outline_path):
    try:
        with open(outline_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return dict(DEFAULT)
    if not isinstance(data.get("chapters"), dict):
        data["chapters"] = {}
    if not isinstance(data.get("global"), dict):
        data["global"] = {"summary": "", "beats": []}
    return data


def write_all(outline_path, data):
    os.makedirs(os.path.dirname(outline_path), exist_ok=True)
    data["updatedAt"] = _now()
    with open(outline_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    return data


def read_chapter(outline_path, chapter_id):
    return read_all(outline_path)["chapters"].get(
        chapter_id, {"beats": [], "summary": ""})


def write_chapter(outline_path, chapter_id, outline):
    data = read_all(outline_path)
    data["chapters"][chapter_id] = {
        "beats": outline.get("beats", []),
        "summary": outline.get("summary", ""),
    }
    return write_all(outline_path, data)


def write_global(outline_path, outline):
    data = read_all(outline_path)
    data["global"] = {
        "beats": outline.get("beats", []),
        "summary": outline.get("summary", ""),
    }
    return write_all(outline_path, data)
