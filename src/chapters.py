"""Chapter (manuscript) CRUD - ported from unblocker's chapter handling.

Chapters are plain-text files in the project's chapters/ folder. Order and
display names are tracked in chapters/_order.json:
    [{"id": "...", "name": "Chapter 1", "file": "chapter-1.txt"}, ...]
Drafts (alternate takes) can be stored as <id>.draft.json siblings.
"""

import json
import os
import re
import uuid

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slug(name):
    s = _SLUG_RE.sub("-", str(name or "chapter").lower()).strip("-")[:60]
    return s or "chapter"


def _order_path(chapters_dir):
    return os.path.join(chapters_dir, "_order.json")


def _read_order(chapters_dir):
    try:
        with open(_order_path(chapters_dir), "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def _write_order(chapters_dir, order):
    os.makedirs(chapters_dir, exist_ok=True)
    with open(_order_path(chapters_dir), "w", encoding="utf-8") as f:
        json.dump(order, f, indent=2, ensure_ascii=False)


def list_chapters(chapters_dir):
    return [{"id": c["id"], "name": c["name"]}
            for c in _read_order(chapters_dir)]


def _find(chapters_dir, chapter_id):
    return next((c for c in _read_order(chapters_dir)
                 if c["id"] == chapter_id), None)


def read(chapters_dir, chapter_id):
    meta = _find(chapters_dir, chapter_id)
    if not meta:
        raise ValueError("Chapter not found: " + str(chapter_id))
    path = os.path.join(chapters_dir, meta["file"])
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
    except OSError:
        content = ""
    return {"id": meta["id"], "name": meta["name"], "content": content}


def create(chapters_dir, name):
    os.makedirs(chapters_dir, exist_ok=True)
    order = _read_order(chapters_dir)
    name = str(name or "Untitled Chapter").strip() or "Untitled Chapter"
    chapter_id = str(uuid.uuid4())
    base = _slug(name)
    file_name = f"{base}-{chapter_id[:8]}.txt"
    with open(os.path.join(chapters_dir, file_name), "w", encoding="utf-8") as f:
        f.write("")
    meta = {"id": chapter_id, "name": name, "file": file_name}
    order.append(meta)
    _write_order(chapters_dir, order)
    return {"id": chapter_id, "name": name, "content": ""}


def write(chapters_dir, chapter_id, content):
    meta = _find(chapters_dir, chapter_id)
    if not meta:
        raise ValueError("Chapter not found: " + str(chapter_id))
    with open(os.path.join(chapters_dir, meta["file"]), "w",
              encoding="utf-8") as f:
        f.write(content or "")
    return True


def rename(chapters_dir, chapter_id, name):
    order = _read_order(chapters_dir)
    for meta in order:
        if meta["id"] == chapter_id:
            meta["name"] = str(name or meta["name"]).strip() or meta["name"]
            _write_order(chapters_dir, order)
            return True
    raise ValueError("Chapter not found: " + str(chapter_id))


def delete(chapters_dir, chapter_id):
    order = _read_order(chapters_dir)
    meta = next((c for c in order if c["id"] == chapter_id), None)
    if not meta:
        return False
    path = os.path.join(chapters_dir, meta["file"])
    if os.path.exists(path):
        try:
            os.remove(path)
        except OSError:
            pass
    _write_order(chapters_dir, [c for c in order if c["id"] != chapter_id])
    return True


def _draft_path(chapters_dir, chapter_id):
    return os.path.join(chapters_dir, f"{chapter_id}.draft.json")


def read_drafts(chapters_dir, chapter_id):
    """Pending AI draft-edit hunks for a chapter: [{id,note,start,length}]."""
    try:
        with open(_draft_path(chapters_dir, chapter_id), "r",
                  encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def write_drafts(chapters_dir, chapter_id, drafts):
    os.makedirs(chapters_dir, exist_ok=True)
    path = _draft_path(chapters_dir, chapter_id)
    if not drafts:
        if os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass
        return
    with open(path, "w", encoding="utf-8") as f:
        json.dump(drafts, f, indent=2, ensure_ascii=False)


def reorder(chapters_dir, ordered_ids):
    order = _read_order(chapters_dir)
    by_id = {c["id"]: c for c in order}
    new_order = [by_id[i] for i in ordered_ids if i in by_id]
    for c in order:  # keep any not mentioned, appended at end
        if c["id"] not in ordered_ids:
            new_order.append(c)
    _write_order(chapters_dir, new_order)
    return list_chapters(chapters_dir)
