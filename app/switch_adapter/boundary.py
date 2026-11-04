from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.agents import AgentProvider, ModelAgentProvider, ModelConfiguration
from app.bursar.checks import InvoiceIntake
from app.bursar.workflow import BursarWorkflowResult, LocalBursarWorkflowCoordinator
from app.switch_adapter.config import SwitchConfiguration
from app.switch_adapter.http import MattermostSwitchAdapter
from app.switch_adapter.models import MessageType, SenderType, SwitchMessage
from app.switch_adapter.protocol import SwitchAdapter


class SwitchCommandRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    room_id: str = Field(min_length=1)
    command: str = Field(min_length=1)
    actor_id: str = Field(min_length=1)
    actor_type: Literal["human"] = "human"


class LiveMattermostBursarBoundary:
    """Validates live room input before handing it to the deterministic coordinator."""

    def __init__(self, adapter: SwitchAdapter, configured_room_id: str, coordinator: LocalBursarWorkflowCoordinator | None = None, agent_provider: AgentProvider | None = None) -> None:
        if not configured_room_id.strip():
            raise ValueError("a configured Bursar room is required")
        self.adapter = adapter
        self.configured_room_id = configured_room_id
        self.coordinator = coordinator or LocalBursarWorkflowCoordinator(adapter, agent_provider=agent_provider)
        self.agent_provider = agent_provider or self.coordinator.agent_provider

    @classmethod
    def from_environment(cls) -> "LiveMattermostBursarBoundary":
        configuration = SwitchConfiguration.from_env()
        if not configuration.channel_id:
            raise ValueError("SWITCH_CHANNEL_ID is required for the webhook/API intake boundary")
        model_configuration = ModelConfiguration.from_env()
        adapter = MattermostSwitchAdapter(configuration)
        return cls(adapter, configuration.channel_id, agent_provider=ModelAgentProvider(model_configuration))

    def receive_message(self, message: SwitchMessage) -> BursarWorkflowResult:
        self._validate_room(message.room_id)
        if message.message_type != MessageType.INVOICE_INTAKE:
            raise ValueError("live intake accepts only invoice_intake messages")
        if message.sender_type == SenderType.AGENT:
            raise PermissionError("agents cannot submit invoice intake")
        intake = InvoiceIntake.model_validate(message.payload)
        result = self.coordinator.start_case(message, require_posted=False)
        if self.agent_provider is not None:
            result = self.coordinator.run_extraction_agent(message.case.case_id, invoice_text=intake.invoice_text)
        return result

    def receive_command(self, request: SwitchCommandRequest) -> BursarWorkflowResult:
        self._validate_room(request.room_id)
        parsed = self.adapter.parse_human_command(request.command, request.actor_id, request.actor_type)
        case = self.coordinator.cases.get(parsed.case_id)
        if case is None:
            raise ValueError("unknown Bursar case")
        if case.room_id != request.room_id:
            raise ValueError("command targets a different room")
        return self.coordinator.decide(request.command, request.actor_id, request.actor_type)

    def _validate_room(self, room_id: str) -> None:
        if room_id != self.configured_room_id:
            raise ValueError("message targets a different configured room")
