import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app.agents import FixtureAgentProvider
from app.api.main import app
from app.api.routes import configure_live_boundary
from app.bursar.scenarios import evaluate_scenario, load_scenarios
from app.switch_adapter import (
    LocalFixtureSwitchAdapter,
    MattermostSwitchAdapter,
    SwitchConfiguration,
)
from app.switch_adapter.boundary import LiveMattermostBursarBoundary, SwitchCommandRequest


def test_mocked_live_message_to_decision_flow_posts_back_to_mattermost():
    post_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal post_count
        if request.method == "GET" and request.url.path == "/api/v4/channels/channel-1":
            return httpx.Response(200, json={"id": "channel-1", "team_id": "team-1", "display_name": "Bursar", "purpose": "AP"})
        if request.method == "POST" and request.url.path == "/api/v4/posts":
            post_count += 1
            body = json.loads(request.content)
            return httpx.Response(201, json={"id": f"provider-post-{post_count}", "channel_id": "channel-1", "message": body["message"]})
        raise AssertionError(f"unexpected provider request: {request.method} {request.url.path}")

    settings = SwitchConfiguration(base_url="https://mattermost.test", token="token", team_id="team-1", channel_id="channel-1")
    adapter = MattermostSwitchAdapter(settings, httpx.Client(transport=httpx.MockTransport(handler)))
    adapter.create_room("Bursar")
    boundary = LiveMattermostBursarBoundary(adapter, "channel-1", agent_provider=FixtureAgentProvider())
    intake = evaluate_scenario(load_scenarios()[0], "channel-1").intake_message

    initial = boundary.receive_message(intake)
    final = boundary.receive_command(
        SwitchCommandRequest(room_id="channel-1", command="approve scenario-clean", actor_id="finance-1")
    )

    assert initial.case.status.value == "pending_review"
    assert final.case.status.value == "approved"
    assert final.ledger_entry is not None
    extraction_messages = [message for message in final.messages if message.agent_role == "intake_extraction_agent"]
    assert extraction_messages[0].payload["mode"] == "fixture"
    assert extraction_messages[0].case.case_id == "scenario-clean"
    assert post_count == 10


def test_api_boundary_validates_room_and_routes_local_offline_flow():
    adapter = LocalFixtureSwitchAdapter()
    room = adapter.create_room("bursar")
    boundary = LiveMattermostBursarBoundary(adapter, room.room_id)
    configure_live_boundary(boundary)
    client = TestClient(app)
    intake = evaluate_scenario(load_scenarios()[0], room.room_id).intake_message

    try:
        response = client.post("/switch/messages", json=intake.model_dump(mode="json"))
        assert response.status_code == 200
        command = client.post(
            "/switch/commands",
            json={"room_id": room.room_id, "command": "approve scenario-clean", "actor_id": "finance-1"},
        )
        assert command.status_code == 200
        assert command.json()["case"]["status"] == "approved"
        wrong_room = client.post(
            "/switch/commands",
            json={"room_id": "other-room", "command": "approve scenario-clean", "actor_id": "finance-1"},
        )
        assert wrong_room.status_code == 400
    finally:
        configure_live_boundary(None)


def test_live_boundary_rejects_non_intake_and_agent_messages():
    adapter = LocalFixtureSwitchAdapter()
    room = adapter.create_room("bursar")
    boundary = LiveMattermostBursarBoundary(adapter, room.room_id)
    intake = evaluate_scenario(load_scenarios()[0], room.room_id).intake_message
    unsupported = intake.model_copy(update={"message_type": "human_decision_request"})

    with pytest.raises(ValueError, match="invoice_intake"):
        boundary.receive_message(unsupported)


def test_live_boundary_uses_allowlisted_command_parser():
    adapter = LocalFixtureSwitchAdapter()
    room = adapter.create_room("bursar")
    boundary = LiveMattermostBursarBoundary(adapter, room.room_id)
    intake = evaluate_scenario(load_scenarios()[0], room.room_id).intake_message
    boundary.receive_message(intake)

    with pytest.raises(ValueError, match="unsupported"):
        boundary.receive_command(SwitchCommandRequest(room_id=room.room_id, command="pay scenario-clean", actor_id="finance-1"))
