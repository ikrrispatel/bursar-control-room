from __future__ import annotations

from uuid import uuid4

from app.bursar.models import (
    AuditEvent,
    BursarCase,
    CaseStatus,
    DecisionAction,
    HumanDecision,
    SimulatedLedgerEntry,
    utc_now,
)


TERMINAL_STATUSES = {
    CaseStatus.APPROVED,
    CaseStatus.REJECTED,
    CaseStatus.APPROVED_WITH_EXCEPTION,
}


def apply_human_decision(
    case: BursarCase,
    decision: HumanDecision,
    *,
    actor_type: str = "human",
) -> tuple[BursarCase, AuditEvent]:
    """Apply one allowlisted decision and return the case plus its audit event."""
    if actor_type != "human":
        raise PermissionError("only a human finance reviewer may decide a case")
    if decision.actor_role != "finance_reviewer":
        raise PermissionError("decision actor must be a finance reviewer")
    if not decision.actor_id.strip():
        raise ValueError("finance reviewer identity is required")
    if case.status in TERMINAL_STATUSES:
        raise ValueError(f"terminal case cannot be decided again: {case.status.value}")

    next_status = {
        DecisionAction.APPROVE: CaseStatus.APPROVED,
        DecisionAction.REJECT: CaseStatus.REJECTED,
        DecisionAction.REQUEST_CLARIFICATION: CaseStatus.CLARIFICATION_REQUESTED,
        DecisionAction.OVERRIDE: CaseStatus.APPROVED_WITH_EXCEPTION,
    }[decision.action]
    updated_case = case.model_copy(
        update={
            "status": next_status,
            "finance_reviewer_id": decision.actor_id,
            "updated_at": utc_now(),
        }
    )
    event = AuditEvent(
        event_id=str(uuid4()),
        case_id=case.case_id,
        event_type="human_decision",
        actor_id=decision.actor_id,
        actor_type="human",
        payload={"action": decision.action.value, "reason": decision.reason},
        occurred_at=decision.occurred_at,
    )
    return updated_case, event


def create_simulated_ledger_entry(
    case: BursarCase,
    audit_events: list[AuditEvent],
    *,
    actor_type: str = "system",
) -> SimulatedLedgerEntry:
    """Create a ledger entry only when a prior human approval is recorded."""
    if actor_type == "agent":
        raise PermissionError("agents cannot create simulated ledger entries")
    if actor_type != "system":
        raise PermissionError("only the deterministic ledger service may create ledger entries")
    eligible = [
        event
        for event in audit_events
        if event.case_id == case.case_id
        and event.event_type == "human_decision"
        and event.actor_type == "human"
        and event.payload.get("action")
        in {DecisionAction.APPROVE.value, DecisionAction.OVERRIDE.value}
    ]
    if not eligible:
        raise PermissionError(
            "simulated ledger entry requires a prior human approval or override event"
        )
    if case.status not in {CaseStatus.APPROVED, CaseStatus.APPROVED_WITH_EXCEPTION}:
        raise ValueError("case is not approved for simulated ledger entry")
    event = eligible[-1]
    if case.total is None or case.currency is None:
        raise ValueError("case total and currency are required for simulated ledger entry")
    return SimulatedLedgerEntry(
        entry_id=str(uuid4()),
        case_id=case.case_id,
        amount=case.total,
        currency=case.currency,
        approved_by=event.actor_id,
        decision_event_id=event.event_id,
    )
