from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


class TimelineEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sequence: int = Field(ge=1)
    event_id: str = Field(min_length=1)
    case_id: str = Field(min_length=1)
    event_type: str = Field(min_length=1)
    actor_id: str = Field(min_length=1)
    payload: dict[str, Any] = Field(default_factory=dict)
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class CaseTimelineService:
    """Append-only in-memory timeline scoped by case ID."""

    def __init__(self) -> None:
        self._events: list[TimelineEvent] = []

    def append(self, case_id: str, event_type: str, actor_id: str, payload: dict[str, Any] | None = None) -> TimelineEvent:
        event = TimelineEvent(
            sequence=len(self._events) + 1,
            event_id=str(uuid4()),
            case_id=case_id,
            event_type=event_type,
            actor_id=actor_id,
            payload=payload or {},
        )
        self._events.append(event)
        return event

    def for_case(self, case_id: str) -> list[TimelineEvent]:
        return [event for event in self._events if event.case_id == case_id]
