import pytest

from app.bursar.evidence import sha256_file
from app.bursar.scenarios import evaluate_scenario, load_scenarios
from app.bursar.workflow import LocalBursarWorkflowCoordinator


def test_all_scenarios_load_deterministically():
    first = [scenario.model_dump(mode="json") for scenario in load_scenarios()]
    second = [scenario.model_dump(mode="json") for scenario in load_scenarios()]
    assert first == second
    assert [item["name"] for item in first] == [
        "clean_invoice", "duplicate_invoice", "missing_evidence",
        "conflicting_evidence", "human_override",
    ]


def test_evidence_hashes_are_deterministic():
    for scenario in load_scenarios():
        for evidence in scenario.evidence_files:
            assert sha256_file(evidence.path) == sha256_file(evidence.path)


def test_clean_invoice_has_complete_passport_and_can_be_approved():
    fixture = load_scenarios()[0]
    result, evaluation = LocalBursarWorkflowCoordinator().run_scenario(fixture)
    assert evaluation.duplicate_result["duplicate_status"] == "clear"
    assert evaluation.matching_result["match_status"] == "matched"
    assert result.case.status.value == "approved"
    assert result.evidence_passport.case_id == fixture.case_id
    assert len(result.evidence_passport.evidence_references) == 3
    assert result.ledger_entry is not None


def test_duplicate_invoice_is_blocked_and_exposes_prior_case():
    fixture = load_scenarios()[1]
    result, _ = LocalBursarWorkflowCoordinator().run_scenario(fixture)
    assert result.checks.duplicate.status == "duplicate"
    assert fixture.prior_case_id in result.checks.duplicate.explanation
    assert result.case.status.value == "rejected"
    assert result.ledger_entry is None


def test_missing_evidence_requests_clarification_without_ledger():
    result, _ = LocalBursarWorkflowCoordinator().run_scenario(load_scenarios()[2])
    assert result.checks.evidence.status == "missing"
    assert result.case.status.value == "clarification_requested"
    assert result.ledger_entry is None


def test_conflicting_evidence_escalates_without_ledger():
    result, _ = LocalBursarWorkflowCoordinator().run_scenario(load_scenarios()[3])
    assert result.checks.policy.status == "conflict"
    assert result.case.status.value == "clarification_requested"
    assert result.ledger_entry is None


def test_human_override_requires_reason_and_creates_approved_with_exception():
    fixture = load_scenarios()[4]
    coordinator = LocalBursarWorkflowCoordinator()
    room = coordinator.adapter.create_room("room-override")
    evaluation = evaluate_scenario(fixture, room.room_id)
    coordinator.adapter.post_message(evaluation.intake_message)
    coordinator.start_case(evaluation.intake_message)
    with pytest.raises(ValueError, match="requires a reason"):
        coordinator.decide("override scenario-override", "finance-001")
    result = coordinator.decide(
        "override scenario-override verified vendor exception", "finance-001"
    )
    assert result.case.status.value == "approved_with_exception"
    assert result.ledger_entry is not None
    assert result.audit_events[-1].payload["reason"] == "verified vendor exception"


def test_evidence_is_case_scoped_and_timeline_is_ordered():
    clean, duplicate = load_scenarios()[:2]
    coordinator = LocalBursarWorkflowCoordinator()
    clean_result, _ = coordinator.run_scenario(clean)
    duplicate_result, _ = coordinator.run_scenario(duplicate)
    assert all(ref.case_id == clean.case_id for ref in clean_result.evidence_passport.evidence_references)
    assert all(ref.case_id == duplicate.case_id for ref in duplicate_result.evidence_passport.evidence_references)
    clean_events = coordinator.timeline_for_case(clean.case_id)
    duplicate_events = coordinator.timeline_for_case(duplicate.case_id)
    assert [event.sequence for event in clean_events] == sorted(event.sequence for event in clean_events)
    assert [event.sequence for event in duplicate_events] == sorted(event.sequence for event in duplicate_events)
    assert all(event.case_id == clean.case_id for event in clean_events)
    assert all(event.case_id == duplicate.case_id for event in duplicate_events)
    assert {event.case_id for event in clean_events}.isdisjoint({event.case_id for event in duplicate_events})


def test_cross_case_evidence_reference_is_rejected():
    first, second = load_scenarios()[:2]
    coordinator = LocalBursarWorkflowCoordinator()
    first_room = coordinator.adapter.create_room("room-one")
    first_evaluation = evaluate_scenario(first, first_room.room_id)
    coordinator.adapter.post_message(first_evaluation.intake_message)
    coordinator.start_case(first_evaluation.intake_message)
    second_room = coordinator.adapter.create_room("room-two")
    second_evaluation = evaluate_scenario(second, second_room.room_id)
    second_evaluation.intake_message.payload["evidence"] = first_evaluation.intake_message.payload["evidence"]
    coordinator.adapter.post_message(second_evaluation.intake_message)
    with pytest.raises(ValueError, match="another case"):
        coordinator.start_case(second_evaluation.intake_message)
