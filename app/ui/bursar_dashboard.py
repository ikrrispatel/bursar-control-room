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
    st.title("Bursar Control Room")
    st.info("Inspection surface only. Intake, agent collaboration, and human decisions happen in Mattermost/Switch.")
    service = load_fixture_inspection()
    cases = service.list_cases().cases
    if not cases:
        st.info("No Bursar cases are available yet.")
        return

    selected = st.selectbox(
        "Case",
        cases,
        format_func=lambda case: f"{escape_dashboard_text(case.case_id)} — {escape_dashboard_text(case.status_label)}",
    )
    st.markdown(status_chip_html(selected.status), unsafe_allow_html=True)
    detail = service.case_detail(selected.case_id)
    passport = service.evidence_passport(selected.case_id)

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
    decision = service.decision(selected.case_id).decision
    st.code(json.dumps(decision.model_dump(mode="json") if decision else None, indent=2), language="json")
    st.subheader("Simulated ledger result")
    ledger = service.ledger(selected.case_id).ledger
    st.code(json.dumps(ledger.model_dump(mode="json") if ledger else None, indent=2), language="json")


if __name__ == "__main__":
    main()
