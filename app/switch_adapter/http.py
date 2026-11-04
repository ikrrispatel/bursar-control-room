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
from app.switch_adapter.config import SwitchConfiguration


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
        configuration: SwitchConfiguration | None = None,
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

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def create_room(self, name: str, purpose: str = "") -> SwitchRoom:
        if self.configuration.channel_id:
            room = self._get_room(self.configuration.channel_id)
        else:
            channel_name = self._channel_name(name)
            payload = {
                "team_id": self.configuration.team_id,
                "name": channel_name,
                "display_name": name.strip(),
                "purpose": purpose,
                "type": "O",
            }
            response = self._request("POST", "/api/v4/channels", json=payload)
            room = self._room_from_provider(response)
        if room.room_id != self.configuration.channel_id and self.configuration.channel_id:
            raise SwitchProviderError("provider returned a different configured channel")
        if room.team_id != self.configuration.team_id:
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
        response = self._request(
            "GET",
            f"/api/v4/channels/{room_id}/posts",
            params={"per_page": 200},
        )
        posts = self._posts_from_provider(response)
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

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {self.configuration.token.get_secret_value()}"}
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
            if not isinstance(body, dict):
                raise SwitchMalformedResponseError("Switch provider returned an unexpected JSON shape")
            return body
        raise SwitchTransportError("Switch request exhausted retries")

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
