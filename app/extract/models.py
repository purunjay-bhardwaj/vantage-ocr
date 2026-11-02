"""Pydantic models for extracted fields and the full API response."""
from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, field_validator


class VantageFields(BaseModel):
    supplier_name: str | None = None
    invoice_number: str | None = None
    invoice_date: str | None = None
    po_number: str | None = None
    tax_amount: float | None = None
    total_amount: float | None = None


class CheckResult(BaseModel):
    status: Literal["Approve", "Hold", "Duplicate", "Incomplete", "Not applicable"]
    reason: str  # no names, IDs, or account numbers


class PiiInfo(BaseModel):
    masked_before_llm: bool
    entity_counts: dict[str, int]


class PipelineInfo(BaseModel):
    ocr_engine: str
    used_vision_fallback: bool
    timings_ms: dict[str, int]


class ExtractResponse(BaseModel):
    request_id: str
    document_type: str
    fields: VantageFields
    check: CheckResult
    pii: PiiInfo
    pipeline: PipelineInfo


# ─── LLM raw output ────────────────────────────────────────────────────────────

class LLMOutput(BaseModel):
    """Schema the LLM must return. document_type uses title-case from prompt."""
    document_type: str
    fields: VantageFields
