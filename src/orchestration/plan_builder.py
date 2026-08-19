"""Generate structured task lists via the system planner."""

from __future__ import annotations

import json
import re
from typing import Any

from src import personas, worldcontext
from src.orchestration.plan_state import new_task_id
from src.orchestration.registry import AgentRegistry
from src.orchestration.task_types import (
    TASK_TYPES,
    normalize_task_type,
    task_type_for_agent,
)

_TYPE_LIST = " | ".join(sorted(TASK_TYPES))


def _planner_persona(settings, project_id):
    key = settings.get("orchestration.manager_key", "system_planner")
    p = settings.persona(project_id, key)
    if p:
        return p
    return settings.persona(project_id, "system_planner")


def _parse_plan_json(text: str, max_tasks: int) -> dict[str, Any] | None:
    if not text:
        return None
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    tasks = data.get("tasks")
    if not isinstance(tasks, list):
        return None
    out_tasks = []
    for item in tasks[:max_tasks]:
        if not isinstance(item, dict):
            continue
        title = (item.get("title") or item.get("name") or "").strip()
        instruction = (item.get("instruction") or item.get("task") or title).strip()
        if not title or not instruction:
            continue
        assignee = (item.get("assignee") or item.get("agent") or item.get("persona") or "")
        assignee = str(assignee).strip() or None
        raw_type = normalize_task_type(item.get("type"))
        out_tasks.append({
            "title": title[:120],
            "type": raw_type,
            "assignee": assignee,
            "instruction": instruction,
            "priority": int(item.get("priority", 10 + len(out_tasks))),
        })
    if not out_tasks:
        return None
    title = (data.get("title") or "Project plan").strip()
    return {"title": title[:120], "tasks": out_tasks}


def _resolve_assignee(registry: AgentRegistry, item: dict) -> tuple[str | None, str]:
    assignee = item.get("assignee")
    task_type = normalize_task_type(item.get("type"))
    if assignee and registry.get(assignee):
        resolved_type = task_type_for_agent(assignee) or task_type
        return assignee, resolved_type
    cap = registry.best_for(task_type)
    if cap:
        return cap.key, task_type
    return None, task_type


def _tasks_from_parsed(parsed: dict, registry: AgentRegistry) -> list[dict]:
    tasks = []
    for item in parsed["tasks"]:
        assignee, task_type = _resolve_assignee(registry, item)
        if not assignee:
            continue
        tasks.append({
            "id": new_task_id(),
            "title": item["title"],
            "type": task_type,
            "status": "pending",
            "priority": item.get("priority", 10),
            "assignee": assignee,
            "dependsOn": [],
            "instruction": item["instruction"],
            "resultRef": None,
        })
    return tasks


def _call_planner(engine, goal: str, registry: AgentRegistry) -> str:
    settings = engine.settings
    project_id = engine.project_id
    planner = _planner_persona(settings, project_id)
    if not planner:
        raise ValueError("System planner is not available.")

    roster = personas.roster_for_planner(
        settings.selectable_personas(project_id),
        exclude_keys=personas.HIDDEN_PERSONA_KEYS)
    max_tasks = max(3, int(settings.get("orchestration.max_steps", 5)) * 2)

    setting = ""
    if engine.paths and settings.get("context.inject", True):
        setting = worldcontext.assemble(
            engine.paths,
            max_chars=int(settings.get("context.inject_max_chars", 6000)))

    planner_sys = (
        "You are the system planner for a fiction writing team. "
        "Given a GOAL, produce a structured task plan (do not execute work).\n\n"
        "Respond with ONLY JSON:\n"
        "{\n"
        '  "title": "short plan title",\n'
        '  "tasks": [\n'
        "    {\n"
        '      "title": "short task title",\n'
        f'      "type": "{_TYPE_LIST}",\n'
        '      "assignee": "<exact specialist key from roster>",\n'
        '      "instruction": "scoped instruction for that specialist only",\n'
        '      "priority": 10\n'
        "    }\n"
        "  ]\n"
        "}\n"
        f"Use at most {max_tasks} tasks. Each task must name one assignee. "
        "End with canon_check when accuracy matters. Never assign planner or liaison. "
        "When order permits, group consecutive tasks on the same specialist "
        "tier — switching tiers reloads the model and is slow."
    )
    planner_user = f"GOAL:\n{goal}\n\nSPECIALISTS (key: role):\n{roster}\n"
    if setting:
        planner_user += f"\nSETTING:\n{setting[:4000]}\n"
    planner_user += "\nReturn ONLY the JSON plan."

    pairs = [("system", planner_sys)]
    if setting:
        pairs.append(("system", setting))
    pairs.append(("user", planner_user))

    engine.clear_cancel()
    messages = engine._compose(pairs)
    parts = []
    for chunk in engine._stream_generate(planner, messages, show_think=False):
        if engine.is_cancelled():
            break
        parts.append(chunk)
    return "".join(parts)


def build_ephemeral_tasks(
    engine, goal: str, registry: AgentRegistry | None = None,
) -> tuple[str, list[dict]]:
    """Planner → (title, task dicts) for one-shot execution."""
    registry = registry or AgentRegistry()
    if not registry.all_agents():
        registry.populate_from_settings(engine.settings, engine.project_id)
    text = _call_planner(engine, goal, registry)
    if engine.is_cancelled():
        return "Cancelled", []
    max_tasks = max(3, int(engine.settings.get("orchestration.max_steps", 5)) * 2)
    parsed = _parse_plan_json(text, max_tasks)
    if not parsed:
        parsed = _default_plan(goal, registry)
    title = parsed.get("title") or "Project plan"
    return title, _tasks_from_parsed(parsed, registry)


def generate_plan(engine, goal: str, registry: AgentRegistry | None = None) -> dict[str, Any]:
    """Ask the planner for a plan.json-ready task list."""
    goal = (goal or "").strip()
    if not goal:
        raise ValueError("Enter a goal for the plan.")

    registry = registry or AgentRegistry()
    registry.populate_from_settings(engine.settings, engine.project_id)

    if engine.is_cancelled():
        return {"title": "Cancelled", "tasks": [], "cancelled": True}

    title, tasks = build_ephemeral_tasks(engine, goal, registry)
    if engine.is_cancelled():
        return {"title": "Cancelled", "tasks": [], "cancelled": True}
    return {"title": title, "tasks": tasks}


def _default_plan(goal: str, registry: AgentRegistry) -> dict[str, Any]:
    tasks = []
    if registry.get("world_builder"):
        tasks.append({
            "title": "Design setting elements",
            "type": "setting_design",
            "assignee": "world_builder",
            "instruction": goal,
            "priority": 10,
        })
    if registry.get("lore_curator"):
        tasks.append({
            "title": "Check against canon",
            "type": "canon_check",
            "assignee": "lore_curator",
            "instruction": "Review output against established canon; flag contradictions.",
            "priority": 20,
        })
    if not tasks:
        cap = registry.best_for("plot_design")
        if cap:
            tasks.append({
                "title": "Execute goal",
                "type": "plot_design",
                "assignee": cap.key,
                "instruction": goal,
                "priority": 10,
            })
    return {"title": "Project plan", "tasks": tasks}
