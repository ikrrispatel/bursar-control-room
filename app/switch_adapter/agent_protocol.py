from __future__ import annotations

import json
import logging
import threading
import uuid
from collections.abc import Iterator
from typing import Any

import httpx

from app.switch_adapter.agent_config import SwitchAgentConfiguration
from app.switch_adapter.local_fixture import COMMAND_RE
from app.switch_adapter.models import HumanCommand, MessageType, SenderType, SwitchMessage, SwitchRoom


LOGGER = logging.getLogger(__name__)


class SwitchAgentTransportError(RuntimeError):
    pass


class SwitchAgentProtocolAdapter:
    """Switch agent-protocol transport; Mattermost remains behind Switch."""

    def __init__(self, configuration: SwitchAgentConfiguration, client: httpx.Client | None = None) -> None:
        self.configuration = configuration
        self._client = client or httpx.Client(timeout=configuration.timeout_seconds)
        self._owns_client = client is None
        self._messages: list[SwitchMessage] = []

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def create_room(self, name: str, purpose: str = "") -> SwitchRoom:
        raise NotImplementedError("Switch rooms are created and configured through Switch Console")

    def post_message(self, message: SwitchMessage) -> SwitchMessage:
        if message.room_id != self.configuration.room_id:
            raise ValueError("message targets a different configured Switch room")
        body = {
            "room_id": message.room_id,
            "content": self.render_message(message),
        }
        response = self._request("POST", f"/agents/{self.configuration.agent_id}/message", json=body)
        event_id = response.get("event_id") or response.get("message_id") or message.message_id
        posted = message.model_copy(update={"message_id": str(event_id)})
        self._messages.append(posted)
        return posted

    def list_case_messages(self, room_id: str, case_id: str) -> list[SwitchMessage]:
        if room_id != self.configuration.room_id:
            raise ValueError("message targets a different configured Switch room")
        return [message for message in self._messages if message.case.case_id == case_id]

    def parse_human_command(self, command: str, actor_id: str, actor_type: str = "human") -> HumanCommand:
        if actor_type != SenderType.HUMAN:
            raise PermissionError("agent commands cannot create human decisions")
        if not actor_id.strip():
            raise ValueError("human command requires an actor identity")
        match = COMMAND_RE.fullmatch(command.strip())
        if match is None:
            raise ValueError("unsupported or malformed human command")
        return HumanCommand(action=match.group("action"), case_id=match.group("case_id"), actor_id=actor_id, reason=match.group("reason"))

    def stream_events(self, *, connection_id: str | None = None, start_from: str = "head") -> Iterator[dict[str, Any]]:
        connection_id = connection_id or self.configuration.connection_id or str(uuid.uuid4())
        cursor = start_from
        cursor_lock = threading.Lock()
        stop_heartbeat = threading.Event()

        heartbeat = threading.Thread(
            target=self._heartbeat_loop,
            args=(connection_id, cursor_lock, lambda: cursor, stop_heartbeat),
            name="switch-agent-heartbeat",
            daemon=True,
        )
        params = {
            "connection_id": connection_id,
            "scope": "all",
            "filter": "all",
            "start_from": start_from,
            "rooms": self.configuration.room_id,
        }
        headers = {"Accept": "text/event-stream"}
        headers["Authorization"] = f"Bearer {self.configuration.api_key.get_secret_value()}"
        try:
            heartbeat.start()
            with self._client.stream("GET", f"{self.configuration.base_url.rstrip('/')}/agents/{self.configuration.agent_id}/events", params=params, headers=headers, timeout=None) as response:
                if response.status_code >= 400:
                    if response.status_code == 410:
                        raise SwitchAgentTransportError(
                            "external client connection to the Console-managed agent is unavailable; Switch Console owns the managed watcher and connection"
                        )
                    raise SwitchAgentTransportError(f"Switch event stream returned HTTP {response.status_code}")
                frame: dict[str, str] = {}
                for line in response.iter_lines():
                    if not line:
                        if frame.get("data"):
                            try:
                                event = json.loads(frame["data"])
                            except json.JSONDecodeError as exc:
                                raise SwitchAgentTransportError("Switch event stream returned invalid JSON") from exc
                            if isinstance(event, dict):
                                sequence = event.get("sequence") or event.get("id")
                                if sequence is not None:
                                    with cursor_lock:
                                        cursor = str(sequence)
                                yield event
                        frame = {}
                        continue
                    text = line.decode() if isinstance(line, bytes) else line
                    key, separator, value = text.partition(":")
                    if separator and key in {"event", "data", "id"}:
                        frame[key] = value.lstrip()
        except httpx.TimeoutException as exc:
            raise SwitchAgentTransportError("Switch event stream timed out") from exc
        except httpx.RequestError as exc:
            raise SwitchAgentTransportError("Switch event stream failed") from exc
        finally:
            stop_heartbeat.set()
            heartbeat.join(timeout=1.0)

    def _heartbeat_loop(
        self,
        connection_id: str,
        cursor_lock: threading.Lock,
        cursor_getter: Any,
        stop_event: threading.Event,
    ) -> None:
        """Keep the documented six-second Switch connection lease alive."""
        while not stop_event.wait(2.0):
            with cursor_lock:
                cursor = cursor_getter()
            try:
                self._request(
                    "POST",
                    f"/agents/{self.configuration.agent_id}/connection/beat",
                    json={"connection_id": connection_id, "cursor": cursor},
                )
            except SwitchAgentTransportError:
                LOGGER.warning("Switch agent heartbeat failed; event stream may expire")

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        headers = kwargs.pop("headers", {})
        headers["Authorization"] = f"Bearer {self.configuration.api_key.get_secret_value()}"
        try:
            response = self._client.request(method, f"{self.configuration.base_url.rstrip('/')}{path}", headers=headers, timeout=self.configuration.timeout_seconds, **kwargs)
        except httpx.TimeoutException as exc:
            raise SwitchAgentTransportError("Switch agent request timed out") from exc
        except httpx.RequestError as exc:
            raise SwitchAgentTransportError("Switch agent request failed") from exc
        if response.status_code >= 400:
            raise SwitchAgentTransportError(f"Switch agent request returned HTTP {response.status_code}")
        try:
            result = response.json()
        except ValueError as exc:
            raise SwitchAgentTransportError("Switch agent returned invalid JSON") from exc
        if not isinstance(result, dict):
            raise SwitchAgentTransportError("Switch agent returned an unexpected response")
        return result

    @staticmethod
    def render_message(message: SwitchMessage) -> str:
        role = f" role={message.agent_role.value}" if message.agent_role else ""
        payload = json.dumps(message.payload, sort_keys=True, default=str)
        return f"[BURSAR][agent={message.sender_id}][case={message.case.case_id}][type={message.message_type.value}{role}]\n{payload}"
