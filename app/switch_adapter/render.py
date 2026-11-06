from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

from app.switch_adapter.models import MessageType, SwitchMessage


def _text(value: Any, default: str = "—") -> str:
    if value is None or value == "":
        return default
    return str(value).replace("\\", "\\\\").replace("`", "\\`").replace("|", "\\|").replace("\n", " ").strip()


def _status(value: Any) -> str:
    normalized = str(value or "unknown").replace("_", " ").strip().title()
    if normalized.casefold() in {"clear", "complete", "matched", "received", "created", "approved"}:
        return f"✅ {normalized}"
    if normalized.casefold() in {"blocked", "duplicate", "conflict", "missing", "rejected"}:
        return f"🛑 {normalized}"
    if normalized.casefold() in {"warning", "needs evidence", "pending review", "pending human decision"}:
        return f"⚠️ {normalized}"
    return f"• {normalized}"


def _invoice_header(payload: dict[str, Any]) -> list[str]:
    return [
        f"**Vendor:** {_text(payload.get('vendor_name'))}",
        f"**Invoice:** {_text(payload.get('invoice_number'))}",
        f"**Amount:** {_text(payload.get('amount', payload.get('total')))} {_text(payload.get('currency'), '')}".rstrip(),
    ]


def _fixture_note(payload: dict[str, Any]) -> str:
    mode = str(payload.get("mode", "fixture")).casefold()
    if mode in {"fixture", "fixture_mode", "deterministic"}:
        return "**Mode:** Deterministic fixture checks — not real document extraction"
    return f"**Mode:** {_text(payload.get('mode'))}"


def _finding_lines(findings: Iterable[dict[str, Any]]) -> list[str]:
    labels = {
        "extraction": "Extraction",
        "duplicate": "Duplicate check",
        "evidence": "Evidence completeness",
        "policy_matching": "Policy / matching",
        "risk_summary": "Risk summary",
        "intake_extraction": "AI intake extraction",
    }
    lines: list[str] = []
    for finding in findings:
        finding_type = str(finding.get("finding_type", "finding"))
        label = labels.get(finding_type, finding_type.replace("_", " ").title())
        lines.append(f"- **{_text(label)}:** {_status(finding.get('status'))} — {_text(finding.get('explanation'))}")
    return lines


def render_mattermost_message(message: SwitchMessage) -> str:
    """Render the concise human-facing room message without changing typed data."""
    payload = message.payload
    case_id = _text(message.case.case_id)
    if message.message_type == MessageType.INTAKE_ACKNOWLEDGEMENT:
        return "\n".join([
            "## Invoice intake received",
            f"**Case:** `{case_id}`",
            *_invoice_header(payload),
            _fixture_note(payload),
            "**Status:** Review checks started",
        ])
    if message.message_type in {
        MessageType.EXTRACTION_FINDING,
        MessageType.DUPLICATE_FINDING,
        MessageType.EVIDENCE_FINDING,
        MessageType.POLICY_FINDING,
        MessageType.RISK_SUMMARY,
    }:
        is_ai_extraction = message.message_type == MessageType.EXTRACTION_FINDING and "summary" in payload
        label = "AI intake extraction" if is_ai_extraction else str(payload.get("finding_type", message.message_type.value)).replace("_", " ").title()
        status = payload.get("status")
        if is_ai_extraction:
            status = "model-assisted" if str(payload.get("mode", "")).casefold() == "model_assisted" else "fixture"
        explanation = payload.get("summary", payload.get("explanation"))
        return "\n".join([
            f"### {label} finding",
            f"**Case:** `{case_id}` · **Status:** {_status(status)}",
            f"**Finding:** {_text(explanation)}",
            _fixture_note(payload),
        ])
    if message.message_type == MessageType.HUMAN_DECISION_REQUEST:
        findings = payload.get("findings", [])
        finding_lines = _finding_lines(findings if isinstance(findings, list) else [])
        return "\n".join([
            "## Human decision required",
            f"**Case:** `{case_id}`",
            *_invoice_header(payload),
            _fixture_note(payload),
            "",
            "**Five checks**",
            *(finding_lines or ["- No findings supplied"]),
            "",
            "**Gate:** ⏳ Pending human decision",
            "**Ledger:** 🔒 Locked — no entry exists before approval",
            "**Allowed actions:** `approve` · `reject <reason>` · `request_clarification` · `override <reason>`",
        ])
    if message.message_type == MessageType.HUMAN_DECISION_RECORDED:
        action = _text(payload.get("action"))
        return "\n".join([
            "## Human decision recorded",
            f"**Case:** `{case_id}` · **Decision:** `{action}`",
            f"**Status:** {_status(payload.get('status'))}",
            f"**Finance reviewer:** `{_text(payload.get('actor_id'))}`",
            f"**Reason:** {_text(payload.get('reason'), 'Not required')}",
            "**Authority:** Human decision gate satisfied",
            "**Ledger:** ⏳ Created only after authorized approval or override",
        ])
    if message.message_type == MessageType.LEDGER_RESULT:
        return "\n".join([
            "## Ledger result",
            f"**Case:** `{case_id}` · **Status:** {_status(payload.get('status'))}",
            f"**Entry:** `{_text(payload.get('entry_id'))}`",
            f"**Amount:** {_text(payload.get('amount'))} {_text(payload.get('currency'), '')}".rstrip(),
            f"**Approved by:** `{_text(payload.get('approved_by'))}`",
            "**Control:** Created only after authorized human approval",
        ])
    return f"### Bursar message\n**Case:** `{case_id}`\n**Type:** `{_text(message.message_type.value)}`"


def protocol_envelope(message: SwitchMessage) -> dict[str, Any]:
    """Return the optional technical representation stored in post properties."""
    return {"schema": "bursar.switch.message.v1", "message": message.model_dump(mode="json")}


def render_protocol_debug(message: SwitchMessage) -> str:
    """Return raw JSON only for explicit technical/debug inspection."""
    return json.dumps(protocol_envelope(message), indent=2, sort_keys=True)
