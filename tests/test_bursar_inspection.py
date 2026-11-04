from fastapi.testclient import TestClient

from app.api.main import app
from app.api.routes import configure_bursar_coordinator, configure_live_boundary
from app.bursar.inspection import BursarInspectionService
from app.bursar.scenarios import load_scenarios
from app.bursar.workflow import LocalBursarWorkflowCoordinator
from app.switch_adapter import LocalFixtureSwitchAdapter
from app.ui.bursar_dashboard import escape_dashboard_text, status_chip_html


def populated_coordinator() -> LocalBursarWorkflowCoordinator:
    coordinator = LocalBursarWorkflowCoordinator(LocalFixtureSwitchAdapter())
    coordinator.run_scenario(load_scenarios()[0])
    return coordinator


def test_case_list_and_detail_are_read_only():
    coordinator = populated_coordinator()
    configure_bursar_coordinator(coordinator)
    client = TestClient(app)

    listed = client.get("/bursar/cases")
    detail = client.get("/bursar/cases/scenario-clean")

    assert listed.status_code == 200
    assert listed.json()["cases"][0]["status_label"] == "Approved"
    assert detail.status_code == 200
    assert detail.json()["case"]["case_id"] == "scenario-clean"
    assert detail.json()["message_count"] == 9
    assert coordinator.cases["scenario-clean"].status.value == "approved"


def test_passport_findings_decision_ledger_and_timeline_queries():
    coordinator = populated_coordinator()
    configure_bursar_coordinator(coordinator)
    client = TestClient(app)

    passport = client.get("/bursar/cases/scenario-clean/passport")
    findings = client.get("/bursar/cases/scenario-clean/findings")
    decision = client.get("/bursar/cases/scenario-clean/decision")
    ledger = client.get("/bursar/cases/scenario-clean/ledger")
    timeline = client.get("/bursar/cases/scenario-clean/timeline")

    assert passport.status_code == findings.status_code == decision.status_code == ledger.status_code == timeline.status_code == 200
    assert passport.json()["passport"]["case_id"] == "scenario-clean"
    assert findings.json()["findings"]
    assert decision.json()["decision"]["action"] == "approve"
    assert ledger.json()["ledger"]["case_id"] == "scenario-clean"
    sequences = [event["sequence"] for event in timeline.json()["events"]]
    assert sequences == sorted(sequences)


def test_empty_and_missing_case_states():
    configure_bursar_coordinator(LocalBursarWorkflowCoordinator())
    client = TestClient(app)
    assert client.get("/bursar/cases").json() == {"cases": []}
    assert client.get("/bursar/cases/missing").status_code == 404
    assert client.get("/bursar/cases/missing/passport").status_code == 404
    assert client.get("/bursar/cases/missing/timeline").status_code == 404


def test_status_labels_and_untrusted_text_are_escaped():
    assert BursarInspectionService.status_label("pending_review") == "Ready"
    assert BursarInspectionService.status_label("needs_evidence") == "Needs evidence"
    assert BursarInspectionService.status_label("approved_with_exception") == "Approved with exception"
    unsafe = "<script>alert('x')</script> & invoice"
    escaped = escape_dashboard_text(unsafe)
    assert escaped == "&lt;script&gt;alert(&#x27;x&#x27;)&lt;/script&gt; &amp; invoice"
    assert "<script>" not in status_chip_html(unsafe)


def test_dashboard_has_no_case_mutation_routes():
    assert not any(
        getattr(route, "path", "").startswith("/bursar") and "POST" in getattr(route, "methods", set())
        for route in app.routes
    )
    configure_live_boundary(None)
