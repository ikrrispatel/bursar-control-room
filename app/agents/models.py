from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class AgentSourceLocation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_id: str = Field(min_length=1)
    file_name: str = Field(min_length=1)
    source_location: str = Field(min_length=1)
    page: int | None = Field(default=None, ge=1)


class ExtractedInvoiceFields(BaseModel):
    model_config = ConfigDict(extra="forbid")

    vendor_name: str | None = None
    invoice_number: str | None = None
    invoice_date: str | None = None
    purchase_order_number: str | None = None
    total: str | None = None
    currency: str | None = None


class AgentExtractionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(min_length=1)
    invoice_text: str = Field(default="", max_length=12000)
    evidence_locations: list[AgentSourceLocation] = Field(default_factory=list, max_length=50)


class AgentExtractionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(min_length=1)
    agent_role: Literal["intake_extraction_agent"]
    mode: Literal["fixture", "model_assisted"]
    extracted_fields: ExtractedInvoiceFields
    confidence: float = Field(ge=0, le=1)
    source_locations: list[AgentSourceLocation] = Field(max_length=50)
    missing_fields: list[str] = Field(max_length=20)
    uncertainty_explanations: list[str] = Field(max_length=20)
    summary: str = Field(min_length=1, max_length=2000)
