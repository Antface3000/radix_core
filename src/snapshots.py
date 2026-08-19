"""Timed chapter snapshots, crash recovery, and folder backups."""

from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timezone

from src import chapters, projects


def _now_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def snapshots_dir(paths) -> str:
    path = os.path.join(paths["root"], "snapshots")
    os.makedirs(path, exist_ok=True)
    return path


def take_snapshot(paths, chapter_id: str, content: str, reason: str = "auto") -> str:
    folder = os.path.join(snapshots_dir(paths), chapter_id)
    os.makedirs(folder, exist_ok=True)
    stamp = _now_stamp()
    body_path = os.path.join(folder, f"{stamp}.txt")
    meta_path = os.path.join(folder, f"{stamp}.json")
    with open(body_path, "w", encoding="utf-8") as fh:
        fh.write(content or "")
    projects.write_json(meta_path, {
        "chapterId": chapter_id,
        "reason": reason,
        "chars": len(content or ""),
        "createdAt": datetime.now(timezone.utc).isoformat(),
    })
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
        meta = projects.read_json_safe(os.path.join(folder, name), {})
        stamp = name[:-5]
        txt = os.path.join(folder, stamp + ".txt")
        meta["stamp"] = stamp
        meta["path"] = txt
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
    """Copy the project root into dest_dir/<name>-<stamp>/."""
    stamp = _now_stamp()
    name = os.path.basename(paths["root"].rstrip("\\/")) or "project"
    target = os.path.join(dest_dir, f"{name}-{stamp}")
    shutil.copytree(paths["root"], target, dirs_exist_ok=False)
    return target


def _prune(folder: str, keep: int) -> None:
    stamps = sorted(
        {n[:-5] for n in os.listdir(folder) if n.endswith(".txt")},
        reverse=True)
    for stamp in stamps[keep:]:
        for ext in (".txt", ".json"):
            path = os.path.join(folder, stamp + ext)
            if os.path.exists(path):
                try:
                    os.remove(path)
                except OSError:
                    pass
