"""
Step 4 – One LLM call: classify + extract.
Masked text goes in; structured JSON comes out.
"""
from __future__ import annotations

import json
import logging

from openai import OpenAI
from pydantic import ValidationError

from app.config import settings
from app.extract.models import LLMOutput, VantageFields

log = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You classify one document and fill a JSON object.

Allowed document_type values:
  supplier_invoice
  purchase_order
  payment_receipt

Fields:
  supplier_name    - string or null
  invoice_number   - string or null
  invoice_date     - ISO 8601 date string or null (YYYY-MM-DD)
  po_number        - string or null
  tax_amount       - number (rupees) or null
  total_amount     - number (rupees) or null

The text may contain placeholders such as <PERSON_1> or <BANK_1>.
Copy placeholders unchanged into the relevant field. Do not guess the hidden value.
If a field is not present on the page, return null.
Return ONLY valid JSON matching this schema, with no markdown fences:

{
  "document_type": "...",
  "fields": {
    "supplier_name": ...,
    "invoice_number": ...,
    "invoice_date": ...,
    "po_number": ...,
    "tax_amount": ...,
    "total_amount": ...
  }
}
"""


def _get_client() -> OpenAI:
    return OpenAI(
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
    )


def call_llm(masked_text: str) -> LLMOutput:
    """
    Send masked OCR text to the LLM, parse response.
    Raises ValueError on schema mismatch.
    """
    client = _get_client()

    response = client.chat.completions.create(
        model=settings.openai_model,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": masked_text},
        ],
        temperature=0,
        max_tokens=512,
    )

    raw = response.choices[0].message.content or ""
    # Strip any accidental markdown fences
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        log.warning("llm_json_parse_error class=%s", type(exc).__name__)
        raise ValueError("schema_invalid") from exc

    try:
        return LLMOutput(**parsed)
    except (ValidationError, TypeError) as exc:
        log.warning("llm_schema_invalid class=%s", type(exc).__name__)
        raise ValueError("schema_invalid") from exc
