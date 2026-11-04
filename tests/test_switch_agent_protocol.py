import json

import httpx
import pytest

from app.agents import FixtureAgentProvider
from app.bursar.workflow import LocalBursarWorkflowCoordinator
from app.switch_adapter import (
    CaseCorrelation,
    MessageType,
    SenderType,
    SwitchAgentConfiguration,
    SwitchAgentProtocolAdapter,
    SwitchAgentTransportError,
    SwitchMessage,
)
from app.switch_adapter.runtime import SwitchBursarRuntime


def configuration() -> SwitchAgentConfiguration:
    return SwitchAgentConfiguration(
        base_url="http://switch.local",
        agent_id="agent-1",
        agent_name="bursar-reviewer",
        api_key="test-key",
        room_id="room-bursar",
    )


def message(case_id: str = "case-1") -> SwitchMessage:
    return SwitchMessage(
        room_id="room-bursar",
        case=CaseCorrelation(case_id=case_id),
        message_type=MessageType.INTAKE_ACKNOWLEDGEMENT,
        sender_type=SenderType.AGENT,
        sender_id="agent-1",
        agent_role="intake_agent",
        payload={"case_id": case_id, "status": "received", "message": "received"},
    )


def test_switch_post_uses_agent_message_endpoint_and_never_mattermost():
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"event_id": "switch-event-1"})

    adapter = SwitchAgentProtocolAdapter(configuration(), httpx.Client(transport=httpx.MockTransport(handler)))
    posted = adapter.post_message(message())
    assert posted.message_id == "switch-event-1"
    assert requests[0].url.path == "/agents/agent-1/message"
    body = json.loads(requests[0].content)
    assert body["room_id"] == "room-bursar"
    assert "[BURSAR]" in body["content"]
    assert "[agent=agent-1]" in body["content"]
    assert requests[0].headers["authorization"] == "Bearer test-key"


def test_switch_configuration_defaults_to_bursar_reviewer(monkeypatch):
    monkeypatch.setenv("SWITCH_AGENT_BASE_URL", "http://switch.local")
    monkeypatch.setenv("SWITCH_AGENT_ID", "bursar-agent-id")
    monkeypatch.setenv("SWITCH_AGENT_API_KEY", "test-key")
    monkeypatch.setenv("SWITCH_ROOM_ID", "room-bursar")
    monkeypatch.delenv("SWITCH_AGENT_NAME", raising=False)
    config = SwitchAgentConfiguration.from_env()
    assert config.agent_name == "bursar-reviewer"


def test_switch_event_stream_parses_domain_message():
    stream = b"event: message\ndata: {\"type\":\"message\",\"room_id\":\"room-bursar\",\"payload\":{\"body\":\"approve case-1\"}}\n\n"
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, content=stream, headers={"content-type": "text/event-stream"})

    adapter = SwitchAgentProtocolAdapter(configuration(), httpx.Client(transport=httpx.MockTransport(handler)))
    events = list(adapter.stream_events())
    assert events[0]["payload"]["body"] == "approve case-1"
    assert requests[0].url.params["rooms"] == "room-bursar"


def test_console_owned_agent_stream_fails_without_taking_over_managed_agent():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            410,
            json={"detail": "The agents controller no longer serves the agent connection"},
        )

    adapter = SwitchAgentProtocolAdapter(
        configuration(),
        httpx.Client(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(SwitchAgentTransportError, match="owned by the local Switch Console agent host"):
        list(adapter.stream_events())


def test_runtime_processes_switch_intake_and_human_decision():
    adapter = SwitchAgentProtocolAdapter(
        configuration(),
        httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"event_id": "outbound"}))),
    )
    runtime = SwitchBursarRuntime(adapter, LocalBursarWorkflowCoordinator(adapter, agent_provider=FixtureAgentProvider()))
    payload = {
        "sender": "human-finance",
        "body": "/bursar intake {\"case_id\":\"case-live\",\"vendor_name\":\"Acme\",\"invoice_number\":\"INV-1\",\"total\":\"10.00\",\"currency\":\"USD\"}",
    }
    result = runtime.handle_event({"type": "message", "room_id": "room-bursar", "payload": payload})
    assert result and result.case.case_id == "case-live"
    decision = runtime.handle_event({"type": "message", "room_id": "room-bursar", "payload": {"sender": "finance-human", "body": "approve case-live"}})
    assert decision and decision.case.status.value == "approved"


def test_runtime_ignores_switch_platform_messages():
    adapter = SwitchAgentProtocolAdapter(
        configuration(),
        httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"event_id": "outbound"}))),
    )
    runtime = SwitchBursarRuntime(adapter, LocalBursarWorkflowCoordinator(adapter))
    assert runtime.handle_event({"type": "message", "room_id": "room-bursar", "payload": {"sender_kind": "platform", "body": "approve case-1"}}) is None
