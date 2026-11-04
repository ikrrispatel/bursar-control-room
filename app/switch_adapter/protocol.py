from __future__ import annotations

from typing import Protocol

from app.switch_adapter.models import (
    HumanCommand,
    SwitchMessage,
    SwitchRoom,
)


class SwitchAdapter(Protocol):
    def create_room(self, name: str, purpose: str = "") -> SwitchRoom:
        ...

    def post_message(self, message: SwitchMessage) -> SwitchMessage:
        ...

    def list_case_messages(self, room_id: str, case_id: str) -> list[SwitchMessage]:
        ...

    def parse_human_command(self, command: str, actor_id: str) -> HumanCommand:
        ...
