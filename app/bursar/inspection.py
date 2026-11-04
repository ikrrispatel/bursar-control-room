from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.bursar.models import AgentFinding, AuditEvent, BursarCase, HumanDecision, SimulatedLedgerEntry
from app.bursar.passport import EvidencePassport
from app.bursar.timeline import TimelineEvent
from app.bursar.workflow import LocalBursarWorkflowCoordinator


STATUS_LABELS = {
    "pending_review": "Ready",
    "needs_evidence": "Needs evidence",
    "clarification_requested": "Needs evidence",
    "blocked": "Blocked",
    "approved": "Approved",
    "rejected": "Rejected",
    "approved_with_exception": "Approved with exception",
}


class CaseSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    status: str
    status_label: str
    vendor_name: str | None = None
    invoice_number: str | None = None
    total: str | None = None
    currency: str | None = None
    room_id: str | None = None


class CaseDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case: BursarCase
    status_label: str
    checks: dict
    message_count: int = Field(ge=0)


class CaseListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cases: list[CaseSummary]


class EvidencePassportResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    passport: EvidencePassport


class TimelineResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    events: list[TimelineEvent]


class FindingsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    findings: list[AgentFinding]


class DecisionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: HumanDecision | None


class LedgerResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ledger: SimulatedLedgerEntry | None


class BursarInspectionService:
    """Read-only projection over the coordinator's in-memory Bursar state."""

    def __init__(self, coordinator: LocalBursarWorkflowCoordinator) -> None:
        self.coordinator = coordinator

    def list_cases(self) -> CaseListResponse:
        cases = sorted(self.coordinator.cases.values(), key=lambda case: case.created_at)
        return CaseListResponse(cases=[self._summary(case) for case in cases])

    def case_detail(self, case_id: str) -> CaseDetail:
        case = self._case(case_id)
        return CaseDetail(
            case=case,
            status_label=self.status_label(case.status.value),
            checks=self.coordinator.checks[case_id].model_dump(mode="json"),
            message_count=len(self.coordinator.messages.get(case_id, [])),
        )

    def evidence_passport(self, case_id: str):
        self._case(case_id)
        return self.coordinator.passports[case_id]

    def timeline(self, case_id: str):
        self._case(case_id)
        return self.coordinator.timeline_for_case(case_id)

    def findings(self, case_id: str) -> FindingsResponse:
        passport = self.evidence_passport(case_id)
        return FindingsResponse(findings=passport.agent_findings)

    def decision(self, case_id: str) -> DecisionResponse:
        passport = self.evidence_passport(case_id)
        return DecisionResponse(decision=passport.human_decision)

    def ledger(self, case_id: str) -> LedgerResponse:
        passport = self.evidence_passport(case_id)
        return LedgerResponse(ledger=passport.simulated_ledger_result)

    @staticmethod
    def status_label(status: str) -> str:
        return STATUS_LABELS.get(status, status.replace("_", " ").title())

    def _case(self, case_id: str) -> BursarCase:
        case = self.coordinator.cases.get(case_id)
        if case is None:
            raise KeyError(case_id)
        return case

    def _summary(self, case: BursarCase) -> CaseSummary:
        return CaseSummary(
            case_id=case.case_id,
            status=case.status.value,
            status_label=self.status_label(case.status.value),
            vendor_name=case.vendor_name,
            invoice_number=case.invoice_number,
            total=str(case.total) if case.total is not None else None,
            currency=case.currency,
            room_id=case.room_id,
        )
