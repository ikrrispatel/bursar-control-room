from __future__ import annotations

import json
import re
from typing import Any

from app.agents import FixtureAgentProvider, ModelAgentProvider, ModelConfiguration
from app.bursar.checks import InvoiceIntake
from app.bursar.repository import BursarRepository
from app.bursar.workflow import BursarWorkflowResult, LocalBursarWorkflowCoordinator
from app.switch_adapter.agent_config import SwitchAgentConfiguration
from app.switch_adapter.agent_protocol import SwitchAgentProtocolAdapter
from app.switch_adapter.models import CaseCorrelation, MessageType, SenderType, SwitchMessage, utc_now


INTAKE_PREFIX = re.compile(r"^\s*/?bursar\s+intake\s+(.+?)\s*$", re.IGNORECASE | re.DOTALL)


class SwitchBursarRuntime:
    """Turns Switch room events into Bursar intake/decision operations."""

    def __init__(self, adapter: SwitchAgentProtocolAdapter, coordinator: LocalBursarWorkflowCoordinator) -> None:
        self.adapter = adapter
        self.coordinator = coordinator

    def handle_event(self, event: dict[str, Any]) -> BursarWorkflowResult | None:
        if event.get("type") != "message" or event.get("room_id") != self.adapter.configuration.room_id:
            return None
        payload = event.get("payload")
        if not isinstance(payload, dict) or payload.get("sender_kind") == "platform":
            return None
        body = payload.get("body")
        if not isinstance(body, str) or not body.strip():
            return None
        actor_id = str(payload.get("sender") or payload.get("user_id") or payload.get("sender_name") or "")
        intake_match = INTAKE_PREFIX.match(body)
        if intake_match:
            intake_payload = json.loads(intake_match.group(1))
            case_id = str(intake_payload.get("case_id") or f"switch-{payload.get('message_id', 'intake')}")
            intake_payload.pop("case_id", None)
            intake = InvoiceIntake.model_validate(intake_payload)
            message = SwitchMessage(
                room_id=self.adapter.configuration.room_id,
                case=CaseCorrelation(case_id=case_id),
                message_type=MessageType.INVOICE_INTAKE,
                sender_type=SenderType.HUMAN,
                sender_id=actor_id,
                payload=intake.model_dump(mode="json"),
                timestamp=utc_now(),
            )
            result = self.coordinator.start_case(message, require_posted=False)
            if self.coordinator.agent_provider:
                return self.coordinator.run_extraction_agent(case_id, invoice_text=intake.invoice_text)
            return result
        if re.fullmatch(r"(?:approve|reject|request_clarification|override)\s+\S+(?:\s+.+)?", body.strip(), re.IGNORECASE):
            return self.coordinator.decide(body.strip(), actor_id)
        return None

    def run_once(self, *, start_from: str = "head") -> BursarWorkflowResult | None:
        for event in self.adapter.stream_events(start_from=start_from):
            result = self.handle_event(event)
            if result is not None:
                return result
        return None


def runtime_from_environment() -> SwitchBursarRuntime:
    configuration = SwitchAgentConfiguration.from_env()
    adapter = SwitchAgentProtocolAdapter(configuration)
    repository = BursarRepository.from_environment_optional()
    try:
        model_configuration = ModelConfiguration.from_env()
        provider = ModelAgentProvider(model_configuration)
    except (ValueError, TypeError):
        provider = FixtureAgentProvider()
    coordinator = LocalBursarWorkflowCoordinator(adapter=adapter, agent_provider=provider, repository=repository)
    return SwitchBursarRuntime(adapter, coordinator)
