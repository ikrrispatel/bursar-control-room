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
from app.switch_adapter.http import MattermostSwitchAdapter, SwitchUnauthorizedError
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
    posts: list[dict] = []
    sent: list[dict] = []
    relay = make_relay(posts, sent)

    assert relay.poll_once() is None
    posts.append(intake_post())
    initial = relay.poll_once()
    assert initial and initial.case.case_id == "relay-clean"
    assert initial.case.status.value == "pending_review"
    assert initial.ledger_entry is None
    assert any(item["props"]["bursar_protocol"]["message"]["message_type"] == "human_decision_request" for item in sent)
    assert any("Human decision required" in item["message"] for item in sent)

    posts.append({"id": "human-approve", "channel_id": ROOM, "user_id": "finance-reviewer", "message": "approve relay-clean"})
    final = relay.poll_once()
    assert final and final.case.status.value == "approved"
    assert final.ledger_entry is not None
    assert any(item["props"]["bursar_protocol"]["message"]["message_type"] == "human_decision_recorded" for item in sent)
    assert any(item["props"]["bursar_protocol"]["message"]["message_type"] == "ledger_result" for item in sent)
    assert any(event.event_type == "human_decision" for event in final.audit_events)
    assert any(event.event_type == "ledger_created" for event in relay.boundary.coordinator.timeline_for_case("relay-clean"))


def approval_post(case_id: str = "relay-clean", post_id: str = "human-approve") -> dict:
    return {"id": post_id, "channel_id": ROOM, "user_id": "finance-reviewer", "message": f"approve {case_id}"}


def test_historical_intake_and_approval_are_not_interpreted_after_startup():
    posts = [intake_post("stale-intake"), approval_post(post_id="stale-approval")]
    sent: list[dict] = []
    relay = make_relay(posts, sent)

    assert relay.poll_once() is None
    assert sent == []


def test_fresh_approval_requires_current_session_intake():
    posts: list[dict] = []
    sent: list[dict] = []
    relay = make_relay(posts, sent)
    assert relay.poll_once() is None
    posts.append(approval_post(case_id="never-intaked", post_id="fresh-approval"))

    with pytest.raises(ValueError, match="intake observed in this relay session"):
        relay.poll_once()


def test_fresh_intake_then_approval_is_processed_once():
    posts: list[dict] = []
    sent: list[dict] = []
    relay = make_relay(posts, sent)
    assert relay.poll_once() is None
    posts.append(intake_post("fresh-intake"))
    initial = relay.poll_once()
    assert initial and initial.case.case_id == "relay-clean"
    assert relay.poll_once() is None
    posts.append(approval_post(post_id="fresh-approval"))
    final = relay.poll_once()
    assert final and final.ledger_entry is not None
    assert relay.poll_once() is None


def test_restart_does_not_accept_old_case_approval_without_new_intake():
    posts: list[dict] = []
    first_sent: list[dict] = []
    first = make_relay(posts, first_sent)
    assert first.poll_once() is None
    posts.append(intake_post("restart-intake"))
    assert first.poll_once() is not None

    second_sent: list[dict] = []
    second = make_relay(posts, second_sent)
    assert second.poll_once() is None
    posts.append(approval_post(post_id="restart-approval"))
    with pytest.raises(ValueError, match="intake observed in this relay session"):
        second.poll_once()


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


def test_relay_requires_configured_finance_reviewer_in_production_mode(monkeypatch):
    monkeypatch.setenv("BURSAR_API_AUTH_MODE", "required")
    relay = make_relay([intake_post()], [])
    relay.poll_once()
    with pytest.raises(PermissionError, match="finance reviewer authorization"):
        relay.process_post(approval_post())


def test_mattermost_relay_config_requires_team_for_channel_id(monkeypatch):
    monkeypatch.setenv("SWITCH_BASE_URL", "http://mattermost.local")
    monkeypatch.setenv("SWITCH_TOKEN", "mattermost-token")
    monkeypatch.setenv("SWITCH_CHANNEL_ID", ROOM)
    monkeypatch.setenv("SWITCH_TEAM_NAME", "Switch")
    monkeypatch.delenv("SWITCH_TEAM_ID", raising=False)
    monkeypatch.delenv("SWITCH_AGENT_BASE_URL", raising=False)
    monkeypatch.delenv("SWITCH_AGENT_ID", raising=False)
    monkeypatch.delenv("SWITCH_AGENT_API_KEY", raising=False)

    configuration = MattermostRelayConfiguration.from_env()

    assert configuration.channel_id == ROOM
    assert configuration.team_id is None
    assert configuration.team_name == "Switch"


def test_mattermost_relay_config_preserves_id_precedence_over_name(monkeypatch):
    monkeypatch.setenv("SWITCH_BASE_URL", "http://mattermost.local")
    monkeypatch.setenv("SWITCH_TOKEN", "mattermost-token")
    monkeypatch.setenv("SWITCH_CHANNEL_ID", ROOM)
    monkeypatch.setenv("SWITCH_CHANNEL_NAME", "Ignored Name")
    monkeypatch.setenv("SWITCH_TEAM_NAME", "Switch")
    monkeypatch.delenv("SWITCH_TEAM_ID", raising=False)

    configuration = MattermostRelayConfiguration.from_env()

    assert configuration.channel_id == ROOM
    assert configuration.channel_name is None


def test_mattermost_relay_config_accepts_team_name_when_team_id_is_absent(monkeypatch):
    monkeypatch.setenv("SWITCH_BASE_URL", "http://mattermost.local")
    monkeypatch.setenv("SWITCH_TOKEN", "mattermost-token")
    monkeypatch.setenv("SWITCH_TEAM_NAME", "Switch")
    monkeypatch.setenv("SWITCH_CHANNEL_NAME", "Bursar Control Room")
    monkeypatch.delenv("SWITCH_TEAM_ID", raising=False)
    monkeypatch.delenv("SWITCH_CHANNEL_ID", raising=False)

    configuration = MattermostRelayConfiguration.from_env()

    assert configuration.team_id is None
    assert configuration.team_name == "Switch"
    assert configuration.channel_name == "Bursar Control Room"


def test_mattermost_relay_config_preserves_team_id_precedence(monkeypatch):
    monkeypatch.setenv("SWITCH_BASE_URL", "http://mattermost.local")
    monkeypatch.setenv("SWITCH_TOKEN", "mattermost-token")
    monkeypatch.setenv("SWITCH_TEAM_ID", "team-1")
    monkeypatch.setenv("SWITCH_TEAM_NAME", "Ignored Team")
    monkeypatch.setenv("SWITCH_CHANNEL_NAME", "Bursar Control Room")
    monkeypatch.delenv("SWITCH_CHANNEL_ID", raising=False)

    configuration = MattermostRelayConfiguration.from_env()

    assert configuration.team_id == "team-1"
    assert configuration.team_name is None


def test_mattermost_token_auth_takes_precedence_over_password_fallback(monkeypatch):
    monkeypatch.setenv("SWITCH_BASE_URL", "http://mattermost.local")
    monkeypatch.setenv("SWITCH_TOKEN", "bearer-token")
    monkeypatch.setenv("SWITCH_USERNAME", "user")
    monkeypatch.setenv("SWITCH_PASSWORD", "local-password")
    monkeypatch.setenv("SWITCH_CHANNEL_ID", ROOM)
    monkeypatch.setenv("SWITCH_TEAM_ID", "team-1")

    configuration = MattermostRelayConfiguration.from_env()

    assert configuration.token is not None
    assert configuration.username is not None
    assert configuration.password is not None

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == f"/api/v4/channels/{ROOM}"
        assert request.headers.get("authorization") == "Bearer bearer-token"
        return httpx.Response(200, json={"id": ROOM, "team_id": "team-1", "display_name": "Bursar"})

    MattermostSwitchAdapter(configuration, httpx.Client(transport=httpx.MockTransport(handler))).create_room("ignored")


def test_switch_agent_configuration_remains_separate_and_requires_agent_credentials(monkeypatch):
    for name in ("SWITCH_AGENT_BASE_URL", "SWITCH_AGENT_ID", "SWITCH_AGENT_API_KEY", "SWITCH_ROOM_ID"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(ValueError, match="missing Switch agent configuration"):
        SwitchAgentConfiguration.from_env()


def test_missing_mattermost_relay_configuration_names_only_required_variables(monkeypatch):
    for name in ("SWITCH_BASE_URL", "SWITCH_TOKEN", "SWITCH_CHANNEL_ID", "SWITCH_CHANNEL_NAME", "SWITCH_TEAM_ID"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(ValueError, match="missing Mattermost relay configuration: SWITCH_BASE_URL"):
        MattermostRelayConfiguration.from_env()


def test_name_based_configuration_requires_team_without_exposing_token(monkeypatch):
    monkeypatch.setenv("SWITCH_BASE_URL", "http://mattermost.local")
    monkeypatch.setenv("SWITCH_TOKEN", "do-not-print-this-token")
    monkeypatch.setenv("SWITCH_CHANNEL_NAME", "Bursar Control Room")
    monkeypatch.delenv("SWITCH_CHANNEL_ID", raising=False)
    monkeypatch.delenv("SWITCH_TEAM_ID", raising=False)

    with pytest.raises(ValueError) as error:
        MattermostRelayConfiguration.from_env()
    assert "SWITCH_TEAM_ID or SWITCH_TEAM_NAME" in str(error.value)
    assert "do-not-print-this-token" not in str(error.value)


def test_missing_relay_credentials_names_only_environment_variables(monkeypatch):
    monkeypatch.setenv("SWITCH_BASE_URL", "http://mattermost.local")
    monkeypatch.setenv("SWITCH_CHANNEL_ID", ROOM)
    for name in ("SWITCH_TOKEN", "SWITCH_USERNAME", "SWITCH_PASSWORD"):
        monkeypatch.delenv(name, raising=False)

    with pytest.raises(ValueError, match="missing Mattermost relay credentials") as error:
        MattermostRelayConfiguration.from_env()
    assert "SWITCH_TOKEN" in str(error.value)
    assert "SWITCH_USERNAME" in str(error.value)
    assert "SWITCH_PASSWORD" in str(error.value)


def test_failed_password_login_redacts_credentials():
    configuration = MattermostRelayConfiguration(
        base_url="http://mattermost.local",
        username="user",
        password="super-secret-password",
        channel_id=ROOM,
        team_id="team-1",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v4/users/login"
        return httpx.Response(401, json={"message": "super-secret-password"})

    adapter = MattermostSwitchAdapter(configuration, httpx.Client(transport=httpx.MockTransport(handler)), max_retries=0)
    with pytest.raises(SwitchUnauthorizedError) as error:
        adapter.create_room("ignored")
    assert "super-secret-password" not in str(error.value)
    assert "user" not in str(error.value)


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
