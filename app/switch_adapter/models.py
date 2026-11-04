from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class AgentRole(StrEnum):
    INTAKE_AGENT = "intake_agent"
    EXTRACTION_AGENT = "extraction_agent"
    DUPLICATE_AGENT = "duplicate_agent"
    EVIDENCE_AGENT = "evidence_agent"
    POLICY_AGENT = "policy_agent"
    RISK_AGENT = "risk_agent"
    AUDIT_AGENT = "audit_agent"


class MessageType(StrEnum):
    INTAKE_ACKNOWLEDGEMENT = "intake_acknowledgement"
    EXTRACTION_FINDING = "extraction_finding"
    DUPLICATE_FINDING = "duplicate_finding"
    EVIDENCE_FINDING = "evidence_finding"
    POLICY_FINDING = "policy_finding"
    RISK_SUMMARY = "risk_summary"
    HUMAN_DECISION_REQUEST = "human_decision_request"
    HUMAN_DECISION_RECORDED = "human_decision_recorded"


class SenderType(StrEnum):
    AGENT = "agent"
    HUMAN = "human"
    SYSTEM = "system"


AGENT_MESSAGE_TYPES = {
    MessageType.INTAKE_ACKNOWLEDGEMENT,
    MessageType.EXTRACTION_FINDING,
    MessageType.DUPLICATE_FINDING,
    MessageType.EVIDENCE_FINDING,
    MessageType.POLICY_FINDING,
    MessageType.RISK_SUMMARY,
}


class SwitchRoom(BaseModel):
    model_config = ConfigDict(extra="forbid")

    room_id: str = Field(default_factory=lambda: f"room-{uuid4()}", min_length=1)
    name: str = Field(min_length=1)
    purpose: str = ""
    created_at: datetime = Field(default_factory=utc_now)


class CaseCorrelation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(min_length=1)
    thread_key: str | None = None


class SwitchMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message_id: str = Field(default_factory=lambda: f"message-{uuid4()}", min_length=1)
    room_id: str = Field(min_length=1)
    case: CaseCorrelation
    message_type: MessageType
    sender_type: SenderType
    sender_id: str = Field(min_length=1)
    agent_role: AgentRole | None = None
    payload: dict[str, Any] = Field(min_length=1)
    timestamp: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def validate_sender_boundary(self) -> "SwitchMessage":
        is_agent_message = self.message_type in AGENT_MESSAGE_TYPES
        if is_agent_message:
            if self.sender_type != SenderType.AGENT:
                raise ValueError("agent message types require sender_type=agent")
            if self.agent_role is None:
                raise ValueError("agent messages require an agent role")
        elif self.sender_type == SenderType.AGENT:
            raise ValueError("agents cannot send human decision messages")

        if self.sender_type != SenderType.AGENT and self.agent_role is not None:
            raise ValueError("only agent messages may contain an agent role")
        return self


class HumanCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["approve", "reject", "request_clarification", "override"]
    case_id: str = Field(min_length=1)
    actor_id: str = Field(min_length=1)
    reason: str | None = None

    @model_validator(mode="after")
    def validate_reason(self) -> "HumanCommand":
        if self.action in {"reject", "override"} and not (self.reason or "").strip():
            raise ValueError(f"{self.action} requires a reason")
        if self.action == "approve" and (self.reason or "").strip():
            raise ValueError("approve does not accept a trailing reason")
        return self
