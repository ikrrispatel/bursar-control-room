from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.bursar.models import AgentFinding, AuditEvent, HumanDecision, EvidenceReference, SimulatedLedgerEntry


class EvidencePassport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    extracted_invoice_fields: dict[str, Any]
    evidence_references: list[EvidenceReference] = Field(default_factory=list)
    check_results: dict[str, Any] = Field(default_factory=dict)
    agent_findings: list[AgentFinding] = Field(default_factory=list)
    human_decision: HumanDecision | None = None
    audit_events: list[AuditEvent] = Field(default_factory=list)
    simulated_ledger_result: SimulatedLedgerEntry | None = None
