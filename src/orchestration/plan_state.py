"""plan.json authority + Plan.md bidirectional sync."""

from __future__ import annotations

import json
import os
import re
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from src import projects

STATUS_SECTIONS = {
    "pending": "Pending",
    "in_progress": "In progress",
    "blocked": "Blocked",
    "done": "Done",
    "cancelled": "Cancelled",
}

SECTION_TO_STATUS = {v.lower(): k for k, v in STATUS_SECTIONS.items()}

_TASK_LINE = re.compile(
    r"^-\s+\[[ xX]\]\s+\*\*(task-[a-z0-9-]+)\*\*\s+\|\s+([^|]+)\s+\|\s+(.+)$"
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def empty_plan(title: str = "Working title") -> dict[str, Any]:
    return {
        "version": 1,
        "title": title,
        "updatedAt": _now(),
        "tasks": [],
        "meta": {"lastEventId": None, "paused": False},
    }


def new_task_id() -> str:
    return f"task-{uuid.uuid4().hex[:8]}"


class PlanStateStore:
    """Read/write plan.json and keep Plan.md in sync."""

    def __init__(self, project_id: str):
        self.project_id = project_id
        paths = projects.project_paths(project_id)
        self.json_path = paths["plan"]
        self.md_path = paths["plan_md"]
        self._data: dict[str, Any] | None = None
        self._snapshot: list[dict[str, Any]] | None = None

    def load(self) -> dict[str, Any]:
        if os.path.exists(self.json_path):
            with open(self.json_path, "r", encoding="utf-8") as fh:
                self._data = json.load(fh)
        else:
            project = projects.get_project(self.project_id)
            title = (project or {}).get("name", "Working title")
            self._data = empty_plan(title)
            self.save()
        if not os.path.exists(self.md_path):
            self.export_markdown()
        self._migrate_task_types()
        if self._snapshot is None:
            self._snapshot = deepcopy(self._data.get("tasks", []))
        return self._data

    def _migrate_task_types(self) -> None:
        from src.orchestration.task_types import normalize_task_type
        if self._data is None:
            return
        changed = False
        for task in self._data.get("tasks", []):
            old = task.get("type", "")
            new = normalize_task_type(old)
            if old != new:
                task["type"] = new
                changed = True
        if changed:
            self.save()
            self.export_markdown()

    def save(self) -> None:
        if self._data is None:
            return
        self._data["updatedAt"] = _now()
        projects.write_json(self.json_path, self._data)

    @property
    def data(self) -> dict[str, Any]:
        if self._data is None:
            self.load()
        return self._data  # type: ignore[return-value]

    def task_by_id(self, task_id: str) -> dict[str, Any] | None:
        for task in self.data.get("tasks", []):
            if task.get("id") == task_id:
                return task
        return None

    def upsert_task(self, task: dict[str, Any]) -> dict[str, Any]:
        tasks = self.data.setdefault("tasks", [])
        existing = self.task_by_id(task["id"])
        if existing:
            existing.update(task)
            merged = existing
        else:
            task.setdefault("createdAt", _now())
            task.setdefault("status", "pending")
            task.setdefault("priority", 10)
            task.setdefault("dependsOn", [])
            task.setdefault("assignee", None)
            task.setdefault("resultRef", None)
            task.setdefault("completedAt", None)
            tasks.append(task)
            merged = task
        self.save()
        self.export_markdown()
        return merged

    def complete_task(self, task_id: str, result_ref: str | None = None) -> None:
        task = self.task_by_id(task_id)
        if not task:
            return
        task["status"] = "done"
        task["completedAt"] = _now()
        if result_ref is not None:
            task["resultRef"] = result_ref
        self.save()
        self.export_markdown()

    def cancel_task(self, task_id: str) -> None:
        task = self.task_by_id(task_id)
        if not task:
            return
        task["status"] = "cancelled"
        self.save()
        self.export_markdown()

    def set_task_status(self, task_id: str, status: str) -> None:
        task = self.task_by_id(task_id)
        if not task:
            return
        task["status"] = status
        if status == "done":
            task["completedAt"] = _now()
        self.save()
        self.export_markdown()

    def diff_since(self, snapshot: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
        """Return tasks that are pending and were not pending in snapshot."""
        snap = snapshot if snapshot is not None else (self._snapshot or [])
        snap_ids = {t["id"] for t in snap if t.get("status") == "pending"}
        pending = []
        for task in self.data.get("tasks", []):
            if task.get("status") != "pending":
                continue
            if task["id"] not in snap_ids:
                pending.append(task)
            elif not any(
                s.get("id") == task["id"]
                and s.get("instruction") == task.get("instruction")
                for s in snap
            ):
                pending.append(task)
        return pending

    def emit_pending_events(self) -> list[dict[str, Any]]:
        """Mark snapshot and return newly pending tasks."""
        pending = self.diff_since()
        self._snapshot = deepcopy(self.data.get("tasks", []))
        return pending

    def export_markdown(self) -> str:
        data = self.data
        title = data.get("title", "Working title")
        lines = [
            f"# Plan: {title}",
            "",
            "> Auto-synced with plan.json. Edit task lines below; do not remove id: lines.",
            "",
        ]
        by_status: dict[str, list[dict]] = {k: [] for k in STATUS_SECTIONS}
        for task in data.get("tasks", []):
            status = task.get("status", "pending")
            if status == "cancelled":
                by_status.setdefault("cancelled", []).append(task)
            elif status in by_status:
                by_status[status].append(task)
            else:
                by_status["pending"].append(task)

        for status, heading in STATUS_SECTIONS.items():
            lines.append(f"## {heading}")
            lines.append("")
            for task in by_status.get(status, []):
                checked = "x" if status == "done" else " "
                lines.append(
                    f"- [{checked}] **{task['id']}** | {task.get('type', 'general')} | "
                    f"{task.get('title', 'Untitled')}"
                )
                instruction = (task.get("instruction") or "").strip()
                if instruction:
                    for part in instruction.splitlines():
                        lines.append(f"  {part}")
                lines.append("")
            if not by_status.get(status):
                lines.append("")

        text = "\n".join(lines).rstrip() + "\n"
        os.makedirs(os.path.dirname(self.md_path) or ".", exist_ok=True)
        with open(self.md_path, "w", encoding="utf-8") as fh:
            fh.write(text)
        return text

    def import_markdown(self, text: str) -> dict[str, Any]:
        """Parse Plan.md, validate, merge into plan.json. Returns change summary."""
        parsed = self._parse_markdown(text)
        if parsed.get("error"):
            raise ValueError(parsed["error"])

        existing = {t["id"]: t for t in self.data.get("tasks", [])}
        merged_tasks = []
        seen_ids: set[str] = set()

        for pt in parsed["tasks"]:
            tid = pt["id"]
            seen_ids.add(tid)
            if tid in existing:
                base = deepcopy(existing[tid])
                base["title"] = pt.get("title", base.get("title"))
                base["type"] = pt.get("type", base.get("type"))
                base["status"] = pt.get("status", base.get("status"))
                base["instruction"] = pt.get("instruction", base.get("instruction", ""))
            else:
                base = {
                    "id": tid,
                    "title": pt.get("title", "Untitled"),
                    "type": pt.get("type", "general"),
                    "status": pt.get("status", "pending"),
                    "priority": 10,
                    "assignee": None,
                    "dependsOn": [],
                    "instruction": pt.get("instruction", ""),
                    "resultRef": None,
                    "createdAt": _now(),
                    "completedAt": None,
                }
            if base["status"] == "done" and not base.get("completedAt"):
                base["completedAt"] = _now()
            merged_tasks.append(base)

        for tid, task in existing.items():
            if tid not in seen_ids and task.get("status") != "cancelled":
                merged_tasks.append(task)

        title_match = re.match(r"^#\s+Plan:\s*(.+)$", text.strip().splitlines()[0] if text.strip() else "")
        if title_match:
            self.data["title"] = title_match.group(1).strip()

        self.data["tasks"] = merged_tasks
        self.save()
        self.export_markdown()
        return {
            "tasks_updated": len(parsed["tasks"]),
            "title": self.data.get("title"),
        }

    @staticmethod
    def _parse_markdown(text: str) -> dict[str, Any]:
        lines = text.splitlines()
        current_status = "pending"
        tasks: list[dict[str, Any]] = []
        i = 0
        while i < len(lines):
            line = lines[i]
            section = re.match(r"^##\s+(.+)$", line.strip())
            if section:
                key = section.group(1).strip().lower()
                current_status = SECTION_TO_STATUS.get(key, current_status)
                i += 1
                continue

            m = _TASK_LINE.match(line.strip())
            if m:
                tid, typ, title = m.group(1), m.group(2).strip(), m.group(3).strip()
                instruction_lines = []
                i += 1
                while i < len(lines):
                    nxt = lines[i]
                    if nxt.startswith("  ") and nxt.strip():
                        instruction_lines.append(nxt.strip())
                        i += 1
                        continue
                    if nxt.strip() == "":
                        i += 1
                        break
                    if nxt.startswith("##") or _TASK_LINE.match(nxt.strip()):
                        break
                    i += 1
                status = current_status
                if line.strip().startswith("- [x]") or line.strip().startswith("- [X]"):
                    status = "done"
                tasks.append({
                    "id": tid,
                    "type": typ,
                    "title": title,
                    "status": status,
                    "instruction": "\n".join(instruction_lines),
                })
                continue
            i += 1

        ids = [t["id"] for t in tasks]
        if len(ids) != len(set(ids)):
            return {"error": "Duplicate task ids in Plan.md"}

        return {"tasks": tasks}

    def rebuild_markdown_from_json(self) -> str:
        return self.export_markdown()

    def apply_generated_plan(self, title: str, tasks: list[dict], *, replace: bool = True) -> int:
        """Replace or merge generated tasks into plan.json."""
        if replace:
            self.data["tasks"] = []
        count = 0
        for item in tasks:
            tid = item.get("id") or new_task_id()
            self.upsert_task({
                "id": tid,
                "title": item.get("title", "Untitled"),
                "type": item.get("type", "general"),
                "status": "pending",
                "priority": item.get("priority", 10),
                "assignee": item.get("assignee"),
                "dependsOn": item.get("dependsOn") or [],
                "instruction": item.get("instruction", ""),
                "resultRef": None,
            })
            count += 1
        if title:
            self.data["title"] = title
        self.save()
        self.export_markdown()
        self._snapshot = deepcopy(self.data.get("tasks", []))
        return count
