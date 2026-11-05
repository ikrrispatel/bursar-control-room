import json

import httpx
import pytest

from app.switch_adapter import (
    CaseCorrelation,
    MattermostRelayConfiguration,
    MattermostSwitchAdapter,
    MessageType,
    SwitchConfiguration,
    SwitchMalformedResponseError,
    SwitchProviderError,
    SwitchTransportError,
    SwitchUnauthorizedError,
    SwitchMessage,
)
from app.switch_adapter.config import SwitchConfiguration


def configuration() -> SwitchConfiguration:
    return SwitchConfiguration(
        base_url="https://mattermost.test/",
        token="secret-token",
        team_id="team-1",
        channel_id="channel-1",
        timeout_seconds=0.5,
    )


def test_configuration_reads_environment_without_exposing_token(monkeypatch):
    monkeypatch.setenv("SWITCH_BASE_URL", "https://mattermost.test/")
    monkeypatch.setenv("SWITCH_TOKEN", "secret-token")
    monkeypatch.setenv("SWITCH_TEAM_ID", "team-1")
    monkeypatch.setenv("SWITCH_CHANNEL_ID", "channel-1")
    monkeypatch.setenv("SWITCH_TIMEOUT_SECONDS", "3")

    settings = SwitchConfiguration.from_env()

    assert settings.base_url == "https://mattermost.test"
    assert settings.timeout_seconds == 3
    assert "secret-token" not in repr(settings)


def message(case_id: str = "case-1") -> SwitchMessage:
    return SwitchMessage(
        room_id="channel-1",
        case=CaseCorrelation(case_id=case_id),
        message_type=MessageType.HUMAN_DECISION_REQUEST,
        sender_type="system",
        sender_id="bursar-coordinator",
        payload={"case_id": case_id, "allowed_actions": ["approve"]},
    )


def test_resolves_room_posts_typed_message_and_lists_case_messages():
    posted: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path == "/api/v4/channels/channel-1":
            return httpx.Response(200, json={"id": "channel-1", "team_id": "team-1", "display_name": "Bursar", "purpose": "AP"})
        if request.method == "POST" and request.url.path == "/api/v4/posts":
            body = json.loads(request.content)
            posted["body"] = body
            return httpx.Response(201, json={"id": "post-1", "channel_id": "channel-1", "message": body["message"]})
        if request.method == "GET" and request.url.path == "/api/v4/channels/channel-1/posts":
            return httpx.Response(200, json={"order": ["post-1"], "posts": {"post-1": {"id": "post-1", "channel_id": "channel-1", "message": posted["body"]["message"]}}})
        return httpx.Response(404)

    adapter = MattermostSwitchAdapter(configuration(), httpx.Client(transport=httpx.MockTransport(handler)))
    room = adapter.create_room("bursar-control-room")
    returned = adapter.post_message(message())

    assert room.room_id == "channel-1"
    assert returned.message_id == "post-1"
    assert [item.message_id for item in adapter.list_case_messages("channel-1", "case-1")] == ["post-1"]


def test_creates_room_when_channel_id_is_not_configured():
    requests: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append({"method": request.method, "path": request.url.path, "body": json.loads(request.content)})
        return httpx.Response(201, json={"id": "channel-created", "team_id": "team-1", "display_name": "Bursar Control Room", "purpose": "Invoice review"})

    settings = configuration().model_copy(update={"channel_id": None})
    adapter = MattermostSwitchAdapter(settings, httpx.Client(transport=httpx.MockTransport(handler)))
    room = adapter.create_room("Bursar Control Room", "Invoice review")

    assert room.room_id == "channel-created"
    assert requests[0]["path"] == "/api/v4/channels"
    assert requests[0]["body"]["team_id"] == "team-1"


def relay_name_configuration() -> MattermostRelayConfiguration:
    return MattermostRelayConfiguration(
        base_url="https://mattermost.test",
        token="secret-token",
        channel_name="Bursar Control Room",
        team_id="team-1",
    )


def relay_team_name_configuration() -> MattermostRelayConfiguration:
    return MattermostRelayConfiguration(
        base_url="https://mattermost.test",
        token="secret-token",
        channel_name="Bursar Control Room",
        team_name="Switch",
    )


def test_resolves_configured_channel_by_name_with_team_scope():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/api/v4/teams/team-1/channels"
        return httpx.Response(
            200,
            json=[{"id": "channel-name", "team_id": "team-1", "display_name": "Bursar Control Room", "name": "bursar-control-room"}],
        )

    adapter = MattermostSwitchAdapter(relay_name_configuration(), httpx.Client(transport=httpx.MockTransport(handler)))
    room = adapter.create_room("ignored")

    assert room.room_id == "channel-name"
    assert room.team_id == "team-1"


def test_resolves_team_and_channel_by_name_with_authenticated_scope():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v4/teams":
            return httpx.Response(200, json=[{"id": "team-1", "display_name": "Switch", "name": "switch"}])
        assert request.url.path == "/api/v4/teams/team-1/channels"
        return httpx.Response(
            200,
            json=[{"id": "channel-name", "team_id": "team-1", "display_name": "Bursar Control Room", "name": "bursar-control-room"}],
        )

    adapter = MattermostSwitchAdapter(relay_team_name_configuration(), httpx.Client(transport=httpx.MockTransport(handler)))
    room = adapter.create_room("ignored")

    assert room.room_id == "channel-name"
    assert room.team_id == "team-1"


def test_team_name_resolution_rejects_missing_team():
    adapter = MattermostSwitchAdapter(
        relay_team_name_configuration(),
        httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=[]))),
    )
    with pytest.raises(SwitchProviderError, match="no Mattermost team matched SWITCH_TEAM_NAME"):
        adapter.create_room("ignored")


def test_team_name_resolution_rejects_ambiguous_team():
    response = [
        {"id": "team-a", "display_name": "Switch"},
        {"id": "team-b", "display_name": "Switch"},
    ]
    adapter = MattermostSwitchAdapter(
        relay_team_name_configuration(),
        httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=response))),
    )
    with pytest.raises(SwitchProviderError, match="multiple Mattermost teams"):
        adapter.create_room("ignored")


def test_team_name_lookup_failure_does_not_expose_token():
    adapter = MattermostSwitchAdapter(
        relay_team_name_configuration(),
        httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(401, json={"message": "secret-token"})
            )
        ),
    )
    with pytest.raises(SwitchUnauthorizedError) as error:
        adapter.create_room("ignored")
    assert "secret-token" not in str(error.value)


def test_password_fallback_logs_in_once_and_uses_session_token():
    configuration = MattermostRelayConfiguration(
        base_url="https://mattermost.test",
        username="user",
        password="local-password",
        channel_id="channel-1",
    )
    calls: list[tuple[str, str, dict]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path, json.loads(request.content) if request.content else {}))
        if request.url.path == "/api/v4/users/login":
            assert request.headers.get("authorization") is None
            return httpx.Response(200, headers={"Token": "session-token"}, json={"id": "user-id"})
        assert request.headers.get("authorization") == "Bearer session-token"
        return httpx.Response(200, json={"id": "channel-1", "team_id": "team-1", "display_name": "Bursar"})

    adapter = MattermostSwitchAdapter(configuration, httpx.Client(transport=httpx.MockTransport(handler)))
    adapter.create_room("ignored")
    adapter.create_room("ignored")

    assert calls[0] == ("POST", "/api/v4/users/login", {"login_id": "user", "password": "local-password"})
    assert sum(path == "/api/v4/users/login" for _, path, _ in calls) == 1


def test_name_resolution_rejects_missing_channel():
    adapter = MattermostSwitchAdapter(
        relay_name_configuration(),
        httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=[]))),
    )
    with pytest.raises(SwitchProviderError, match="no Mattermost channel matched SWITCH_CHANNEL_NAME"):
        adapter.create_room("ignored")


def test_name_resolution_rejects_ambiguous_channel():
    response = [
        {"id": "channel-a", "team_id": "team-1", "display_name": "Bursar Control Room"},
        {"id": "channel-b", "team_id": "team-1", "display_name": "Bursar Control Room"},
    ]
    adapter = MattermostSwitchAdapter(
        relay_name_configuration(),
        httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=response))),
    )
    with pytest.raises(SwitchProviderError, match="multiple Mattermost channels"):
        adapter.create_room("ignored")


def test_name_resolution_rejects_channel_from_wrong_team():
    response = [{"id": "channel-other", "team_id": "team-2", "display_name": "Bursar Control Room"}]
    adapter = MattermostSwitchAdapter(
        relay_name_configuration(),
        httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=response))),
    )
    with pytest.raises(SwitchProviderError, match="different team"):
        adapter.create_room("ignored")


def test_rejects_different_room_and_agent_command():
    adapter = MattermostSwitchAdapter(configuration(), httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"id": "channel-1", "team_id": "team-1", "display_name": "Bursar"}))))
    adapter.create_room("bursar")
    with pytest.raises(ValueError, match="different configured room"):
        adapter.post_message(message().model_copy(update={"room_id": "other-channel"}))
    with pytest.raises(PermissionError, match="agent"):
        adapter.parse_human_command("approve case-1", "agent-1", "agent")
    assert adapter.parse_human_command("/approve case-1", "finance-1").action == "approve"


def test_timeout_is_bounded_and_safe():
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("timed out", request=request)

    adapter = MattermostSwitchAdapter(configuration(), httpx.Client(transport=httpx.MockTransport(handler)), max_retries=2)
    with pytest.raises(SwitchTransportError, match="timed out"):
        adapter.create_room("bursar")
    assert calls == 3


def test_unauthorized_response_is_not_retried():
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(401, json={"message": "secret details"})

    adapter = MattermostSwitchAdapter(configuration(), httpx.Client(transport=httpx.MockTransport(handler)), max_retries=2)
    with pytest.raises(SwitchUnauthorizedError, match="authorization"):
        adapter.create_room("bursar")
    assert calls == 1


def test_provider_error_retries_then_fails():
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(503, json={"message": "provider details"})

    adapter = MattermostSwitchAdapter(configuration(), httpx.Client(transport=httpx.MockTransport(handler)), max_retries=2)
    with pytest.raises(SwitchProviderError, match="HTTP 503"):
        adapter.create_room("bursar")
    assert calls == 3


def test_malformed_provider_response_is_rejected():
    adapter = MattermostSwitchAdapter(configuration(), httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"id": "channel-1"}))))
    with pytest.raises(SwitchMalformedResponseError, match="display_name"):
        adapter.create_room("bursar")


def test_malformed_posts_response_is_rejected():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/posts"):
            return httpx.Response(200, json={"posts": {}})
        return httpx.Response(200, json={"id": "channel-1", "team_id": "team-1", "display_name": "Bursar"})

    adapter = MattermostSwitchAdapter(configuration(), httpx.Client(transport=httpx.MockTransport(handler)))
    adapter.create_room("bursar")
    with pytest.raises(SwitchMalformedResponseError, match="posts/order"):
        adapter.list_case_messages("channel-1", "case-1")
