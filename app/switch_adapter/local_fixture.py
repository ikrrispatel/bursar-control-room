from __future__ import annotations

import re

from app.switch_adapter.models import (
    HumanCommand,
    SenderType,
    SwitchMessage,
    SwitchRoom,
)


COMMAND_RE = re.compile(
    r"^/?(?P<action>approve|reject|request_clarification|override)"
    r"\s+(?P<case_id>[A-Za-z0-9][A-Za-z0-9._:-]*)"
    r"(?:\s+(?P<reason>.+))?$"
)


class LocalFixtureSwitchAdapter:
    """Deterministic in-memory Switch substitute for tests and local demos."""

    def __init__(self) -> None:
        self._rooms: dict[str, SwitchRoom] = {}
        self._messages: list[SwitchMessage] = []

    def create_room(self, name: str, purpose: str = "") -> SwitchRoom:
        room = SwitchRoom(name=name.strip(), purpose=purpose)
        if room.room_id in self._rooms:
            raise ValueError(f"room already exists: {room.room_id}")
        self._rooms[room.room_id] = room
        return room

    def post_message(self, message: SwitchMessage) -> SwitchMessage:
        if message.room_id not in self._rooms:
            raise ValueError(f"unknown room: {message.room_id}")
        if any(existing.message_id == message.message_id for existing in self._messages):
            raise ValueError(f"message already exists: {message.message_id}")
        self._messages.append(message)
        return message

    def list_case_messages(self, room_id: str, case_id: str) -> list[SwitchMessage]:
        if room_id not in self._rooms:
            raise ValueError(f"unknown room: {room_id}")
        return [
            message
            for message in self._messages
            if message.room_id == room_id and message.case.case_id == case_id
        ]

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
