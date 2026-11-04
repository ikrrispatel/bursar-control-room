"""Switch room/message boundary with a deterministic local fixture adapter."""

from app.switch_adapter.local_fixture import LocalFixtureSwitchAdapter
from app.switch_adapter.config import MattermostRelayConfiguration, SwitchConfiguration
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
    SenderType,
    SwitchMessage,
    SwitchRoom,
)
from app.switch_adapter.protocol import SwitchAdapter
from app.switch_adapter.agent_config import SwitchAgentConfiguration
from app.switch_adapter.agent_protocol import SwitchAgentProtocolAdapter, SwitchAgentTransportError

__all__ = [
    "AgentRole",
    "CaseCorrelation",
    "LocalFixtureSwitchAdapter",
    "MattermostSwitchAdapter",
    "SwitchConfiguration",
    "MattermostRelayConfiguration",
    "SwitchTransportError",
    "SwitchUnauthorizedError",
    "SwitchProviderError",
    "SwitchMalformedResponseError",
    "MessageType",
    "SenderType",
    "SwitchAdapter",
    "SwitchMessage",
    "SwitchRoom",
    "SwitchAgentConfiguration",
    "SwitchAgentProtocolAdapter",
    "SwitchAgentTransportError",
]
