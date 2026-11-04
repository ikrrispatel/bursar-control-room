from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.bursar.models import EvidenceReference


class InvoiceIntake(BaseModel):
    """Synthetic, structured intake data used by the local fixture workflow."""

    model_config = ConfigDict(extra="forbid")

    vendor_name: str = Field(min_length=1)
    invoice_number: str = Field(min_length=1)
    total: Decimal = Field(ge=0)
    currency: str = Field(min_length=1)
    evidence: list[EvidenceReference] = Field(default_factory=list)
    duplicate_of: str | None = None
    missing_evidence: list[str] = Field(default_factory=list)
    conflicting_evidence: list[str] = Field(default_factory=list)
    policy_warning: str | None = None


class FixtureFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    finding_type: str = Field(min_length=1)
    status: str = Field(min_length=1)
    explanation: str = Field(min_length=1)
    evidence: list[dict] = Field(default_factory=list)


class FixtureCheckResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    extraction: FixtureFinding
    duplicate: FixtureFinding
    evidence: FixtureFinding
    policy: FixtureFinding
    risk: FixtureFinding
    current_status: str


def run_fixture_checks(intake: InvoiceIntake) -> FixtureCheckResult:
    extraction = FixtureFinding(
        finding_type="extraction",
        status="complete",
        explanation=f"Extracted {intake.vendor_name} invoice {intake.invoice_number} for {intake.total} {intake.currency}.",
    )
    duplicate = FixtureFinding(
        finding_type="duplicate",
        status="duplicate" if intake.duplicate_of else "clear",
        explanation=(
            f"Matches prior invoice {intake.duplicate_of}."
            if intake.duplicate_of
            else "No duplicate invoice was identified in the fixture set."
        ),
    )
    evidence = FixtureFinding(
        finding_type="evidence",
        status="missing" if intake.missing_evidence else "complete",
        explanation=(
            f"Missing evidence: {', '.join(intake.missing_evidence)}."
            if intake.missing_evidence
            else "Required fixture evidence is complete."
        ),
    )
    policy_status = "conflict" if intake.conflicting_evidence else "warning" if intake.policy_warning else "matched"
    policy_explanation = (
        f"Conflicting evidence: {', '.join(intake.conflicting_evidence)}."
        if intake.conflicting_evidence
        else intake.policy_warning or "Purchase-order and delivery fixture checks match."
    )
    policy = FixtureFinding(
        finding_type="policy_matching",
        status=policy_status,
        explanation=policy_explanation,
    )

    blocked = bool(intake.duplicate_of or intake.conflicting_evidence)
    needs_evidence = bool(intake.missing_evidence)
    risk_status = "blocked" if blocked else "needs_evidence" if needs_evidence else "warning" if intake.policy_warning else "clear"
    risk = FixtureFinding(
        finding_type="risk_summary",
        status=risk_status,
        explanation=(
            "Duplicate or conflicting evidence blocks automatic approval."
            if blocked
            else "Evidence is incomplete and requires clarification."
            if needs_evidence
            else intake.policy_warning or "Fixture checks are clear for human review."
        ),
    )
    current_status = "blocked" if blocked else "needs_evidence" if needs_evidence else "pending_review"
    return FixtureCheckResult(
        extraction=extraction,
        duplicate=duplicate,
        evidence=evidence,
        policy=policy,
        risk=risk,
        current_status=current_status,
    )
