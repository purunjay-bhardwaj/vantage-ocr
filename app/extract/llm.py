"""
Step 4 – One LLM call: classify + extract.
Masked text goes in; structured JSON comes out.

Errors are raised as ValueError with a fixed, content-free code:
  "schema_invalid"   – model reply was not valid JSON / did not match schema
  "llm_unavailable"  – network / auth / rate-limit / timeout from the provider
"""
from __future__ import annotations

import json
import logging
import re

from openai import OpenAI, OpenAIError
from pydantic import ValidationError

from app.config import settings
from app.extract.models import DOC_TYPES, LLMOutput

log = logging.getLogger(__name__)

PROMPT_VERSION = "v2"

_SYSTEM_PROMPT = """\
You classify one document and fill a JSON object.

Allowed document_type values (use exactly one, lowercase):
  supplier_invoice
  purchase_order
  payment_receipt

Fields:
  supplier_name    - string or null
  invoice_number   - string or null (copy exactly as printed)
  invoice_date     - ISO 8601 date string or null (YYYY-MM-DD)
  po_number        - string or null
  tax_amount       - number (rupees) or null
  total_amount     - number (rupees) or null. If the page prints a subtotal
                     and a grand total, use the grand total (final amount due).

The text may contain placeholders such as <PERSON_1> or <BANK_1>.
Copy placeholders unchanged into the relevant field. Do not guess the hidden value.
Never put a bank account, phone number or ID placeholder in any field.
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

_FENCE_RE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL | re.IGNORECASE)


def _get_client() -> OpenAI:
    return OpenAI(
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
        timeout=settings.llm_timeout_s,
        max_retries=1,
    )


def parse_llm_reply(raw: str) -> LLMOutput:
    """Strip fences, parse JSON and validate. Raises ValueError('schema_invalid')."""
    raw = (raw or "").strip()
    m = _FENCE_RE.match(raw)
    if m:
        raw = m.group(1)
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        log.warning("llm_json_parse_error class=%s", type(exc).__name__)
        raise ValueError("schema_invalid") from exc
    if not isinstance(parsed, dict):
        raise ValueError("schema_invalid")
    try:
        out = LLMOutput(**parsed)
    except (ValidationError, TypeError) as exc:
        log.warning("llm_schema_invalid class=%s", type(exc).__name__)
        raise ValueError("schema_invalid") from exc
    if out.document_type not in DOC_TYPES:
        log.warning("llm_unknown_doc_type")
        raise ValueError("schema_invalid")
    return out


def call_llm(masked_text: str) -> LLMOutput:
    """Send masked OCR text to the LLM and parse the response."""
    client = _get_client()
    try:
        response = client.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": masked_text},
            ],
            temperature=0,
            max_tokens=512,
        )
    except OpenAIError as exc:
        # Never log the exception message: some providers echo the prompt.
        log.warning("llm_call_failed class=%s", type(exc).__name__)
        raise ValueError("llm_unavailable") from exc

    raw = response.choices[0].message.content if response.choices else ""
    return parse_llm_reply(raw or "")
