import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.bursar.scenarios import load_scenarios
from app.bursar.workflow import LocalBursarWorkflowCoordinator


def main() -> int:
    coordinator = LocalBursarWorkflowCoordinator()
    for fixture in load_scenarios():
        result, evaluation = coordinator.run_scenario(fixture)
        expected = fixture.expected
        actual_ledger = result.ledger_entry is not None
        if (
            evaluation.duplicate_result["duplicate_status"] != expected.duplicate_status
            or evaluation.matching_result["match_status"] != expected.matching_status
            or actual_ledger != expected.ledger_result
        ):
            raise AssertionError(f"scenario verification failed: {fixture.name}")
        print(
            f"{fixture.name}: duplicate={evaluation.duplicate_result['duplicate_status']} "
            f"matching={evaluation.matching_result['match_status']} "
            f"case={result.case.status.value} ledger={'created' if actual_ledger else 'none'}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
