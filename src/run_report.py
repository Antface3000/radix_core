"""Persist team job output as a markdown report under the project's runs/ dir."""

from __future__ import annotations

import os
import re
from datetime import datetime

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slug(value: str) -> str:
    return _SLUG_RE.sub("-", (value or "").lower()).strip("-")[:40]


def write_run_report(paths, goal: str, blocks: list[tuple[str, str]],
                     kind: str = "Team job") -> str:
    """Write goal + per-speaker output blocks to runs/<timestamp>-<slug>.md."""
    runs_dir = paths["runs"]
    os.makedirs(runs_dir, exist_ok=True)
    now = datetime.now()
    stamp = now.strftime("%Y%m%d-%H%M%S")
    name = f"{stamp}-{_slug(goal) or _slug(kind) or 'run'}.md"
    path = os.path.join(runs_dir, name)

    lines = [
        f"# {kind} report",
        "",
        f"- **When:** {now.strftime('%Y-%m-%d %H:%M:%S')}",
        f"- **Goal:** {goal.strip() or '(none)'}",
        "",
    ]
    for who, text in blocks:
        text = (text or "").strip()
        if not text:
            continue
        lines.append(f"## {who or 'Output'}")
        lines.append("")
        lines.append(text)
        lines.append("")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    return path
