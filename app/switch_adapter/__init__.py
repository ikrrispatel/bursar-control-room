"""Switch room/message boundary with a deterministic local fixture adapter."""

from app.switch_adapter.local_fixture import LocalFixtureSwitchAdapter
from app.switch_adapter.config import SwitchConfiguration
from app.switch_adapter.http import (
    MattermostSwitchAdapter,
    SwitchMalformedResponseError,
    SwitchProviderError,
    SwitchTransportError,
    SwitchUnauthorizedError,
)
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
    "MattermostSwitchAdapter",
    "SwitchConfiguration",
    "SwitchTransportError",
    "SwitchUnauthorizedError",
    "SwitchProviderError",
    "SwitchMalformedResponseError",
    "MessageType",
    "SwitchAdapter",
    "SwitchMessage",
    "SwitchRoom",
]
