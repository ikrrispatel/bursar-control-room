import json

from app.switch_adapter import CaseCorrelation, MessageType, SenderType, SwitchMessage
from app.switch_adapter.render import protocol_envelope, render_mattermost_message, render_protocol_debug


def message(message_type: MessageType, payload: dict) -> SwitchMessage:
    return SwitchMessage(
        room_id="bursar-room",
        case=CaseCorrelation(case_id="case-render"),
        message_type=message_type,
        sender_type=SenderType.SYSTEM,
        sender_id="bursar-coordinator",
        payload=payload,
    )


def test_renderer_is_concise_but_typed_envelope_is_unchanged():
    typed = message(
        MessageType.HUMAN_DECISION_REQUEST,
        {
            "case_id": "case-render",
            "vendor_name": "Untrusted | Vendor",
            "invoice_number": "INV-1",
            "amount": "10.00",
            "currency": "USD",
            "findings": [
                {"finding_type": "extraction", "status": "complete", "explanation": "Fixture extraction"},
                {"finding_type": "duplicate", "status": "clear", "explanation": "No duplicate"},
                {"finding_type": "evidence", "status": "complete", "explanation": "Complete"},
                {"finding_type": "policy_matching", "status": "matched", "explanation": "Matched"},
                {"finding_type": "risk_summary", "status": "clear", "explanation": "Clear"},
            ],
            "allowed_actions": ["approve"],
        },
    )
    rendered = render_mattermost_message(typed)
    assert "Human decision required" in rendered
    assert "Untrusted \\| Vendor" in rendered
    assert "Pending human decision" in rendered
    assert "Ledger" in rendered
    assert protocol_envelope(typed)["message"] == typed.model_dump(mode="json")
    assert json.loads(render_protocol_debug(typed)) == protocol_envelope(typed)
    assert "{\"schema\"" not in rendered


def test_renderer_shows_ledger_gate_only_after_decision():
    pending = render_mattermost_message(
        message(
            MessageType.HUMAN_DECISION_REQUEST,
            {"case_id": "case-render", "vendor_name": "Acme", "invoice_number": "INV-1", "amount": "10.00", "currency": "USD", "findings": [], "allowed_actions": []},
        )
    )
    recorded = render_mattermost_message(
        message(MessageType.HUMAN_DECISION_RECORDED, {"case_id": "case-render", "action": "approve", "actor_id": "reviewer", "status": "approved"})
    )
    ledger = render_mattermost_message(
        message(MessageType.LEDGER_RESULT, {"case_id": "case-render", "status": "created", "entry_id": "entry-1", "amount": "10.00", "currency": "USD", "approved_by": "reviewer"})
    )
    assert "Locked" in pending
    assert "Created only after authorized human approval" in ledger
    assert "entry-1" not in pending
    assert "Human decision gate satisfied" in recorded


def test_renderer_does_not_change_agent_or_human_boundaries():
    agent = SwitchMessage(
        room_id="bursar-room",
        case=CaseCorrelation(case_id="case-render"),
        message_type=MessageType.RISK_SUMMARY,
        sender_type=SenderType.AGENT,
        sender_id="risk-agent",
        agent_role="risk_agent",
        payload={"case_id": "case-render", "finding_type": "risk_summary", "status": "clear", "explanation": "Fixture check"},
    )
    rendered = render_mattermost_message(agent)
    assert "risk summary" in rendered.casefold()
    assert "approve" not in rendered.casefold()
