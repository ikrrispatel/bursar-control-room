from __future__ import annotations

import json
import os
import re
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field

from app.bursar.checks import InvoiceIntake
from app.switch_adapter.boundary import LiveMattermostBursarBoundary, SwitchCommandRequest
from app.switch_adapter.http import MattermostSwitchAdapter
from app.switch_adapter.models import CaseCorrelation, MessageType, SenderType, SwitchMessage, utc_now

if TYPE_CHECKING:
    from app.bursar.workflow import BursarWorkflowResult


INTAKE_PREFIX = re.compile(r"^\s*/?bursar\s+intake\s+(.+?)\s*$", re.IGNORECASE | re.DOTALL)
COMMAND_PREFIX = re.compile(r"^(?:approve|reject|request_clarification|override)\s+\S+(?:\s+.+)?$", re.IGNORECASE)
AGENT_MARKER = re.compile(r"^\s*\[BURSAR\]\[agent=", re.IGNORECASE)


class MattermostRelayPost(BaseModel):
    model_config = ConfigDict(extra="forbid")

    post_id: str = Field(min_length=1)
    room_id: str = Field(min_length=1)
    actor_id: str = Field(min_length=1)
    body: str = Field(min_length=1)


class MattermostBursarRelay:
    """Console-compatible inbound relay for the configured Mattermost room.

    This is deliberately separate from the legacy Switch agent-protocol
    compatibility runtime. It is a Mattermost relay for local Switch Console
    deployments whose managed agent host returns HTTP 410 to an attempted
    external client connection.
    """

    def __init__(self, adapter: MattermostSwitchAdapter, boundary: LiveMattermostBursarBoundary) -> None:
        self.adapter = adapter
        self.boundary = boundary
        self.room_id = boundary.configured_room_id
        self._processed_post_ids: set[str] = set()
        self._observed_intake_case_ids: set[str] = set()
        self._cursor_initialized = False

    def process_post(self, raw: dict[str, Any]) -> BursarWorkflowResult | None:
        post = self._validate_post(raw)
        if post.post_id in self._processed_post_ids:
            return None
        self._processed_post_ids.add(post.post_id)
        if self.adapter.configuration.agent_user_id == post.actor_id or AGENT_MARKER.match(post.body) or self._is_typed_agent_post(post.body):
            return None

        intake_match = INTAKE_PREFIX.fullmatch(post.body)
        if intake_match:
            try:
                values = json.loads(intake_match.group(1))
                if not isinstance(values, dict):
                    raise ValueError("intake payload must be a JSON object")
                case_id = str(values.pop("case_id", "")).strip()
                if not case_id:
                    raise ValueError("intake payload requires case_id")
                if case_id in self._observed_intake_case_ids:
                    return None
                intake = InvoiceIntake.model_validate(values)
            except (json.JSONDecodeError, TypeError, ValueError) as exc:
                raise ValueError("malformed Bursar intake payload") from exc
            message = SwitchMessage(
                message_id=post.post_id,
                room_id=self.room_id,
                case=CaseCorrelation(case_id=case_id),
                message_type=MessageType.INVOICE_INTAKE,
                sender_type=SenderType.HUMAN,
                sender_id=post.actor_id,
                payload=intake.model_dump(mode="json"),
                timestamp=utc_now(),
            )
            result = self.boundary.receive_message(message)
            self._observed_intake_case_ids.add(case_id)
            return result

        if COMMAND_PREFIX.fullmatch(post.body.strip()):
            reviewer_ids = getattr(self.adapter.configuration, "finance_reviewer_ids", None)
            if reviewer_ids is None and os.getenv("BURSAR_API_AUTH_MODE", "required").strip().lower() != "local":
                raise PermissionError("finance reviewer authorization is not configured")
            if reviewer_ids is not None and post.actor_id not in reviewer_ids:
                raise PermissionError("finance reviewer authorization is required")
            command = self.adapter.parse_human_command(post.body.strip(), post.actor_id)
            if command.case_id not in self._observed_intake_case_ids:
                raise ValueError("human decision requires an intake observed in this relay session")
            return self.boundary.receive_command(
                SwitchCommandRequest(room_id=self.room_id, command=post.body.strip(), actor_id=post.actor_id)
            )
        return None

    @staticmethod
    def _is_typed_agent_post(body: str) -> bool:
        if not body.lstrip().startswith("{"):
            return False
        try:
            envelope = json.loads(body)
        except json.JSONDecodeError:
            return False
        message = envelope.get("message") if isinstance(envelope, dict) else None
        return isinstance(envelope, dict) and envelope.get("schema") == "bursar.switch.message.v1" and isinstance(message, dict) and message.get("sender_type") == SenderType.AGENT.value

    def poll_once(self) -> BursarWorkflowResult | None:
        posts = self.adapter.list_room_posts(self.room_id)
        if not self._cursor_initialized:
            self._processed_post_ids.update(self._post_id(post) for post in posts if self._post_id(post))
            self._cursor_initialized = True
            return None
        new_posts = [post for post in posts if self._post_id(post) not in self._processed_post_ids]
        for raw in self._chronological(new_posts):
            result = self.process_post(raw)
            if result is not None:
                return result
        return None

    @staticmethod
    def _post_id(raw: dict[str, Any]) -> str | None:
        value = raw.get("id") if isinstance(raw, dict) else None
        return value if isinstance(value, str) and value else None

    @classmethod
    def _chronological(cls, posts: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Order provider posts oldest-first when Mattermost timestamps exist.

        Fixture transports often omit ``create_at``; their returned order is
        retained so deterministic tests and offline providers remain stable.
        """
        return [
            post
            for _, post in sorted(
                enumerate(posts),
                key=lambda item: (
                    0 if isinstance(item[1].get("create_at"), (int, float)) else 1,
                    item[1].get("create_at") if isinstance(item[1].get("create_at"), (int, float)) else item[0],
                    item[0],
                ),
            )
        ]

    def _validate_post(self, raw: dict[str, Any]) -> MattermostRelayPost:
        if not isinstance(raw, dict):
            raise ValueError("Mattermost post must be an object")
        room_id = raw.get("channel_id")
        if room_id != self.room_id:
            raise ValueError("Mattermost post targets a different configured room")
        post_id = raw.get("id")
        actor_id = raw.get("user_id")
        body = raw.get("message")
        if not all(isinstance(value, str) and value.strip() for value in (post_id, actor_id, body)):
            raise ValueError("Mattermost post is missing caller identity or message body")
        return MattermostRelayPost(post_id=post_id, room_id=room_id, actor_id=actor_id, body=body)
