from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.switch_adapter import (
    AgentRole,
    CaseCorrelation,
    LocalFixtureSwitchAdapter,
    MessageType,
    SwitchMessage,
)


def make_agent_message(room_id: str, case_id: str, message_type=MessageType.EXTRACTION_FINDING):
    return SwitchMessage(
        room_id=room_id,
        case=CaseCorrelation(case_id=case_id, thread_key=f"thread-{case_id}"),
        message_type=message_type,
        sender_type="agent",
        sender_id="extraction-agent",
        agent_role=AgentRole.EXTRACTION_AGENT,
        payload={"field": "invoice_number", "value": "INV-001"},
        timestamp=datetime.now(timezone.utc),
    )


def test_room_creation():
    adapter = LocalFixtureSwitchAdapter()

    room = adapter.create_room("bursar-control-room", "Invoice review")

    assert room.name == "bursar-control-room"
    assert room.purpose == "Invoice review"
    assert room.room_id.startswith("room-")


def test_typed_agent_message_posting_and_case_correlation():
    adapter = LocalFixtureSwitchAdapter()
    room = adapter.create_room("bursar")
    message = make_agent_message(room.room_id, "case-001")

    posted = adapter.post_message(message)

    assert posted.message_type == MessageType.EXTRACTION_FINDING
    assert posted.agent_role == AgentRole.EXTRACTION_AGENT
    assert posted.case.case_id == "case-001"
    assert posted.payload["field"] == "invoice_number"


def test_case_isolation():
    adapter = LocalFixtureSwitchAdapter()
    room = adapter.create_room("bursar")
    adapter.post_message(make_agent_message(room.room_id, "case-001"))
    adapter.post_message(make_agent_message(room.room_id, "case-002"))

    messages = adapter.list_case_messages(room.room_id, "case-001")

    assert len(messages) == 1
    assert messages[0].case.case_id == "case-001"


def test_malformed_payload_is_rejected():
    adapter = LocalFixtureSwitchAdapter()
    room = adapter.create_room("bursar")

    with pytest.raises(ValidationError):
        SwitchMessage(
            room_id=room.room_id,
            case=CaseCorrelation(case_id="case-001"),
            message_type=MessageType.EXTRACTION_FINDING,
            sender_type="agent",
            sender_id="extraction-agent",
            agent_role=AgentRole.EXTRACTION_AGENT,
            payload="not structured",
        )

    with pytest.raises(ValidationError):
        SwitchMessage(
            room_id=room.room_id,
            case=CaseCorrelation(case_id="case-001"),
            message_type=MessageType.EXTRACTION_FINDING,
            sender_type="agent",
            sender_id="extraction-agent",
            payload={"field": "invoice_number"},
        )


def test_case_id_is_required_for_case_message():
    with pytest.raises(ValidationError):
        CaseCorrelation(case_id="")


def test_unsupported_message_type_is_rejected():
    with pytest.raises(ValidationError):
        SwitchMessage(
            room_id="room-001",
            case={"case_id": "case-001"},
            message_type="payment_approved",
            sender_type="system",
            sender_id="system",
            payload={"status": "approved"},
        )


@pytest.mark.parametrize(
    ("command", "action", "reason"),
    [
        ("approve case-001", "approve", None),
        ("/reject case-001 duplicate invoice", "reject", "duplicate invoice"),
        ("request_clarification case-001", "request_clarification", None),
        ("override case-001 verified exception", "override", "verified exception"),
    ],
)
def test_valid_human_command_parsing(command, action, reason):
    result = LocalFixtureSwitchAdapter().parse_human_command(command, "finance-001")

    assert result.action == action
    assert result.case_id == "case-001"
    assert result.actor_id == "finance-001"
    assert result.reason == reason


@pytest.mark.parametrize(
    "command",
    [
        "pay case-001",
        "approve",
        "reject case-001",
        "override case-001",
        "approve case-001 extra words are okay",
    ],
)
def test_unsupported_or_invalid_human_commands_are_rejected(command):
    with pytest.raises(ValueError):
        LocalFixtureSwitchAdapter().parse_human_command(command, "finance-001")


def test_agent_impersonation_is_rejected():
    with pytest.raises(ValueError, match="agents cannot"):
        SwitchMessage(
            room_id="room-001",
            case=CaseCorrelation(case_id="case-001"),
            message_type=MessageType.HUMAN_DECISION_RECORDED,
            sender_type="agent",
            sender_id="extraction-agent",
            agent_role=AgentRole.EXTRACTION_AGENT,
            payload={"action": "approve"},
        )
