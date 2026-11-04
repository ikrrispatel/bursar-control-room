import pytest

from app.bursar.workflow import LocalBursarWorkflowCoordinator
from app.switch_adapter import CaseCorrelation, LocalFixtureSwitchAdapter, MessageType, SwitchMessage


EVIDENCE = {
    "evidence_id": "evidence-invoice-001",
    "kind": "invoice",
    "file_name": "invoice-001.pdf",
    "sha256": "a" * 64,
    "source_location": "fixture://invoice-001",
}


def make_intake(room_id: str, case_id: str, **overrides):
    payload = {
        "vendor_name": "Acme Supplies",
        "invoice_number": f"INV-{case_id[-3:]}",
        "total": "125.50",
        "currency": "USD",
        "evidence": [EVIDENCE],
        **overrides,
    }
    return SwitchMessage(
        room_id=room_id,
        case=CaseCorrelation(case_id=case_id),
        message_type=MessageType.INVOICE_INTAKE,
        sender_type="human",
        sender_id="requester-001",
        payload=payload,
    )


def setup_case(case_id="case-001", **overrides):
    adapter = LocalFixtureSwitchAdapter()
    room = adapter.create_room("bursar-control-room")
    intake = make_intake(room.room_id, case_id, **overrides)
    adapter.post_message(intake)
    coordinator = LocalBursarWorkflowCoordinator(adapter)
    result = coordinator.start_case(intake)
    return adapter, room, coordinator, result


def message_types(result):
    return [message.message_type for message in result.messages]


def test_clean_invoice_intake_findings_approve_and_ledger():
    adapter, room, coordinator, result = setup_case()

    assert result.case.room_id == room.room_id
    assert result.case.intake_message_id
    assert result.case.status.value == "pending_review"
    assert message_types(result) == [
        MessageType.INTAKE_ACKNOWLEDGEMENT,
        MessageType.EXTRACTION_FINDING,
        MessageType.DUPLICATE_FINDING,
        MessageType.EVIDENCE_FINDING,
        MessageType.POLICY_FINDING,
        MessageType.RISK_SUMMARY,
        MessageType.HUMAN_DECISION_REQUEST,
    ]
    assert all(message.case.case_id == "case-001" for message in result.messages)

    decided = coordinator.decide("approve case-001", "finance-001")

    assert decided.case.status.value == "approved"
    assert decided.ledger_entry is not None
    assert message_types(decided)[-2:] == [MessageType.HUMAN_DECISION_RECORDED, MessageType.LEDGER_RESULT]
    assert len(adapter.list_case_messages(room.room_id, "case-001")) == 10


def test_duplicate_invoice_rejects_without_ledger():
    _, _, coordinator, result = setup_case(duplicate_of="INV-000")

    assert result.checks.duplicate.status == "duplicate"
    decided = coordinator.decide("reject case-001 duplicate invoice", "finance-001")

    assert decided.case.status.value == "rejected"
    assert decided.ledger_entry is None
    assert MessageType.LEDGER_RESULT not in message_types(decided)


def test_missing_evidence_requests_clarification_without_ledger():
    _, _, coordinator, result = setup_case(missing_evidence=["delivery_confirmation"])

    assert result.case.status.value == "needs_evidence"
    assert result.checks.evidence.status == "missing"
    decided = coordinator.decide("request_clarification case-001", "finance-001")

    assert decided.case.status.value == "clarification_requested"
    assert decided.ledger_entry is None
    assert MessageType.LEDGER_RESULT not in message_types(decided)


def test_conflicting_evidence_remains_blocked_until_clarification_or_override():
    _, _, coordinator, result = setup_case(conflicting_evidence=["total_vs_line_items"])

    assert result.case.status.value == "blocked"
    with pytest.raises(ValueError, match="blocked or incomplete"):
        coordinator.decide("approve case-001", "finance-001")

    decided = coordinator.decide("request_clarification case-001", "finance-001")
    assert decided.case.status.value == "clarification_requested"
    assert decided.ledger_entry is None


def test_human_override_creates_ledger_and_audit_event():
    _, _, coordinator, result = setup_case(policy_warning="vendor is newly added")

    assert result.checks.policy.status == "warning"
    decided = coordinator.decide("override case-001 verified vendor exception", "finance-001")

    assert decided.case.status.value == "approved_with_exception"
    assert decided.ledger_entry is not None
    assert decided.audit_events[-1].event_type == "human_decision"
    assert decided.audit_events[-1].payload["action"] == "override"


def test_separate_cases_and_rooms_are_isolated():
    adapter = LocalFixtureSwitchAdapter()
    room_one = adapter.create_room("bursar-one")
    room_two = adapter.create_room("bursar-two")
    intake_one = make_intake(room_one.room_id, "case-001")
    intake_two = make_intake(room_two.room_id, "case-002")
    adapter.post_message(intake_one)
    adapter.post_message(intake_two)
    coordinator = LocalBursarWorkflowCoordinator(adapter)
    coordinator.start_case(intake_one)
    coordinator.start_case(intake_two)

    decided = coordinator.decide("approve case-001", "finance-001")

    assert decided.case.room_id == room_one.room_id
    assert coordinator.cases["case-002"].status.value == "pending_review"
    assert set(coordinator.ledger_entries) == {"case-001"}
    assert {message.case.case_id for message in adapter.list_case_messages(room_two.room_id, "case-002")} == {"case-002"}


def test_missing_actor_identity_is_rejected():
    _, _, coordinator, _ = setup_case()

    with pytest.raises(ValueError, match="actor identity"):
        coordinator.decide("approve case-001", "")


@pytest.mark.parametrize("command", ["reject case-001", "override case-001"])
def test_reject_and_override_without_reason_are_rejected(command):
    _, _, coordinator, _ = setup_case()

    with pytest.raises(ValueError, match="requires a reason"):
        coordinator.decide(command, "finance-001")


def test_agent_commands_cannot_create_decisions():
    _, _, coordinator, _ = setup_case()

    with pytest.raises(PermissionError, match="agent commands"):
        coordinator.decide("approve case-001", "extraction-agent", actor_type="agent")

    assert coordinator.cases["case-001"].status.value == "pending_review"
    assert coordinator.audit_events["case-001"] == []


def test_ledger_creation_cannot_bypass_decision_service():
    _, _, coordinator, result = setup_case()

    with pytest.raises(PermissionError, match="prior human approval"):
        from app.bursar.decisions import create_simulated_ledger_entry

        create_simulated_ledger_entry(result.case, coordinator.audit_events["case-001"])

    assert coordinator.ledger_entries == {}
