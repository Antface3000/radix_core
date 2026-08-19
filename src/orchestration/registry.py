"""Dynamic agent registry — one specialist per task type."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.orchestration.task_types import (
    AGENT_TO_TASK_TYPE,
    TASK_TYPE_TO_AGENT,
    normalize_task_type,
    task_type_for_agent,
)


@dataclass
class AgentCapability:
    key: str
    display_name: str
    handles: list[str]
    tools: list[str]
    model_key: str
    system_prompt: str
    capture_kind: str | None = None
    tier: str = ""
    temperature: float | None = None
    max_tokens: int | None = None
    persona: dict[str, Any] = field(default_factory=dict)


class AgentRegistry:
    def __init__(self):
        self._agents: dict[str, AgentCapability] = {}

    def register(self, cap: AgentCapability) -> None:
        self._agents[cap.key] = cap

    def register_persona(self, persona: dict[str, Any]) -> None:
        key = persona["key"]
        task_type = task_type_for_agent(key)
        handles = [task_type] if task_type else []
        cap = AgentCapability(
            key=key,
            display_name=persona.get("display_name", key),
            handles=handles,
            tools=persona.get("tools") or [],
            model_key=persona.get("model_key", "operator"),
            system_prompt=persona.get("system_prompt", ""),
            capture_kind=persona.get("capture_kind"),
            tier=persona.get("tier", ""),
            temperature=persona.get("temperature"),
            max_tokens=persona.get("max_tokens"),
            persona=persona,
        )
        self.register(cap)

    def get(self, key: str) -> AgentCapability | None:
        return self._agents.get(key)

    def all_agents(self) -> list[AgentCapability]:
        return list(self._agents.values())

    def best_for(self, task_type: str) -> AgentCapability | None:
        """Exact task type → specialist; no fallbacks."""
        task_type = normalize_task_type(task_type)
        key = TASK_TYPE_TO_AGENT.get(task_type)
        if key:
            return self.get(key)
        return None

    def populate_from_settings(self, settings, project_id: str) -> None:
        self._agents.clear()
        for persona in settings.selectable_personas(project_id):
            self.register_persona(persona)
        for key in ("system_planner", "system_liaison"):
            persona = settings.persona(project_id, key)
            if persona:
                self.register_persona(persona)

    def agent_for_task(self, task: dict[str, Any]) -> AgentCapability | None:
        assignee = (task.get("assignee") or "").strip()
        if assignee:
            cap = self.get(assignee)
            if cap:
                return cap
        return self.best_for(task.get("type", ""))


# Model slots load one GGUF at a time; grouping tasks by tier avoids reloads.
_TIER_DISPATCH_ORDER = {"architect": 0, "operator": 1, "flavor": 2}


def order_tasks_for_dispatch(
    tasks: list[dict[str, Any]], registry: AgentRegistry
) -> list[dict[str, Any]]:
    """Stable-sort tasks by (priority, model tier), keeping dependents after
    their dependencies. Minimizes single-slot model reloads between steps."""

    def tier_rank(task: dict[str, Any]) -> int:
        agent = registry.agent_for_task(task)
        if agent is None:
            return 99
        return _TIER_DISPATCH_ORDER.get(agent.model_key, 50)

    ordered = sorted(
        tasks, key=lambda t: (t.get("priority", 10), tier_rank(t)))

    # Dependency fix-up: move any task that precedes one of its dependencies
    # to just after its last dependency (bounded passes; cycles left as-is).
    for _ in range(len(ordered)):
        pos = {t.get("id"): i for i, t in enumerate(ordered)}
        moved = False
        for i, task in enumerate(ordered):
            deps = task.get("dependsOn") or []
            latest = max((pos.get(d, -1) for d in deps), default=-1)
            if latest > i:
                ordered.insert(latest, ordered.pop(i))
                moved = True
                break
        if not moved:
            break
    return ordered
