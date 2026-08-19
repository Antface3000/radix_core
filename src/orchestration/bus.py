"""In-process pub/sub for orchestration events."""

from __future__ import annotations

from collections import defaultdict
from typing import Callable

from src.orchestration.events import Event, EventType

Handler = Callable[[Event], None]


class EventBus:
    def __init__(self):
        self._handlers: dict[str, list[Handler]] = defaultdict(list)

    def subscribe(self, event_type: EventType | str, handler: Handler) -> None:
        key = event_type.value if isinstance(event_type, EventType) else event_type
        self._handlers[key].append(handler)

    def publish(self, event: Event) -> None:
        for handler in list(self._handlers.get(event.type.value, [])):
            handler(event)
        for handler in list(self._handlers.get("*", [])):
            handler(event)

    def clear(self) -> None:
        self._handlers.clear()
