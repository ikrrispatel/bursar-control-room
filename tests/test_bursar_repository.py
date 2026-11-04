from pathlib import Path

import pytest

from app.bursar.repository import BursarRepository, BursarRepositoryError
from app.bursar.scenarios import load_scenarios
from app.bursar.workflow import LocalBursarWorkflowCoordinator


def test_schema_initializes_and_persists_across_instances(tmp_path: Path):
    path = tmp_path / "bursar.db"
    repository = BursarRepository(path)
    coordinator = LocalBursarWorkflowCoordinator(repository=repository)
    result, _ = coordinator.run_scenario(load_scenarios()[0])
    repository.close()

    restored = LocalBursarWorkflowCoordinator(repository=BursarRepository(path))
    assert restored.cases[result.case.case_id].status == result.case.status
    assert restored.repository.get_passport(result.case.case_id).case_id == result.case.case_id
    assert len(restored.messages[result.case.case_id]) >= 7


def test_messages_evidence_timeline_and_case_isolation(tmp_path: Path):
    repository = BursarRepository(tmp_path / "bursar.db")
    coordinator = LocalBursarWorkflowCoordinator(repository=repository)
    scenarios = load_scenarios()
    first, _ = coordinator.run_scenario(scenarios[0])
    second, _ = coordinator.run_scenario(scenarios[1])

    assert all(message.case.case_id == first.case.case_id for message in repository.list_messages(first.case.case_id))
    assert all(event.case_id == first.case.case_id for event in repository.list_timeline(first.case.case_id))
    assert repository.list_messages(first.case.case_id, second.case.room_id) == []
    passport = repository.get_passport(first.case.case_id)
    assert passport and all(ref.case_id == first.case.case_id for ref in passport.evidence_references)
    sequences = [event.sequence for event in repository.list_timeline(first.case.case_id)]
    assert sequences == sorted(sequences)


def test_decision_and_ledger_gating_are_persisted(tmp_path: Path):
    repository = BursarRepository(tmp_path / "bursar.db")
    coordinator = LocalBursarWorkflowCoordinator(repository=repository)
    scenarios = load_scenarios()
    rejected, _ = coordinator.run_scenario(scenarios[1])
    assert repository.get_decision(rejected.case.case_id).action.value == "reject"
    assert repository.get_ledger_entry(rejected.case.case_id) is None

    clean, _ = coordinator.run_scenario(scenarios[0])
    assert repository.get_decision(clean.case.case_id).action.value == "approve"
    assert repository.get_ledger_entry(clean.case.case_id).case_id == clean.case.case_id


def test_duplicate_events_are_ignored(tmp_path: Path):
    repository = BursarRepository(tmp_path / "bursar.db")
    coordinator = LocalBursarWorkflowCoordinator(repository=repository)
    result, _ = coordinator.run_scenario(load_scenarios()[0])
    event = result.audit_events[0]
    assert repository.save_audit_event(event) is False
    assert len(repository.list_audit_events(result.case.case_id)) == 1


def test_database_failure_is_safe(tmp_path: Path):
    repository = BursarRepository(tmp_path / "bursar.db")
    repository.close()
    with pytest.raises(BursarRepositoryError, match="Bursar cases"):
        repository.list_cases()
