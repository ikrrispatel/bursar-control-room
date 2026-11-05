from __future__ import annotations

import html
import json

import streamlit as st

from app.bursar.inspection import BursarInspectionService, STATUS_LABELS
from app.bursar.repository import BursarRepository
from app.bursar.scenarios import load_scenarios
from app.bursar.workflow import LocalBursarWorkflowCoordinator
from app.agents import FixtureAgentProvider
from app.switch_adapter import LocalFixtureSwitchAdapter


def escape_dashboard_text(value: object) -> str:
    return html.escape(str(value), quote=True)


def status_chip_html(status: str) -> str:
    label = BursarInspectionService.status_label(status)
    return f'<span class="bursar-status-chip">{escape_dashboard_text(label)}</span>'


def _risk_summary(checks: dict) -> str:
    status = str(checks.get("risk", {}).get("status", "unknown"))
    return {
        "clear": "Clear",
        "warning": "Review warning",
        "blocked": "Blocked",
        "needs_evidence": "Needs evidence",
    }.get(status, status.replace("_", " ").title())


def _evidence_summary(checks: dict) -> str:
    status = str(checks.get("evidence", {}).get("status", "unknown"))
    return "Complete" if status == "complete" else "Missing"


def _human_gate_summary(decision: object) -> str:
    if decision is None:
        return "Awaiting finance reviewer"
    return f"Recorded: {decision.action.value}"


def _ledger_summary(ledger: object) -> str:
    return "Created" if ledger is not None else "Not created"


def _stage_html(title: str, state: str, detail: str, tone: str) -> str:
    return (
        f'<div class="bursar-stage bursar-stage-{escape_dashboard_text(tone)}">'
        f'<div class="bursar-stage-title">{escape_dashboard_text(title)}</div>'
        f'<div class="bursar-stage-state">{escape_dashboard_text(state)}</div>'
        f'<div class="bursar-stage-detail">{escape_dashboard_text(detail)}</div>'
        "</div>"
    )


@st.cache_resource
def load_fixture_inspection() -> BursarInspectionService:
    repository = BursarRepository.from_environment_optional()
    adapter = LocalFixtureSwitchAdapter()
    coordinator = LocalBursarWorkflowCoordinator(
        adapter,
        agent_provider=FixtureAgentProvider(),
        repository=repository,
    )
    if not coordinator.cases:
        for fixture in load_scenarios():
            coordinator.run_scenario(fixture)
    return BursarInspectionService(coordinator)


def main() -> None:
    st.set_page_config(page_title="Bursar Control Room", page_icon="BCR", layout="wide")
    st.markdown(
        """
        <style>
        .bursar-stage { border: 1px solid #d9e2ec; border-radius: 12px; padding: 14px; min-height: 104px; background: #f8fafc; }
        .bursar-stage-title { color: #52606d; font-size: 0.78rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em; }
        .bursar-stage-state { color: #102a43; font-size: 1.05rem; font-weight: 700; margin-top: 8px; }
        .bursar-stage-detail { color: #627d98; font-size: 0.82rem; margin-top: 4px; }
        .bursar-stage-ok { border-top: 4px solid #2f855a; }
        .bursar-stage-wait { border-top: 4px solid #d69e2e; }
        .bursar-stage-blocked { border-top: 4px solid #c53030; }
        .bursar-kicker { color: #52606d; font-size: 0.9rem; margin-top: -0.5rem; }
        </style>
        """,
        unsafe_allow_html=True,
    )
    st.title("Bursar Control Room")
    st.markdown('<div class="bursar-kicker">Switch room collaboration → deterministic controls → human-owned ledger gate</div>', unsafe_allow_html=True)
    st.info("Read-only inspection surface. Intake, agent collaboration, and human decisions happen in the Switch-connected Bursar Control Room.")
    service = load_fixture_inspection()
    cases = service.list_cases().cases
    if not cases:
        st.info("No Bursar cases are available yet.")
        return

    st.sidebar.header("Guided inspection")
    st.sidebar.caption("Fixture mode only: deterministic synthetic cases. This view does not claim live document extraction or replay the Switch room.")
    guided = st.sidebar.checkbox("Guided demo mode", value=True)
    selected = st.selectbox(
        "Synthetic case" if guided else "Case",
        cases,
        format_func=lambda case: f"{escape_dashboard_text(case.case_id)} — {escape_dashboard_text(case.status_label)}",
    )
    detail = service.case_detail(selected.case_id)
    passport = service.evidence_passport(selected.case_id)
    decision = service.decision(selected.case_id).decision
    ledger = service.ledger(selected.case_id).ledger
    risk = _risk_summary(detail.checks)
    evidence = _evidence_summary(detail.checks)
    gate = _human_gate_summary(decision)
    ledger_state = _ledger_summary(ledger)

    st.markdown(status_chip_html(selected.status), unsafe_allow_html=True)
    st.subheader("Control path")
    st.caption("The dashboard observes this path; it cannot advance any stage.")
    stage_tone = "blocked" if selected.status in {"blocked", "needs_evidence", "clarification_requested"} else "ok"
    gate_tone = "ok" if decision is not None else "wait"
    ledger_tone = "ok" if ledger is not None else "wait"
    stages = [
        _stage_html("1 · Intake", "Received", f"{selected.vendor_name or 'Unknown vendor'} · {selected.invoice_number or 'Unknown invoice'}", "ok"),
        _stage_html("2 · Findings", risk, f"Evidence: {evidence} · {len(service.findings(selected.case_id).findings)} typed findings", stage_tone),
        _stage_html("3 · Human decision gate", gate, "Finance reviewer required", gate_tone),
        _stage_html("4 · Simulated ledger", ledger_state, "Only after approve or override", ledger_tone),
    ]
    for column, stage in zip(st.columns(4), stages):
        with column:
            st.markdown(stage, unsafe_allow_html=True)

    metric_columns = st.columns(5)
    metric_columns[0].metric("Status", selected.status_label)
    metric_columns[1].metric("Risk", risk)
    metric_columns[2].metric("Evidence", evidence)
    metric_columns[3].metric("Human owner", decision.actor_id if decision else "Finance reviewer")
    metric_columns[4].metric("Ledger", ledger_state)

    st.subheader("Case detail")
    st.text(f"Case ID: {selected.case_id}")
    st.text(f"Vendor: {selected.vendor_name or 'Unknown'}")
    st.text(f"Invoice: {selected.invoice_number or 'Unknown'}")
    st.text(f"Amount: {selected.total or 'Unknown'} {selected.currency or ''}".strip())
    st.text(f"Messages: {detail.message_count}")

    st.subheader("Evidence passport")
    st.text("Extracted invoice fields")
    st.code(json.dumps(passport.extracted_invoice_fields, indent=2, default=str), language="json")
    for reference in passport.evidence_references:
        st.text(f"{reference.kind}: {reference.file_name} | SHA-256: {reference.sha256} | {reference.source_location}")

    st.subheader("Agent findings")
    for finding in service.findings(selected.case_id).findings:
        with st.expander(escape_dashboard_text(finding.agent_name)):
            st.text(f"Status: {finding.status} | Confidence: {finding.confidence:.2f}")
            st.text(finding.explanation)

    st.subheader("Case timeline")
    for event in service.timeline(selected.case_id):
        st.text(f"#{event.sequence} {event.event_type} — {event.actor_id}")
        st.code(json.dumps(event.payload, indent=2, default=str), language="json")

    st.subheader("Human decision")
    st.code(json.dumps(decision.model_dump(mode="json") if decision else None, indent=2), language="json")
    st.subheader("Simulated ledger result")
    st.code(json.dumps(ledger.model_dump(mode="json") if ledger else None, indent=2), language="json")


if __name__ == "__main__":
    main()
