"""Monitor → Evaluate → Dispatch → Execute → Update orchestration loop."""

from __future__ import annotations

from typing import Any, Callable, Generator, Iterator

from src.orchestration.bus import EventBus
from src.orchestration.event_log import EventLog
from src.orchestration.events import Event, EventType
from src.orchestration.hitl import HitlController
from src.orchestration.plan_state import PlanStateStore
from src.orchestration.registry import AgentRegistry
from src.orchestration.task_types import normalize_task_type
from src.orchestration.tool_gatekeeper import ToolGatekeeper


class OrchestratorLoop:
    """Event-driven task runner backed by plan.json."""

    def __init__(
        self,
        project_id: str,
        registry: AgentRegistry,
        runner: Any,
        settings=None,
        ask_user: Callable[[str], str] | None = None,
    ):
        self.project_id = project_id
        self.registry = registry
        self.runner = runner
        self.settings = settings
        self.ask_user = ask_user
        self.bus = EventBus()
        self.plan = PlanStateStore(project_id)
        paths = __import__("src.projects", fromlist=["project_paths"]).project_paths(project_id)
        self.log = EventLog(paths["events"])
        self.hitl = HitlController(project_id)
        self.gatekeeper = ToolGatekeeper()
        self._running = False

    def _emit(self, event_type: EventType, payload: dict[str, Any]) -> Event:
        event = Event(type=event_type, payload=payload)
        self.log.append(event)
        self.bus.publish(event)
        meta = self.plan.data.setdefault("meta", {})
        meta["lastEventId"] = event.id
        self.plan.save()
        return event

    def _scoped_instruction(self, task: dict[str, Any], instruction: str) -> str:
        """Task instruction plus dependency outputs only (no full team buffer)."""
        deps = task.get("dependsOn") or []
        if not deps:
            return instruction
        blocks: list[str] = []
        for dep_id in deps:
            dep = self.plan.task_by_id(dep_id)
            if not dep:
                continue
            ref = (dep.get("resultRef") or "").strip()
            if ref:
                title = dep.get("title") or dep_id
                blocks.append(f"[Prior task — {title}]:\n{ref}")
        if not blocks:
            return instruction
        return (
            instruction
            + "\n\nREFERENCE (from tasks this one depends on):\n"
            + "\n\n".join(blocks)
        )

    def monitor(self) -> list[dict[str, Any]]:
        self.plan.load()
        return self.plan.emit_pending_events()

    def dispatch_task(
        self, task: dict[str, Any], show_think: bool = False
    ) -> Generator[tuple[str, Any], None, None]:
        """Run one plan task; yields GUI-style events."""
        task_id = task["id"]
        task_type = normalize_task_type(task.get("type"))
        instruction = task.get("instruction", task.get("title", ""))
        scoped = self._scoped_instruction(task, instruction)

        agent = self.registry.agent_for_task(task)
        if agent is None:
            yield ("error", "orchestrator",
                   f"No specialist for task type {task_type!r}")
            return

        self.plan.set_task_status(task_id, "in_progress")
        self._emit(EventType.AGENT_DISPATCH, {
            "task_id": task_id,
            "agent": agent.key,
            "instruction": instruction,
        })

        if task_type == "hitl" and callable(self.ask_user):
            answer = self.hitl.request_input(
                instruction,
                {"task_id": task_id},
                self.ask_user,
                cancel_check=getattr(self.runner, "is_cancelled", lambda: False),
            )
            if answer is None and getattr(self.runner, "is_cancelled", lambda: False)():
                self.plan.cancel_task(task_id)
                self._emit(EventType.AGENT_CANCELLED, {"task_id": task_id})
                yield ("cancelled",)
                return
            if answer:
                self._emit(EventType.HUMAN_INPUT_RECEIVED, {"task_id": task_id, "text": answer})
                yield ("user", answer)

        yield ("task", task)
        yield ("step", agent.persona, scoped)
        visible_parts: list[str] = []

        stream_fn = getattr(self.runner, "stream_persona", None)
        if callable(stream_fn):
            for delta in stream_fn(
                    agent.key, scoped, show_think=show_think, orchestration=True):
                if getattr(self.runner, "is_cancelled", lambda: False)():
                    self.plan.set_task_status(task_id, "cancelled")
                    self._emit(EventType.AGENT_CANCELLED, {"task_id": task_id})
                    yield ("cancelled",)
                    return
                visible_parts.append(delta)
                yield ("delta", agent.persona, delta)
        else:
            text = self.runner.run_persona(
                agent.key, scoped, show_think=show_think, orchestration=True)
            visible_parts.append(text)
            yield ("delta", agent.persona, text)

        raw = "".join(visible_parts)
        tool_calls = self.gatekeeper.parse_tool_calls(raw)
        for call in tool_calls:
            self._emit(EventType.TOOL_CALL_REQUESTED, call)
            result = self.gatekeeper.run_parsed(call)
            self._emit(EventType.TOOL_CALL_COMPLETED, result)

        self.plan.complete_task(task_id, result_ref=raw[:200] if raw else None)
        self._emit(EventType.AGENT_COMPLETED, {
            "task_id": task_id,
            "agent": agent.key,
            "chars": len(raw),
        })
        yield ("step_done", agent.persona)
        yield ("done",)

    def run_pending(
        self, show_think: bool = False, max_tasks: int | None = None
    ) -> Iterator[tuple[str, Any]]:
        """Process all pending plan tasks."""
        self._running = True
        try:
            from src.orchestration.registry import order_tasks_for_dispatch
            pending = order_tasks_for_dispatch(self.monitor(), self.registry)
            if max_tasks is not None:
                pending = pending[:max_tasks]
            for task in pending:
                if getattr(self.runner, "is_cancelled", lambda: False)():
                    yield ("cancelled",)
                    return
                yield from self.dispatch_task(task, show_think=show_think)
        finally:
            self._running = False

    def run_freeform(
        self, message: str, show_think: bool = False
    ) -> Iterator[tuple[str, Any]]:
        """Ad-hoc orchestration: create a transient task and run via registry."""
        from src.orchestration.plan_state import new_task_id

        task = {
            "id": new_task_id(),
            "title": message[:80],
            "type": "plot_design",
            "status": "pending",
            "priority": 10,
            "assignee": None,
            "dependsOn": [],
            "instruction": message,
            "resultRef": None,
        }
        self.plan.upsert_task(task)
        yield from self.dispatch_task(task, show_think=show_think)

    def cancel(self) -> None:
        cancel = getattr(self.runner, "request_cancel", None)
        if callable(cancel):
            cancel()

    @property
    def is_running(self) -> bool:
        return self._running
