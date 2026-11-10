"""Pydantic models for extracted fields and the full API response."""
from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, field_validator

DOC_TYPES = ("supplier_invoice", "purchase_order", "payment_receipt")


class VantageFields(BaseModel):
    supplier_name: str | None = None
    invoice_number: str | None = None
    invoice_date: str | None = None
    po_number: str | None = None
    tax_amount: float | None = None
    total_amount: float | None = None

    @field_validator("tax_amount", "total_amount", mode="before")
    @classmethod
    def _parse_amount(cls, v):
        """Accept 35400, "35400.00", "₹35,400.00", "Rs. 35,400"."""
        if v is None or isinstance(v, (int, float)):
            return v
        if isinstance(v, str):
            s = re.sub(r"(?i)rs\.?|inr|₹|,|\s", "", v)
            if s == "":
                return None
            return float(s)
        return v

    @field_validator("supplier_name", "invoice_number", "invoice_date", "po_number", mode="before")
    @classmethod
    def _blank_to_none(cls, v):
        if isinstance(v, str) and v.strip() == "":
            return None
        if isinstance(v, (int, float)):
            return str(v)
        return v


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
    """Schema the LLM must return."""
    document_type: str
    fields: VantageFields

    @field_validator("document_type", mode="before")
    @classmethod
    def _norm_doc_type(cls, v):
        # "Supplier Invoice" / "supplier-invoice" → "supplier_invoice"
        if isinstance(v, str):
            return re.sub(r"[\s\-]+", "_", v.strip().lower())
        return v
