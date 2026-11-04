from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.bursar.checks import FixtureCheckResult, InvoiceIntake, run_fixture_checks
from app.bursar.decisions import apply_human_decision, create_simulated_ledger_entry
from app.bursar.models import AuditEvent, BursarCase, CaseStatus, HumanDecision, SimulatedLedgerEntry, utc_now
from app.switch_adapter import (
    AgentRole,
    CaseCorrelation,
    LocalFixtureSwitchAdapter,
    MessageType,
    SwitchMessage,
)


class IntakeAcknowledgementPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    status: str
    message: str


class FindingPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    finding_type: str
    status: str
    explanation: str
    evidence: list[dict] = Field(default_factory=list)


class DecisionRequestPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    current_status: str
    findings: list[FindingPayload]
    evidence: list[dict]
    allowed_actions: list[str]


class DecisionRecordedPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    action: str
    actor_id: str
    reason: str | None = None
    status: str


class LedgerResultPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    status: str
    entry_id: str
    amount: str
    currency: str
    approved_by: str


class BursarWorkflowResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case: BursarCase
    checks: FixtureCheckResult
    messages: list[SwitchMessage]
    audit_events: list[AuditEvent] = Field(default_factory=list)
    ledger_entry: SimulatedLedgerEntry | None = None


class LocalBursarWorkflowCoordinator:
    """Coordinates deterministic Bursar state with a local Switch adapter."""

    def __init__(self, adapter: LocalFixtureSwitchAdapter | None = None) -> None:
        self.adapter = adapter or LocalFixtureSwitchAdapter()
        self.cases: dict[str, BursarCase] = {}
        self.checks: dict[str, FixtureCheckResult] = {}
        self.messages: dict[str, list[SwitchMessage]] = {}
        self.audit_events: dict[str, list[AuditEvent]] = {}
        self.ledger_entries: dict[str, SimulatedLedgerEntry] = {}

    def start_case(self, intake_message: SwitchMessage) -> BursarWorkflowResult:
        if intake_message.message_type != MessageType.INVOICE_INTAKE:
            raise ValueError("case intake requires an invoice_intake message")
        if intake_message.sender_type.value == "agent":
            raise PermissionError("agents cannot submit case intake")
        if not any(
            message.message_id == intake_message.message_id
            for message in self.adapter.list_case_messages(intake_message.room_id, intake_message.case.case_id)
        ):
            raise ValueError("case intake message must already be posted in its Switch room")
        case_id = intake_message.case.case_id
        if case_id in self.cases:
            raise ValueError(f"case already exists: {case_id}")

        intake = InvoiceIntake.model_validate(intake_message.payload)
        checks = run_fixture_checks(intake)
        case = BursarCase(
            case_id=case_id,
            requester_id=intake_message.sender_id,
            room_id=intake_message.room_id,
            intake_message_id=intake_message.message_id,
            vendor_name=intake.vendor_name,
            invoice_number=intake.invoice_number,
            total=intake.total,
            currency=intake.currency,
            status=CaseStatus(checks.current_status),
        )
        self.cases[case_id] = case
        self.checks[case_id] = checks
        self.audit_events[case_id] = []
        posted = [self._post_ack(case), *self._post_findings(case, checks), self._post_decision_request(case, checks, intake)]
        self.messages[case_id] = posted
        return BursarWorkflowResult(case=case, checks=checks, messages=posted)

    def decide(self, command: str, actor_id: str, actor_type: str = "human") -> BursarWorkflowResult:
        parsed = self.adapter.parse_human_command(command, actor_id, actor_type)
        case = self.cases.get(parsed.case_id)
        if case is None:
            raise ValueError(f"unknown case: {parsed.case_id}")
        if parsed.action == "approve" and case.status in {CaseStatus.BLOCKED, CaseStatus.NEEDS_EVIDENCE}:
            raise ValueError("blocked or incomplete cases require clarification or override")

        decision = HumanDecision(
            action=parsed.action,
            actor_id=parsed.actor_id,
            reason=parsed.reason,
        )
        updated_case, event = apply_human_decision(case, decision)
        self.cases[case.case_id] = updated_case
        self.audit_events[case.case_id].append(event)
        recorded = self._post_decision_recorded(updated_case, decision)
        self.messages[case.case_id].append(recorded)
        ledger_entry = None
        if parsed.action in {"approve", "override"}:
            ledger_entry = create_simulated_ledger_entry(updated_case, self.audit_events[case.case_id])
            self.ledger_entries[case.case_id] = ledger_entry
            self.messages[case.case_id].append(self._post_ledger_result(updated_case, ledger_entry))
        return BursarWorkflowResult(
            case=updated_case,
            checks=self.checks[case.case_id],
            messages=list(self.messages[case.case_id]),
            audit_events=list(self.audit_events[case.case_id]),
            ledger_entry=ledger_entry,
        )

    def list_case_messages(self, case_id: str) -> list[SwitchMessage]:
        case = self.cases.get(case_id)
        if case is None or case.room_id is None:
            raise ValueError(f"unknown case: {case_id}")
        return self.adapter.list_case_messages(case.room_id, case_id)

    def _post(self, message: SwitchMessage) -> SwitchMessage:
        return self.adapter.post_message(message)

    def _post_ack(self, case: BursarCase) -> SwitchMessage:
        payload = IntakeAcknowledgementPayload(
            case_id=case.case_id,
            status="received",
            message="Invoice intake received; deterministic fixture checks started.",
        )
        return self._post(self._agent_message(case, MessageType.INTAKE_ACKNOWLEDGEMENT, AgentRole.INTAKE_AGENT, payload))

    def _post_findings(self, case: BursarCase, checks: FixtureCheckResult) -> list[SwitchMessage]:
        findings = [checks.extraction, checks.duplicate, checks.evidence, checks.policy, checks.risk]
        roles = [
            AgentRole.EXTRACTION_AGENT,
            AgentRole.DUPLICATE_AGENT,
            AgentRole.EVIDENCE_AGENT,
            AgentRole.POLICY_AGENT,
            AgentRole.RISK_AGENT,
        ]
        types = [
            MessageType.EXTRACTION_FINDING,
            MessageType.DUPLICATE_FINDING,
            MessageType.EVIDENCE_FINDING,
            MessageType.POLICY_FINDING,
            MessageType.RISK_SUMMARY,
        ]
        return [
            self._post(
                self._agent_message(
                    case,
                    message_type,
                    role,
                    FindingPayload(
                        case_id=case.case_id,
                        finding_type=finding.finding_type,
                        status=finding.status,
                        explanation=finding.explanation,
                        evidence=finding.evidence,
                    ),
                )
            )
            for finding, role, message_type in zip(findings, roles, types)
        ]

    def _post_decision_request(self, case: BursarCase, checks: FixtureCheckResult, intake: InvoiceIntake) -> SwitchMessage:
        findings = [
            FindingPayload(
                case_id=case.case_id,
                finding_type=finding.finding_type,
                status=finding.status,
                explanation=finding.explanation,
                evidence=finding.evidence,
            )
            for finding in [checks.extraction, checks.duplicate, checks.evidence, checks.policy, checks.risk]
        ]
        payload = DecisionRequestPayload(
            case_id=case.case_id,
            current_status=case.status.value,
            findings=findings,
            evidence=[reference.model_dump(mode="json") for reference in intake.evidence],
            allowed_actions=["approve", "reject", "request_clarification", "override"],
        )
        return self._post(
            SwitchMessage(
                room_id=case.room_id or "",
                case=CaseCorrelation(case_id=case.case_id),
                message_type=MessageType.HUMAN_DECISION_REQUEST,
                sender_type="system",
                sender_id="bursar-coordinator",
                payload=payload.model_dump(mode="json"),
                timestamp=utc_now(),
            )
        )

    def _post_decision_recorded(self, case: BursarCase, decision: HumanDecision) -> SwitchMessage:
        payload = DecisionRecordedPayload(
            case_id=case.case_id,
            action=decision.action.value,
            actor_id=decision.actor_id,
            reason=decision.reason,
            status=case.status.value,
        )
        return self._post(
            SwitchMessage(
                room_id=case.room_id or "",
                case=CaseCorrelation(case_id=case.case_id),
                message_type=MessageType.HUMAN_DECISION_RECORDED,
                sender_type="system",
                sender_id="bursar-coordinator",
                payload=payload.model_dump(mode="json"),
                timestamp=utc_now(),
            )
        )

    def _post_ledger_result(self, case: BursarCase, entry: SimulatedLedgerEntry) -> SwitchMessage:
        payload = LedgerResultPayload(
            case_id=case.case_id,
            status="created",
            entry_id=entry.entry_id,
            amount=str(entry.amount),
            currency=entry.currency,
            approved_by=entry.approved_by,
        )
        return self._post(
            SwitchMessage(
                room_id=case.room_id or "",
                case=CaseCorrelation(case_id=case.case_id),
                message_type=MessageType.LEDGER_RESULT,
                sender_type="system",
                sender_id="bursar-coordinator",
                payload=payload.model_dump(mode="json"),
                timestamp=utc_now(),
            )
        )

    def _agent_message(self, case: BursarCase, message_type: MessageType, role: AgentRole, payload: BaseModel) -> SwitchMessage:
        return SwitchMessage(
            room_id=case.room_id or "",
            case=CaseCorrelation(case_id=case.case_id),
            message_type=message_type,
            sender_type="agent",
            sender_id=role.value,
            agent_role=role,
            payload=payload.model_dump(mode="json"),
            timestamp=utc_now(),
        )
