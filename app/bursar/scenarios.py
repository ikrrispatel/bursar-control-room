from __future__ import annotations

import json
import tempfile
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.bursar.evidence import evidence_reference
from app.bursar.models import EvidenceReference
from app.schemas.common import LineItem, Party
from app.schemas.delivery_note import DeliveryNote
from app.schemas.invoice import Invoice
from app.schemas.purchase_order import PurchaseOrder
from app.services.duplicates import check_duplicate
from app.services.matching import match_invoice_po_delivery
from app.switch_adapter import CaseCorrelation, MessageType, SwitchMessage


ScenarioName = Literal[
    "clean_invoice",
    "duplicate_invoice",
    "missing_evidence",
    "conflicting_evidence",
    "human_override",
]


class ScenarioEvidenceFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str = Field(min_length=1)
    path: Path
    source_location: str


class ScenarioExpectation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    duplicate_status: str
    matching_status: str
    case_status: str
    ledger_result: bool
    decision_action: Literal["approve", "reject", "request_clarification", "override"]
    decision_reason: str | None = None


class ScenarioFixture(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: ScenarioName
    case_id: str
    invoice: Invoice
    vendor: Party
    purchase_order: PurchaseOrder | None = None
    delivery_evidence: DeliveryNote | None = None
    evidence_files: list[ScenarioEvidenceFile]
    prior_case_id: str | None = None
    expected: ScenarioExpectation


class ScenarioEvaluation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fixture: ScenarioFixture
    evidence_references: list[EvidenceReference]
    duplicate_result: dict
    matching_result: dict
    intake_message: SwitchMessage


ROOT = Path(__file__).resolve().parents[2]


def _party() -> Party:
    return Party(name="Acme Supplies", iban="GB33BUKB20201555555555", vat_number="GB123456789")


def _invoice(number: str, total: str = "110.00") -> Invoice:
    vendor = _party()
    return Invoice(
        invoice_number=number,
        po_number="PO-001",
        vendor=vendor,
        issue_date=date(2025, 6, 21),
        currency="USD",
        line_items=[LineItem(description="Office supplies", quantity=Decimal("1"), unit_price=Decimal("100"), line_total=Decimal("100"))],
        subtotal=Decimal("100"),
        tax_amount=Decimal("10") if total == "110.00" else Decimal("0"),
        total_amount=Decimal(total),
    )


def _purchase_order(total: str = "110.00") -> PurchaseOrder:
    vendor = _party()
    return PurchaseOrder(
        po_number="PO-001",
        vendor=vendor,
        issue_date=date(2025, 6, 1),
        currency="USD",
        line_items=[LineItem(description="Office supplies", quantity=Decimal("1"), unit_price=Decimal("100"), line_total=Decimal("100"))],
        subtotal=Decimal("100"),
        tax_amount=Decimal("10") if total == "110.00" else Decimal("0"),
        total_amount=Decimal(total),
    )


def _delivery() -> DeliveryNote:
    return DeliveryNote(
        delivery_note_number="DN-001",
        po_number="PO-001",
        vendor=_party(),
        delivery_date=date(2025, 6, 25),
        delivered_items=[LineItem(description="Office supplies", quantity=Decimal("1"), unit_price=Decimal("100"), line_total=Decimal("100"))],
        delivery_status="delivered",
    )


def load_scenarios() -> list[ScenarioFixture]:
    files = lambda invoice, po=None, delivery=None: [
        ScenarioEvidenceFile(kind="invoice", path=ROOT / "samples" / invoice, source_location=f"fixture://{invoice}"),
        *([] if po is None else [ScenarioEvidenceFile(kind="purchase_order", path=ROOT / "samples" / po, source_location=f"fixture://{po}")]),
        *([] if delivery is None else [ScenarioEvidenceFile(kind="delivery_note", path=ROOT / "samples" / delivery, source_location=f"fixture://{delivery}")]),
    ]
    clean = ScenarioFixture(
        name="clean_invoice", case_id="scenario-clean", invoice=_invoice("INV-001"), vendor=_party(), purchase_order=_purchase_order(), delivery_evidence=_delivery(),
        evidence_files=files("invoice_001_canada_post_sample.pdf", "purchase_order_001_polychemtex.pdf", "delivery_note_001_bunker_receipt.pdf"),
        expected=ScenarioExpectation(duplicate_status="clear", matching_status="matched", case_status="pending_review", ledger_result=True, decision_action="approve"),
    )
    return [
        clean,
        ScenarioFixture(
            name="duplicate_invoice", case_id="scenario-duplicate", invoice=_invoice("INV-001"), vendor=_party(), purchase_order=_purchase_order(), delivery_evidence=_delivery(), prior_case_id=clean.case_id,
            evidence_files=files("invoice_010_priparcel_duplicate.pdf", "purchase_order_001_polychemtex.pdf", "delivery_note_001_bunker_receipt.pdf"),
            expected=ScenarioExpectation(duplicate_status="confirmed_duplicate", matching_status="matched", case_status="blocked", ledger_result=False, decision_action="reject", decision_reason="duplicate invoice"),
        ),
        ScenarioFixture(
            name="missing_evidence", case_id="scenario-missing", invoice=_invoice("INV-MISSING"), vendor=_party(), purchase_order=_purchase_order(), delivery_evidence=None,
            evidence_files=files("invoice_002_tax_sample_local_supply.pdf", "purchase_order_002_sample.pdf"),
            expected=ScenarioExpectation(duplicate_status="clear", matching_status="mismatch", case_status="needs_evidence", ledger_result=False, decision_action="request_clarification"),
        ),
        ScenarioFixture(
            name="conflicting_evidence", case_id="scenario-conflict", invoice=_invoice("INV-CONFLICT"), vendor=_party(), purchase_order=_purchase_order("100.00"), delivery_evidence=_delivery(),
            evidence_files=files("invoice_020_demo_20tax_001.pdf", "purchase_order_002_sample.pdf", "delivery_note_002_template.pdf"),
            expected=ScenarioExpectation(duplicate_status="clear", matching_status="mismatch", case_status="blocked", ledger_result=False, decision_action="request_clarification"),
        ),
        ScenarioFixture(
            name="human_override", case_id="scenario-override", invoice=_invoice("INV-OVERRIDE"), vendor=_party(), purchase_order=_purchase_order(), delivery_evidence=_delivery(),
            evidence_files=files("invoice_003_handwritten_20tax.pdf", "purchase_order_003_sample.pdf", "delivery_note_003_en_sample.pdf"),
            expected=ScenarioExpectation(duplicate_status="clear", matching_status="matched", case_status="pending_review", ledger_result=True, decision_action="override", decision_reason="verified vendor exception"),
        ),
    ]


def evaluate_scenario(fixture: ScenarioFixture, room_id: str) -> ScenarioEvaluation:
    references = [evidence_reference(fixture.case_id, item.kind, item.path, item.source_location) for item in fixture.evidence_files]
    with tempfile.TemporaryDirectory() as directory:
        seen_path = Path(directory) / "seen.jsonl"
        if fixture.prior_case_id:
            seen_path.write_text(json.dumps({"vendor_name": fixture.vendor.name, "invoice_number": fixture.invoice.invoice_number, "total_amount": str(fixture.invoice.total_amount), "issue_date": fixture.invoice.issue_date.isoformat()}) + "\n", encoding="utf-8")
        duplicate_result = check_duplicate(fixture.vendor.name, fixture.invoice.invoice_number, fixture.invoice.total_amount, fixture.invoice.issue_date, seen_path)
    matching_result = match_invoice_po_delivery(fixture.invoice, fixture.purchase_order, fixture.delivery_evidence)
    conflicting = [
        reason
        for reason in matching_result["mismatch_reasons"]
        if not reason.startswith("missing_")
    ]
    missing = ["delivery_note"] if fixture.delivery_evidence is None else []
    policy_warning = "manual vendor verification required" if fixture.name == "human_override" else None
    payload = {
        "vendor_name": fixture.vendor.name,
        "invoice_number": fixture.invoice.invoice_number,
        "total": fixture.invoice.total_amount,
        "currency": fixture.invoice.currency,
        "evidence": references,
        "duplicate_of": fixture.invoice.invoice_number if duplicate_result["duplicate_status"] == "confirmed_duplicate" else None,
        "duplicate_case_id": fixture.prior_case_id,
        "missing_evidence": missing,
        "conflicting_evidence": conflicting,
        "policy_warning": policy_warning,
    }
    intake = SwitchMessage(
        room_id=room_id,
        case=CaseCorrelation(case_id=fixture.case_id),
        message_type=MessageType.INVOICE_INTAKE,
        sender_type="human",
        sender_id="requester-fixture",
        payload=payload,
    )
    return ScenarioEvaluation(fixture=fixture, evidence_references=references, duplicate_result=duplicate_result, matching_result=matching_result, intake_message=intake)
