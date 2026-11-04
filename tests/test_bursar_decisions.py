from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.bursar.decisions import apply_human_decision, create_simulated_ledger_entry
from app.bursar.models import BursarCase, CaseStatus, DecisionAction, HumanDecision


def make_case(status=CaseStatus.PENDING_REVIEW):
    return BursarCase(
        case_id="case-001",
        requester_id="requester-001",
        status=status,
        vendor_name="Acme Supplies",
        invoice_number="INV-001",
        total=Decimal("125.50"),
        currency="USD",
    )


@pytest.mark.parametrize(
    ("action", "expected"),
    [
        (DecisionAction.APPROVE, CaseStatus.APPROVED),
        (DecisionAction.REJECT, CaseStatus.REJECTED),
        (DecisionAction.REQUEST_CLARIFICATION, CaseStatus.CLARIFICATION_REQUESTED),
        (DecisionAction.OVERRIDE, CaseStatus.APPROVED_WITH_EXCEPTION),
    ],
)
def test_valid_human_decisions_transition_and_audit(action, expected):
    reason = "documented exception" if action in {DecisionAction.REJECT, DecisionAction.OVERRIDE} else None
    updated, event = apply_human_decision(
        make_case(),
        HumanDecision(action=action, actor_id="finance-001", reason=reason),
    )

    assert updated.status == expected
    assert updated.finance_reviewer_id == "finance-001"
    assert event.event_type == "human_decision"
    assert event.actor_type == "human"
    assert event.payload["action"] == action.value


@pytest.mark.parametrize("action", [DecisionAction.REJECT, DecisionAction.OVERRIDE])
def test_rejection_and_override_require_reason(action):
    with pytest.raises(ValidationError, match="requires a reason"):
        HumanDecision(action=action, actor_id="finance-001")


def test_agent_cannot_make_human_decision():
    with pytest.raises(PermissionError, match="only a human"):
        apply_human_decision(
            make_case(),
            HumanDecision(action=DecisionAction.APPROVE, actor_id="agent-001"),
            actor_type="agent",
        )


def test_non_reviewer_cannot_make_human_decision():
    with pytest.raises(PermissionError, match="finance reviewer"):
        apply_human_decision(
            make_case(),
            HumanDecision(action=DecisionAction.APPROVE, actor_id="requester-001", actor_role="requester"),
        )


def test_terminal_case_cannot_be_decided_again():
    with pytest.raises(ValueError, match="terminal case"):
        apply_human_decision(
            make_case(CaseStatus.REJECTED),
            HumanDecision(action=DecisionAction.APPROVE, actor_id="finance-001"),
        )


def test_ledger_requires_prior_human_approval_event():
    with pytest.raises(PermissionError, match="prior human approval"):
        create_simulated_ledger_entry(make_case(), [])


def test_agent_cannot_create_ledger_entry_after_approval():
    case, event = apply_human_decision(
        make_case(), HumanDecision(action=DecisionAction.APPROVE, actor_id="finance-001")
    )
    with pytest.raises(PermissionError, match="agents cannot"):
        create_simulated_ledger_entry(case, [event], actor_type="agent")


def test_ledger_is_created_after_human_approval():
    case, event = apply_human_decision(
        make_case(), HumanDecision(action=DecisionAction.APPROVE, actor_id="finance-001")
    )
    entry = create_simulated_ledger_entry(case, [event])

    assert entry.case_id == case.case_id
    assert entry.amount == Decimal("125.50")
    assert entry.approved_by == "finance-001"
    assert entry.decision_event_id == event.event_id


def test_ledger_is_created_after_human_override():
    case, event = apply_human_decision(
        make_case(),
        HumanDecision(action=DecisionAction.OVERRIDE, actor_id="finance-001", reason="verified by phone"),
    )
    entry = create_simulated_ledger_entry(case, [event])

    assert case.status == CaseStatus.APPROVED_WITH_EXCEPTION
    assert entry.approved_by == "finance-001"
