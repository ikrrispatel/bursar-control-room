import json
import os

import httpx
import pytest

from app.agents import FixtureAgentProvider
from app.bursar.workflow import LocalBursarWorkflowCoordinator
from app.switch_adapter.boundary import LiveMattermostBursarBoundary
from app.switch_adapter.agent_config import SwitchAgentConfiguration
from app.switch_adapter.config import MattermostRelayConfiguration, SwitchConfiguration
from app.switch_adapter.env import load_env_file
from app.switch_adapter.http import MattermostSwitchAdapter
from app.switch_adapter.mattermost_relay import MattermostBursarRelay


ROOM = "bursar-channel"


def make_relay(posts: list[dict], sent: list[dict]) -> MattermostBursarRelay:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path.endswith(f"/channels/{ROOM}/posts"):
            return httpx.Response(200, json={"order": [post["id"] for post in posts], "posts": {post["id"]: post for post in posts}})
        if request.method == "POST" and request.url.path == "/api/v4/posts":
            body = json.loads(request.content)
            sent.append(body)
            return httpx.Response(201, json={"id": f"out-{len(sent)}", "channel_id": body["channel_id"]})
        raise AssertionError(f"unexpected request {request.method} {request.url}")

    configuration = SwitchConfiguration(
        base_url="http://mattermost.local",
        token="test-token",
        team_id="team-1",
        channel_id=ROOM,
        agent_user_id="switch-agent-user",
    )
    adapter = MattermostSwitchAdapter(configuration, httpx.Client(transport=httpx.MockTransport(handler)))
    boundary = LiveMattermostBursarBoundary(
        adapter,
        ROOM,
        coordinator=LocalBursarWorkflowCoordinator(adapter, agent_provider=FixtureAgentProvider()),
    )
    return MattermostBursarRelay(adapter, boundary)


def intake_post(post_id: str = "human-intake") -> dict:
    return {
        "id": post_id,
        "channel_id": ROOM,
        "user_id": "finance-requester",
        "message": '/bursar intake {"case_id":"relay-clean","vendor_name":"Acme","invoice_number":"INV-RELAY-1","total":"10.00","currency":"USD"}',
    }


def test_clean_invoice_relay_routes_intake_approve_and_ledger():
    posts = [intake_post()]
    sent: list[dict] = []
    relay = make_relay(posts, sent)

    initial = relay.poll_once()
    assert initial and initial.case.case_id == "relay-clean"
    assert initial.case.status.value == "pending_review"
    assert initial.ledger_entry is None
    assert any("human_decision_request" in item["message"] for item in sent)

    posts.append({"id": "human-approve", "channel_id": ROOM, "user_id": "finance-reviewer", "message": "approve relay-clean"})
    final = relay.poll_once()
    assert final and final.case.status.value == "approved"
    assert final.ledger_entry is not None
    assert any("human_decision_recorded" in item["message"] for item in sent)
    assert any("ledger_result" in item["message"] for item in sent)
    assert any(event.event_type == "human_decision" for event in final.audit_events)
    assert any(event.event_type == "ledger_created" for event in relay.boundary.coordinator.timeline_for_case("relay-clean"))


def test_relay_rejects_wrong_room_missing_actor_and_agent_posts():
    sent: list[dict] = []
    relay = make_relay([], sent)
    with pytest.raises(ValueError, match="different configured room"):
        relay.process_post({"id": "wrong", "channel_id": "other", "user_id": "human", "message": "approve relay-clean"})
    with pytest.raises(ValueError, match="missing caller identity"):
        relay.process_post({"id": "missing", "channel_id": ROOM, "user_id": "", "message": "approve relay-clean"})
    assert relay.process_post({"id": "agent", "channel_id": ROOM, "user_id": "switch-agent-user", "message": "approve relay-clean"}) is None
    typed_agent = json.dumps({"schema": "bursar.switch.message.v1", "message": {"sender_type": "agent"}})
    assert relay.process_post({"id": "agent-envelope", "channel_id": ROOM, "user_id": "other-agent", "message": typed_agent}) is None


def test_relay_rejects_reasonless_reject_and_duplicate_posts():
    sent: list[dict] = []
    relay = make_relay([intake_post()], sent)
    relay.poll_once()
    assert relay.process_post(intake_post()) is None
    with pytest.raises(ValueError, match="reject requires a reason"):
        relay.process_post({"id": "human-reject", "channel_id": ROOM, "user_id": "finance-reviewer", "message": "reject relay-clean"})


def test_mattermost_relay_config_does_not_require_agent_or_team_credentials(monkeypatch):
    monkeypatch.setenv("SWITCH_BASE_URL", "http://mattermost.local")
    monkeypatch.setenv("SWITCH_TOKEN", "mattermost-token")
    monkeypatch.setenv("SWITCH_CHANNEL_ID", ROOM)
    monkeypatch.delenv("SWITCH_TEAM_ID", raising=False)
    monkeypatch.delenv("SWITCH_AGENT_BASE_URL", raising=False)
    monkeypatch.delenv("SWITCH_AGENT_ID", raising=False)
    monkeypatch.delenv("SWITCH_AGENT_API_KEY", raising=False)

    configuration = MattermostRelayConfiguration.from_env()

    assert configuration.channel_id == ROOM
    assert not hasattr(configuration, "team_id")


def test_switch_agent_configuration_remains_separate_and_requires_agent_credentials(monkeypatch):
    for name in ("SWITCH_AGENT_BASE_URL", "SWITCH_AGENT_ID", "SWITCH_AGENT_API_KEY", "SWITCH_ROOM_ID"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(ValueError, match="missing Switch agent configuration"):
        SwitchAgentConfiguration.from_env()


def test_missing_mattermost_relay_configuration_names_only_required_variables(monkeypatch):
    for name in ("SWITCH_BASE_URL", "SWITCH_TOKEN", "SWITCH_CHANNEL_ID", "SWITCH_TEAM_ID"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(ValueError, match="missing Mattermost relay configuration: SWITCH_BASE_URL, SWITCH_TOKEN, SWITCH_CHANNEL_ID"):
        MattermostRelayConfiguration.from_env()


def test_project_env_loader_reads_ignored_env_without_overriding_process(monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "SWITCH_BASE_URL=http://from-env-file\nSWITCH_TOKEN='file-token'\nSWITCH_CHANNEL_ID=channel-from-file\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("SWITCH_BASE_URL", raising=False)
    monkeypatch.delenv("SWITCH_TOKEN", raising=False)
    monkeypatch.setenv("SWITCH_CHANNEL_ID", "process-channel")

    assert load_env_file(env_file) is True
    assert os.environ["SWITCH_BASE_URL"] == "http://from-env-file"
    assert os.environ["SWITCH_TOKEN"] == "file-token"
    assert os.environ["SWITCH_CHANNEL_ID"] == "process-channel"
