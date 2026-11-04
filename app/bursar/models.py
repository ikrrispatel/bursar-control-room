from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class CaseStatus(StrEnum):
    PENDING_REVIEW = "pending_review"
    NEEDS_EVIDENCE = "needs_evidence"
    BLOCKED = "blocked"
    CLARIFICATION_REQUESTED = "clarification_requested"
    APPROVED = "approved"
    REJECTED = "rejected"
    APPROVED_WITH_EXCEPTION = "approved_with_exception"


class DecisionAction(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"
    REQUEST_CLARIFICATION = "request_clarification"
    OVERRIDE = "override"


class EvidenceReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_id: str = Field(min_length=1)
    case_id: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    file_name: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_location: str | None = None
    created_at: datetime = Field(default_factory=utc_now)


class AgentFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    finding_id: str = Field(min_length=1)
    agent_name: str = Field(min_length=1)
    finding_type: str = Field(min_length=1)
    status: str = Field(min_length=1)
    explanation: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)
    evidence: list[EvidenceReference] = Field(default_factory=list)


class HumanDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: DecisionAction
    actor_id: str = Field(min_length=1)
    actor_role: str = Field(default="finance_reviewer", min_length=1)
    reason: str | None = None
    occurred_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def validate_reason(self) -> "HumanDecision":
        if self.action in {DecisionAction.REJECT, DecisionAction.OVERRIDE} and not (self.reason or "").strip():
            raise ValueError(f"{self.action.value} requires a reason")
        return self


class BursarCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(min_length=1)
    status: CaseStatus = CaseStatus.PENDING_REVIEW
    requester_id: str = Field(min_length=1)
    room_id: str | None = None
    intake_message_id: str | None = None
    finance_reviewer_id: str | None = None
    vendor_name: str | None = None
    invoice_number: str | None = None
    total: Decimal | None = Field(default=None, ge=0)
    currency: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class AuditEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(min_length=1)
    case_id: str = Field(min_length=1)
    event_type: str = Field(min_length=1)
    actor_id: str = Field(min_length=1)
    actor_type: str = Field(min_length=1)
    payload: dict[str, Any] = Field(default_factory=dict)
    occurred_at: datetime = Field(default_factory=utc_now)


class SimulatedLedgerEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entry_id: str = Field(min_length=1)
    case_id: str = Field(min_length=1)
    amount: Decimal = Field(ge=0)
    currency: str = Field(min_length=1)
    approved_by: str = Field(min_length=1)
    decision_event_id: str = Field(min_length=1)
    created_at: datetime = Field(default_factory=utc_now)
