"""Append-only JSONL event log with replay."""

from __future__ import annotations

import json
import os
from typing import Iterator

from src.orchestration.events import Event


class EventLog:
    def __init__(self, path: str):
        self.path = path
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

    def append(self, event: Event) -> None:
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(event.to_dict(), ensure_ascii=False) + "\n")

    def read_all(self) -> list[Event]:
        if not os.path.exists(self.path):
            return []
        events = []
        with open(self.path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(Event.from_dict(json.loads(line)))
                except (json.JSONDecodeError, KeyError, ValueError):
                    continue
        return events

    def replay_from(self, offset: int = 0) -> Iterator[Event]:
        for i, event in enumerate(self.read_all()):
            if i >= offset:
                yield event

    def last_event_id(self) -> str | None:
        events = self.read_all()
        return events[-1].id if events else None
