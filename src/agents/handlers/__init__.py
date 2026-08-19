"""Event handler wrappers for registered agents."""

from __future__ import annotations

from typing import Any, Generator

from src.orchestration.events import Event, EventType


class BaseAgentHandler:
    def __init__(self, engine, bus=None):
        self.engine = engine
        self.bus = bus

    def handles(self) -> list[str]:
        return ["general"]

    def on_event(self, event: Event) -> None:
        pass

    def run(
        self, persona_key: str, instruction: str, show_think: bool = False
    ) -> Generator[str, None, None]:
        yield from self.engine.stream_task(persona_key, instruction, show_think=show_think)


class LoreCheckHandler(BaseAgentHandler):
    def handles(self) -> list[str]:
        return ["lore_check"]

    def run(self, persona_key, instruction, show_think=False):
        augmented = (
            instruction + "\n\nUse query_lore tool blocks when needed: "
            '{"tool": "query_lore", "args": {"query": "..."}}'
        )
        yield from self.engine.stream_task(persona_key, augmented, show_think=show_think)


class DialogueHandler(BaseAgentHandler):
    def handles(self) -> list[str]:
        return ["write_dialogue"]

    def run(self, persona_key, instruction, show_think=False):
        yield from self.engine.stream_task(persona_key, instruction, show_think=show_think)


def register_handlers(engine, bus=None) -> dict[str, BaseAgentHandler]:
    handlers = {
        "general": BaseAgentHandler(engine, bus),
        "lore_check": LoreCheckHandler(engine, bus),
        "write_dialogue": DialogueHandler(engine, bus),
    }
    if bus:
        for handler in handlers.values():
            bus.subscribe(EventType.AGENT_DISPATCH, handler.on_event)
    return handlers
