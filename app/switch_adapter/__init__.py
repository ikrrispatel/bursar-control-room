"""Switch room/message boundary with a deterministic local fixture adapter."""

from app.switch_adapter.local_fixture import LocalFixtureSwitchAdapter
from app.switch_adapter.models import (
    AgentRole,
    CaseCorrelation,
    MessageType,
    SwitchMessage,
    SwitchRoom,
)
from app.switch_adapter.protocol import SwitchAdapter

__all__ = [
    "AgentRole",
    "CaseCorrelation",
    "LocalFixtureSwitchAdapter",
    "MessageType",
    "SwitchAdapter",
    "SwitchMessage",
    "SwitchRoom",
]
