"""Staged canon capture queue — review before anything is written.

When `context.capture_review` is on, agent captures land here instead of
being written directly to lore.json / story_bible.json / world_state.json.
Approving an item replays it through the same write helpers the direct
path uses (`worldcontext.apply_*_capture`).
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone

from src import worldcontext
from src.logutil import get_logger

log = get_logger("capture_queue")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class CaptureQueue:
    """Per-project JSON list of pending capture items."""

    def __init__(self, paths):
        self.paths = paths
        self.path = paths["capture_queue"]

    # ----------------------- storage ---------------------------------------
    def load(self) -> list[dict]:
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, list) else []
        except (OSError, json.JSONDecodeError):
            return []

    def _save(self, items: list[dict]) -> None:
        parent = os.path.dirname(self.path)
        if parent and not os.path.exists(parent):
            os.makedirs(parent, exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump(items, fh, indent=2, ensure_ascii=False)

    def count(self) -> int:
        return len(self.load())

    # ----------------------- staging ---------------------------------------
    def stage(self, kind: str, payload: dict, mode: str = "merge",
              source: str = "agent") -> dict:
        """Append one pending item. Signature matches worldcontext's hook."""
        item = {
            "id": uuid.uuid4().hex[:12],
            "kind": kind,                # lore | bible | world_state
            "payload": payload,
            "mode": mode,
            "source": source,
            "timestamp": _now(),
        }
        items = self.load()
        items.append(item)
        self._save(items)
        return item

    # ----------------------- review actions --------------------------------
    def approve(self, item_id: str) -> dict | None:
        """Write one pending item to canon and remove it from the queue."""
        items = self.load()
        target = next((i for i in items if i.get("id") == item_id), None)
        if target is None:
            return None
        self._apply(target)
        self._save([i for i in items if i.get("id") != item_id])
        return target

    def approve_all(self) -> int:
        items = self.load()
        applied = 0
        for item in items:
            try:
                self._apply(item)
                applied += 1
            except Exception:
                log.exception("Capture approve failed: %s", item.get("id"))
        self._save([])
        return applied

    def discard(self, item_id: str) -> bool:
        items = self.load()
        remaining = [i for i in items if i.get("id") != item_id]
        if len(remaining) == len(items):
            return False
        self._save(remaining)
        return True

    def clear(self) -> None:
        self._save([])

    def _apply(self, item: dict) -> None:
        kind = item.get("kind")
        payload = item.get("payload") or {}
        mode = item.get("mode", "merge")
        source = item.get("source", "agent")
        if kind == "lore":
            worldcontext.apply_lore_capture(self.paths, payload, mode, source)
        elif kind == "bible":
            worldcontext.apply_bible_capture(
                self.paths, payload.get("field"), payload.get("body", ""),
                mode, source)
        elif kind == "world_state":
            worldcontext.apply_world_capture(
                self.paths, payload.get("field"), payload.get("body", ""),
                mode, source)
        else:
            log.warning("Unknown capture kind: %r", kind)


def describe_item(item: dict) -> str:
    """One-line label for the review UI."""
    kind = item.get("kind", "?")
    payload = item.get("payload") or {}
    source = item.get("source", "agent")
    if kind == "lore":
        name = payload.get("name", "?")
        etype = payload.get("entryType") or payload.get("type") or "lore"
        return f"[Lore/{etype}] {name}  —  from {source}"
    field = payload.get("field", "?")
    label = "Bible" if kind == "bible" else "World State"
    return f"[{label}] {field}  —  from {source}"


def item_preview(item: dict, max_chars: int = 600) -> str:
    """Body text preview for the review UI."""
    payload = item.get("payload") or {}
    if item.get("kind") == "lore":
        text = payload.get("notes") or payload.get("body") or ""
        extras = [f"{k}: {v}" for k, v in payload.items()
                  if k not in ("notes", "body", "name") and v]
        if extras:
            text = text + ("\n" if text else "") + "\n".join(extras)
    else:
        text = payload.get("body", "")
    text = (text or "").strip()
    if len(text) > max_chars:
        text = text[:max_chars] + "…"
    return text
