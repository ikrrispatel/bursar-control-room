from __future__ import annotations

import json
import logging
import re
from collections.abc import Mapping
from typing import Any

import httpx

from app.switch_adapter.local_fixture import COMMAND_RE
from app.switch_adapter.models import (
    HumanCommand,
    MessageType,
    SenderType,
    SwitchMessage,
    SwitchRoom,
)
from app.switch_adapter.config import MattermostRelayConfiguration, SwitchConfiguration


LOGGER = logging.getLogger(__name__)
ENVELOPE_SCHEMA = "bursar.switch.message.v1"
RETRYABLE_STATUS_CODES = {408, 429, 500, 502, 503, 504}


class SwitchTransportError(RuntimeError):
    """Safe provider-facing error without response bodies or credentials."""


class SwitchUnauthorizedError(SwitchTransportError):
    pass


class SwitchProviderError(SwitchTransportError):
    pass


class SwitchMalformedResponseError(SwitchTransportError):
    pass


class MattermostSwitchAdapter:
    """HTTP transport for the documented Mattermost REST v4 endpoints."""

    def __init__(
        self,
        configuration: SwitchConfiguration | MattermostRelayConfiguration | None = None,
        client: httpx.Client | None = None,
        max_retries: int = 2,
    ) -> None:
        self.configuration = configuration or SwitchConfiguration.from_env()
        if max_retries < 0:
            raise ValueError("max_retries must be non-negative")
        self.max_retries = max_retries
        self._client = client or httpx.Client(timeout=self.configuration.timeout_seconds)
        self._owns_client = client is None
        self._resolved_room: SwitchRoom | None = None
        self._session_token: str | None = None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def create_room(self, name: str, purpose: str = "") -> SwitchRoom:
        team_id = getattr(self.configuration, "team_id", None)
        if self.configuration.channel_id:
            room = self._get_room(self.configuration.channel_id)
        elif getattr(self.configuration, "channel_name", None):
            if not team_id:
                raise ValueError("SWITCH_TEAM_ID is required when SWITCH_CHANNEL_NAME is used")
            room = self._resolve_room_by_name(self.configuration.channel_name, team_id)
        else:
            if not team_id:
                raise ValueError("SWITCH_TEAM_ID is required when creating a Mattermost room")
            channel_name = self._channel_name(name)
            payload = {
                "team_id": team_id,
                "name": channel_name,
                "display_name": name.strip(),
                "purpose": purpose,
                "type": "O",
            }
            response = self._request("POST", "/api/v4/channels", json=payload)
            room = self._room_from_provider(response)
        if room.room_id != self.configuration.channel_id and self.configuration.channel_id:
            raise SwitchProviderError("provider returned a different configured channel")
        if team_id and room.team_id != team_id:
            raise SwitchProviderError("configured channel belongs to a different team")
        self._resolved_room = room
        return room

    def post_message(self, message: SwitchMessage) -> SwitchMessage:
        self._assert_room(message.room_id)
        envelope = self._encode_message(message)
        response = self._request(
            "POST",
            "/api/v4/posts",
            json={"channel_id": message.room_id, "message": envelope},
        )
        provider_id = self._required_string(response, "id")
        provider_channel = self._required_string(response, "channel_id")
        if provider_channel != message.room_id:
            raise SwitchMalformedResponseError("provider returned a different channel")
        return message.model_copy(update={"message_id": provider_id})

    def list_case_messages(self, room_id: str, case_id: str) -> list[SwitchMessage]:
        self._assert_room(room_id)
        posts = self.list_room_posts(room_id)
        messages: list[SwitchMessage] = []
        for post in posts:
            if self._required_string(post, "channel_id") != room_id:
                raise SwitchMalformedResponseError("provider returned a post for another channel")
            text = post.get("message")
            if not isinstance(text, str) or not text.startswith("{"):
                continue
            try:
                envelope = json.loads(text)
            except json.JSONDecodeError as exc:
                raise SwitchMalformedResponseError("provider returned invalid message JSON") from exc
            if not isinstance(envelope, dict) or envelope.get("schema") != ENVELOPE_SCHEMA:
                continue
            message = self._decode_message(envelope, self._required_string(post, "id"))
            if message.room_id == room_id and message.case.case_id == case_id:
                messages.append(message)
        return messages

    def list_room_posts(self, room_id: str) -> list[dict[str, Any]]:
        """Return raw posts for the configured relay room.

        Parsing and authorization stay in the Bursar relay; the adapter only
        validates the provider response and configured room identity.
        """
        self._assert_room(room_id)
        response = self._request(
            "GET",
            f"/api/v4/channels/{room_id}/posts",
            params={"per_page": 200},
        )
        return self._posts_from_provider(response)

    def parse_human_command(self, command: str, actor_id: str, actor_type: str = "human") -> HumanCommand:
        if actor_type != SenderType.HUMAN:
            raise PermissionError("agent commands cannot create human decisions")
        if not actor_id.strip():
            raise ValueError("human command requires an actor identity")
        match = COMMAND_RE.fullmatch(command.strip())
        if match is None:
            raise ValueError("unsupported or malformed human command")
        return HumanCommand(
            action=match.group("action"),
            case_id=match.group("case_id"),
            actor_id=actor_id,
            reason=match.group("reason"),
        )

    def _assert_room(self, room_id: str) -> None:
        configured = self.configuration.channel_id
        resolved = self._resolved_room.room_id if self._resolved_room else None
        if configured and room_id != configured:
            raise ValueError("message targets a different configured room")
        if resolved and room_id != resolved:
            raise ValueError("message targets a different resolved room")
        if not configured and not resolved:
            raise ValueError("create_room must resolve the Bursar room first")

    def _get_room(self, room_id: str) -> SwitchRoom:
        response = self._request("GET", f"/api/v4/channels/{room_id}")
        return self._room_from_provider(response)

    def _resolve_room_by_name(self, channel_name: str, team_id: str) -> SwitchRoom:
        response = self._request("GET", f"/api/v4/teams/{team_id}/channels", params={"per_page": 200})
        if not isinstance(response, list):
            raise SwitchMalformedResponseError("provider channel lookup returned an unexpected JSON shape")
        normalized = channel_name.strip().casefold()
        matches = [
            item
            for item in response
            if isinstance(item, dict)
            and any(
                isinstance(item.get(key), str) and item[key].strip().casefold() == normalized
                for key in ("display_name", "name")
            )
        ]
        if not matches:
            raise SwitchProviderError("no Mattermost channel matched SWITCH_CHANNEL_NAME")
        if len(matches) > 1:
            raise SwitchProviderError("SWITCH_CHANNEL_NAME resolved to multiple Mattermost channels")
        return self._room_from_provider(matches[0])

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any] | list[Any]:
        headers = {"Authorization": f"Bearer {self._get_auth_token()}"}
        for attempt in range(self.max_retries + 1):
            try:
                response = self._client.request(
                    method,
                    f"{self.configuration.base_url}{path}",
                    headers=headers,
                    timeout=self.configuration.timeout_seconds,
                    **kwargs,
                )
            except httpx.TimeoutException as exc:
                if attempt < self.max_retries:
                    LOGGER.warning("switch request timeout; retry=%s method=%s path=%s", attempt + 1, method, path)
                    continue
                raise SwitchTransportError("Switch request timed out after bounded retries") from exc
            except httpx.RequestError as exc:
                if attempt < self.max_retries:
                    LOGGER.warning("switch request failed; retry=%s method=%s path=%s", attempt + 1, method, path)
                    continue
                raise SwitchTransportError("Switch request failed after bounded retries") from exc
            if response.status_code in RETRYABLE_STATUS_CODES and attempt < self.max_retries:
                LOGGER.warning("switch provider retryable response; retry=%s status=%s path=%s", attempt + 1, response.status_code, path)
                continue
            if response.status_code in {401, 403}:
                raise SwitchUnauthorizedError("Switch authorization failed")
            if response.status_code >= 400:
                raise SwitchProviderError(f"Switch provider returned HTTP {response.status_code}")
            try:
                body = response.json()
            except ValueError as exc:
                raise SwitchMalformedResponseError("Switch provider returned non-JSON data") from exc
            if not isinstance(body, (dict, list)):
                raise SwitchMalformedResponseError("Switch provider returned an unexpected JSON shape")
            return body
        raise SwitchTransportError("Switch request exhausted retries")

    def _get_auth_token(self) -> str:
        token = getattr(self.configuration, "token", None)
        if token is not None:
            return token.get_secret_value()
        if self._session_token is None:
            self._login_with_password()
        if self._session_token is None:
            raise SwitchTransportError("Mattermost login did not establish a session")
        return self._session_token

    def _login_with_password(self) -> None:
        username = getattr(self.configuration, "username", None)
        password = getattr(self.configuration, "password", None)
        if username is None or password is None:
            raise SwitchUnauthorizedError("Mattermost relay credentials are unavailable")
        for attempt in range(self.max_retries + 1):
            try:
                response = self._client.request(
                    "POST",
                    f"{self.configuration.base_url}/api/v4/users/login",
                    json={"login_id": username.get_secret_value(), "password": password.get_secret_value()},
                    timeout=self.configuration.timeout_seconds,
                )
            except httpx.TimeoutException as exc:
                if attempt < self.max_retries:
                    LOGGER.warning("Mattermost login timeout; retry=%s", attempt + 1)
                    continue
                raise SwitchTransportError("Mattermost login timed out after bounded retries") from exc
            except httpx.RequestError as exc:
                if attempt < self.max_retries:
                    LOGGER.warning("Mattermost login failed; retry=%s", attempt + 1)
                    continue
                raise SwitchTransportError("Mattermost login failed after bounded retries") from exc
            if response.status_code in RETRYABLE_STATUS_CODES and attempt < self.max_retries:
                LOGGER.warning("Mattermost login retryable response; retry=%s status=%s", attempt + 1, response.status_code)
                continue
            if response.status_code in {401, 403}:
                raise SwitchUnauthorizedError("Mattermost login authorization failed")
            if response.status_code >= 400:
                raise SwitchProviderError(f"Mattermost login returned HTTP {response.status_code}")
            session_token = response.headers.get("Token")
            if not session_token:
                raise SwitchMalformedResponseError("Mattermost login response did not include a session token")
            self._session_token = session_token
            return
        raise SwitchTransportError("Mattermost login exhausted retries")

    @staticmethod
    def _encode_message(message: SwitchMessage) -> str:
        return json.dumps({"schema": ENVELOPE_SCHEMA, "message": message.model_dump(mode="json")}, separators=(",", ":"), sort_keys=True)

    @staticmethod
    def _decode_message(envelope: dict[str, Any], provider_id: str) -> SwitchMessage:
        payload = envelope.get("message")
        if not isinstance(payload, dict):
            raise SwitchMalformedResponseError("provider message envelope is missing a typed message")
        payload["message_id"] = provider_id
        try:
            return SwitchMessage.model_validate(payload)
        except ValueError as exc:
            raise SwitchMalformedResponseError("provider message failed typed validation") from exc

    @staticmethod
    def _posts_from_provider(response: dict[str, Any]) -> list[dict[str, Any]]:
        posts = response.get("posts")
        order = response.get("order")
        if not isinstance(posts, dict) or not isinstance(order, list):
            raise SwitchMalformedResponseError("provider posts response is missing posts/order")
        result: list[dict[str, Any]] = []
        for post_id in order:
            if not isinstance(post_id, str) or not isinstance(posts.get(post_id), dict):
                raise SwitchMalformedResponseError("provider posts response contains an invalid post")
            result.append(posts[post_id])
        return result

    @staticmethod
    def _required_string(data: Mapping[str, Any], key: str) -> str:
        value = data.get(key)
        if not isinstance(value, str) or not value:
            raise SwitchMalformedResponseError(f"provider response is missing {key}")
        return value

    @classmethod
    def _room_from_provider(cls, response: dict[str, Any]) -> SwitchRoom:
        room_id = cls._required_string(response, "id")
        name = cls._required_string(response, "display_name")
        team_id = cls._required_string(response, "team_id")
        return SwitchRoom(room_id=room_id, name=name, purpose=response.get("purpose") or "", team_id=team_id)

    @staticmethod
    def _channel_name(name: str) -> str:
        value = re.sub(r"[^a-z0-9-]+", "-", name.strip().lower()).strip("-")
        if not value:
            raise ValueError("room name must contain letters or numbers")
        return value[:64]
