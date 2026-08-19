"""One-shot team runs via planner + OrchestratorLoop (no legacy synthesis rewrite)."""

from __future__ import annotations

from typing import Any, Callable, Iterator

from src import personas, worldcontext
from src.orchestration.plan_builder import build_ephemeral_tasks
from src.orchestration.registry import order_tasks_for_dispatch
from src.orchestration.task_types import TASK_TYPES


def iter_liaison(
    engine,
    task: str,
    ask_user: Callable[[str], str] | None,
    *,
    show_think: bool = False,
) -> Iterator[tuple[str, Any]]:
    """Liaison preamble before multi-agent jobs. Yields GUI events."""
    if not callable(ask_user):
        return
    settings = engine.settings
    liaison = settings.persona(
        engine.project_id,
        settings.get("orchestration.liaison_key", "system_liaison"))
    if not liaison:
        return
    yield ("step", liaison, "Gather requirements from the user.")
    msgs = engine._compose([("system", liaison["system_prompt"])])
    setting = engine._setting_block()
    if setting:
        msgs.append({"role": "system", "content": setting})
    msgs.append({"role": "user", "content":
        "The user wants to: " + task +
        "\n\nAsk up to 3 focused clarifying questions. "
        "If the request is clear, say so briefly."})
    for delta in engine._stream_generate(liaison, msgs, show_think):
        yield ("delta", liaison, delta)
    if engine.is_cancelled():
        yield ("cancelled",)
        return
    yield ("step_done", liaison)
    yield ("await_user", "Answer the Liaison (blank to proceed):")
    answer = ask_user("Answer the Liaison:") or ""
    if engine.is_cancelled():
        yield ("cancelled",)
        return
    augmented = task
    if answer.strip():
        yield ("user", answer)
        augmented = task + "\n\nUSER CLARIFICATIONS:\n" + answer
    yield ("liaison_done", augmented)


def run_one_shot_team(
    loop,
    engine,
    task: str,
    *,
    show_think: bool = False,
    ask_user: Callable[[str], str] | None = None,
) -> Iterator[tuple[str, Any]]:
    """Plan and execute a one-shot team job; yields GUI events."""
    settings = engine.settings
    augmented = task

    for ev in iter_liaison(engine, task, ask_user, show_think=show_think):
        if ev[0] == "liaison_done":
            augmented = ev[1]
            continue
        yield ev
        if ev[0] == "cancelled":
            return

    if engine.is_cancelled():
        yield ("cancelled",)
        return

    _title, tasks = build_ephemeral_tasks(engine, augmented, loop.registry)
    tasks = order_tasks_for_dispatch(tasks, loop.registry)
    plan_steps = []
    for t in tasks:
        assignee = t.get("assignee") or "?"
        persona = settings.persona(engine.project_id, assignee)
        if persona:
            plan_steps.append({
                "persona": persona,
                "instruction": t.get("instruction", ""),
            })
    yield ("plan", plan_steps)

    outputs: list[tuple[str, str]] = []
    for item in tasks:
        if engine.is_cancelled():
            yield ("cancelled",)
            return
        for ev in loop.dispatch_task(item, show_think=show_think):
            if ev[0] == "delta":
                persona = ev[1]
                outputs.append((persona.get("display_name", ""), ev[2]))
            yield ev

    if settings.get("orchestration.synthesis", False) and outputs:
        planner = settings.persona(
            engine.project_id,
            settings.get("orchestration.manager_key", "system_planner"))
        if planner:
            yield ("step", planner, "Team summary (optional merge).")
            lines = "\n\n".join(
                f"=== {name} ===\n{text}" for name, text in outputs if text)
            msgs = engine._compose([
                ("system", planner["system_prompt"] +
                 "\nSummarize team output for the user in plain language. "
                 "Do not rewrite specialist prose unless asked."),
                ("user", f"TASK:\n{augmented}\n\nTEAM OUTPUT:\n{lines}"),
            ])
            for delta in engine._stream_generate(planner, msgs, show_think):
                yield ("delta", planner, delta)
            if engine.is_cancelled():
                yield ("cancelled",)
                return
            yield ("step_done", planner)

    yield ("done",)
