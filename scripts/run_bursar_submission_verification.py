from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.bursar.scenarios import load_scenarios
from app.bursar.workflow import LocalBursarWorkflowCoordinator


def main() -> int:
    coordinator = LocalBursarWorkflowCoordinator()
    scenarios = {fixture.name: fixture for fixture in load_scenarios()}
    results = {}
    for name, fixture in scenarios.items():
        result, evaluation = coordinator.run_scenario(fixture)
        passport = result.evidence_passport
        timeline = coordinator.timeline_for_case(fixture.case_id)
        assert passport.case_id == fixture.case_id and passport.evidence_references
        assert timeline and all(event.case_id == fixture.case_id for event in timeline)
        assert (result.ledger_entry is not None) == fixture.expected.ledger_result
        results[name] = result

    assert results["clean_invoice"].case.status.value == "approved"
    assert results["clean_invoice"].ledger_entry is not None
    assert results["duplicate_invoice"].case.status.value == "rejected"
    assert results["duplicate_invoice"].checks.duplicate.status == "duplicate"
    assert results["duplicate_invoice"].ledger_entry is None
    assert results["missing_evidence"].case.status.value == "clarification_requested"
    assert results["missing_evidence"].ledger_entry is None
    assert results["conflicting_evidence"].case.status.value == "clarification_requested"
    assert results["conflicting_evidence"].ledger_entry is None
    override = results["human_override"]
    assert override.case.status.value == "approved_with_exception"
    assert override.evidence_passport.human_decision and override.evidence_passport.human_decision.reason
    assert override.ledger_entry is not None
    print("BURSAR SUBMISSION VERIFICATION PASSED")
    print("clean approval, duplicate block, evidence clarification, conflict escalation, reasoned override, passport, timeline, and ledger gates verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
