"""Timed chapter snapshots, crash recovery, and folder backups."""

from __future__ import annotations

import os
import re
import shutil
from datetime import datetime, timezone

from src import projects

# File / meta reason codes → UI wording
REASON_LABELS = {
    "auto": "Timed",
    "timed": "Timed",
    "manual": "Manual",
    "close": "On close",
    "on-close": "On close",
}

# Reason → filename slug (stable, sortable)
REASON_SLUGS = {
    "auto": "timed",
    "timed": "timed",
    "manual": "manual",
    "close": "on-close",
    "on-close": "on-close",
}

# New files: 2026-09-06_215806__timed
# Legacy:    20260906-015806
_STAMP_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2}_\d{6}(?:__[a-z0-9-]+)?|\d{8}-\d{6})$"
)


def _word_count(text: str) -> int:
    return len((text or "").split())


def _reason_slug(reason: str) -> str:
    key = (reason or "auto").strip().lower()
    return REASON_SLUGS.get(key, re.sub(r"[^a-z0-9-]+", "-", key).strip("-") or "timed")


def _now_stamp(reason: str = "auto") -> str:
    """Local-time stamp with reason: 2026-09-06_215806__timed."""
    local = datetime.now().astimezone()
    return f"{local.strftime('%Y-%m-%d_%H%M%S')}__{_reason_slug(reason)}"


def _parse_created(meta: dict) -> datetime | None:
    raw = meta.get("createdAt") or ""
    if raw:
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            return dt.astimezone()
        except ValueError:
            pass
    stamp = meta.get("stamp") or ""
    for fmt in ("%Y-%m-%d_%H%M%S", "%Y%m%d-%H%M%S"):
        head = stamp.split("__", 1)[0]
        try:
            return datetime.strptime(head, fmt).astimezone()
        except ValueError:
            continue
    return None


def format_snapshot_label(meta: dict) -> str:
    """Human list label, e.g. 'Timed · Sep 6, 2026 · 9:58 PM · 1,204 words'."""
    reason_key = (meta.get("reason") or "auto").strip().lower()
    reason = REASON_LABELS.get(reason_key, meta.get("reason") or "Snapshot")
    title = (meta.get("title") or "").strip()
    when = _parse_created(meta)
    if when:
        time_bit = (
            f"{when.strftime('%b')} {when.day}, {when.year} · "
            f"{when.strftime('%I:%M %p').lstrip('0')}"
        )
    else:
        time_bit = meta.get("stamp") or "unknown time"

    parts = [reason]
    if title:
        parts.append(f'"{title}"')
    parts.append(time_bit)
    words = meta.get("words")
    if words is None and meta.get("chars") is not None:
        try:
            words = max(0, int(meta["chars"]) // 5)
        except (TypeError, ValueError):
            words = None
    if isinstance(words, int):
        parts.append(f"{words:,} words")
    return " · ".join(parts)


def snapshots_dir(paths) -> str:
    path = os.path.join(paths["root"], "snapshots")
    os.makedirs(path, exist_ok=True)
    return path


def take_snapshot(
    paths,
    chapter_id: str,
    content: str,
    reason: str = "auto",
    *,
    title: str = "",
    chapter_name: str = "",
) -> str:
    folder = os.path.join(snapshots_dir(paths), chapter_id)
    os.makedirs(folder, exist_ok=True)
    stamp = _now_stamp(reason)
    body_path = os.path.join(folder, f"{stamp}.txt")
    meta_path = os.path.join(folder, f"{stamp}.json")
    text = content or ""
    with open(body_path, "w", encoding="utf-8") as fh:
        fh.write(text)
    reason_code = {
        "auto": "timed",
        "timed": "timed",
        "manual": "manual",
        "close": "on-close",
        "on-close": "on-close",
    }.get((reason or "timed").strip().lower(), _reason_slug(reason))
    meta = {
        "chapterId": chapter_id,
        "reason": reason_code,
        "chars": len(text),
        "words": _word_count(text),
        "createdAt": datetime.now().astimezone().isoformat(),
        "stamp": stamp,
    }
    if title.strip():
        meta["title"] = title.strip()[:80]
    if chapter_name.strip():
        meta["chapterName"] = chapter_name.strip()[:120]
    projects.write_json(meta_path, meta)
    _prune(folder, keep=40)
    return body_path


def list_snapshots(paths, chapter_id: str) -> list[dict]:
    folder = os.path.join(snapshots_dir(paths), chapter_id)
    if not os.path.isdir(folder):
        return []
    items = []
    for name in sorted(os.listdir(folder), reverse=True):
        if not name.endswith(".json"):
            continue
        stamp = name[:-5]
        if not _STAMP_RE.match(stamp):
            continue
        meta = projects.read_json_safe(os.path.join(folder, name), {}) or {}
        txt = os.path.join(folder, stamp + ".txt")
        meta["stamp"] = stamp
        meta["path"] = txt
        meta["label"] = format_snapshot_label(meta)
        items.append(meta)
    return items


def read_snapshot(paths, chapter_id: str, stamp: str) -> str:
    path = os.path.join(snapshots_dir(paths), chapter_id, f"{stamp}.txt")
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def write_crash_buffer(paths, chapter_id: str, content: str) -> None:
    path = os.path.join(snapshots_dir(paths), "crash_buffer.json")
    projects.write_json(path, {
        "chapterId": chapter_id,
        "content": content or "",
        "savedAt": datetime.now(timezone.utc).isoformat(),
    })


def load_crash_buffer(paths) -> dict | None:
    path = os.path.join(snapshots_dir(paths), "crash_buffer.json")
    data = projects.read_json_safe(path, None)
    return data if isinstance(data, dict) and data.get("chapterId") else None


def clear_crash_buffer(paths) -> None:
    path = os.path.join(snapshots_dir(paths), "crash_buffer.json")
    if os.path.exists(path):
        try:
            os.remove(path)
        except OSError:
            pass


def backup_project_to(paths, dest_dir: str) -> str:
    """Copy the project root into dest_dir/<name>-YYYY-MM-DD_HHMMSS/."""
    stamp = datetime.now().astimezone().strftime("%Y-%m-%d_%H%M%S")
    name = os.path.basename(paths["root"].rstrip("\\/")) or "project"
    target = os.path.join(dest_dir, f"{name}-{stamp}")
    shutil.copytree(paths["root"], target, dirs_exist_ok=False)
    return target


def _prune(folder: str, keep: int) -> None:
    stamps = sorted(
        {n[:-5] for n in os.listdir(folder)
         if n.endswith(".txt") and _STAMP_RE.match(n[:-5])},
        reverse=True)
    for stamp in stamps[keep:]:
        for ext in (".txt", ".json"):
            path = os.path.join(folder, stamp + ext)
            if os.path.exists(path):
                try:
                    os.remove(path)
                except OSError:
                    pass
