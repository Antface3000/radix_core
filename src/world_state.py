"""World State CRUD - ported from unblocker's src/worldState.js.

World state tracks the *current* mutable situation of the world: timeline beats,
faction standings, ongoing events, and free-form facts that evolve as the story
progresses. Agents read this so "now" stays consistent across turns.
"""

import json
import os
from datetime import datetime, timezone


def _now():
    return datetime.now(timezone.utc).isoformat()


DEFAULT_STATE = {
    "currentDate": "",
    "currentLocation": "",
    "scene": "",
    "timeline": [],
    "factions": [],
    "ongoingEvents": [],
    "facts": [],
    "updatedAt": None,
}


def _normalize(raw):
    raw = raw or {}
    merged = {**DEFAULT_STATE, **{k: v for k, v in raw.items()
                                  if k in DEFAULT_STATE}}
    for key in ("timeline", "factions", "ongoingEvents", "facts"):
        if not isinstance(merged.get(key), list):
            merged[key] = []
    return merged


def read(state_path):
    try:
        with open(state_path, "r", encoding="utf-8") as f:
            return _normalize(json.load(f))
    except (OSError, json.JSONDecodeError):
        return dict(DEFAULT_STATE)


def write(state_path, data):
    os.makedirs(os.path.dirname(state_path), exist_ok=True)
    normalized = _normalize(data)
    normalized["updatedAt"] = _now()
    with open(state_path, "w", encoding="utf-8") as f:
        json.dump(normalized, f, indent=2, ensure_ascii=False)
    return normalized


def update(state_path, patch):
    current = read(state_path)
    current.update({k: v for k, v in (patch or {}).items()})
    return write(state_path, current)


def add_fact(state_path, fact):
    current = read(state_path)
    text = str(fact or "").strip()
    if text:
        current["facts"].append(text)
        return write(state_path, current)
    return current
