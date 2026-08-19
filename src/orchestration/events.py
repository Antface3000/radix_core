"""Typed orchestration events."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class EventType(str, Enum):
    TASK_PENDING = "task.pending"
    AGENT_DISPATCH = "agent.dispatch"
    AGENT_DELTA = "agent.delta"
    AGENT_COMPLETED = "agent.completed"
    AGENT_CANCELLED = "agent.cancelled"
    ESCALATION_REQUESTED = "escalation.requested"
    TOOL_CALL_REQUESTED = "tool.call.requested"
    TOOL_CALL_COMPLETED = "tool.call.completed"
    HUMAN_INPUT_RECEIVED = "human.input.received"
    PLAN_UPDATED = "plan.updated"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_event_id() -> str:
    return f"evt-{uuid.uuid4().hex[:12]}"


@dataclass
class Event:
    type: EventType
    payload: dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=new_event_id)
    timestamp: str = field(default_factory=_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type.value,
            "timestamp": self.timestamp,
            "payload": self.payload,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Event:
        return cls(
            id=data.get("id", new_event_id()),
            type=EventType(data["type"]),
            timestamp=data.get("timestamp", _now_iso()),
            payload=data.get("payload") or {},
        )
