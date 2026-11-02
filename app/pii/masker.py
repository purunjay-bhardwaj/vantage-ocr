"""
Step 3 – PII masking with Microsoft Presidio.

Design:
- Stable placeholder per distinct value per request (<PERSON_1>, <PHONE_1>, …).
- Normalize text (case + whitespace) before token assignment so "RAVI MENON"
  and "ravi menon" get the same token.
- The vault (token→real) is returned but NEVER logged or written to disk.
- Caller must clear the vault when the request ends.
"""
from __future__ import annotations

import logging
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from presidio_analyzer import AnalyzerEngine, RecognizerRegistry
from presidio_anonymizer import AnonymizerEngine
from presidio_anonymizer.entities import OperatorConfig

from app.pii.recognizers import get_custom_recognizers

log = logging.getLogger(__name__)

# Entity types to mask
_ENTITIES = [
    "PERSON",
    "PHONE_NUMBER",
    "EMAIL_ADDRESS",
    "IBAN_CODE",
    "CREDIT_CARD",
    "LOCATION",          # addresses
    "IN_MOBILE",
    "BANK_ACCOUNT",
    "IFSC",
    "AADHAAR",
    "PAN",
    "POLICY_NUMBER",
    "ROLL_NUMBER",
    "US_SSN",            # catch-all for generic ID patterns
]

# Short prefix per entity type
_PREFIX: dict[str, str] = {
    "PERSON": "PERSON",
    "PHONE_NUMBER": "PHONE",
    "EMAIL_ADDRESS": "EMAIL",
    "IBAN_CODE": "BANK",
    "CREDIT_CARD": "CARD",
    "LOCATION": "ADDR",
    "IN_MOBILE": "PHONE",
    "BANK_ACCOUNT": "BANK",
    "IFSC": "IFSC",
    "AADHAAR": "ID",
    "PAN": "ID",
    "POLICY_NUMBER": "ID",
    "ROLL_NUMBER": "ID",
    "US_SSN": "ID",
}


def _normalize_value(value: str) -> str:
    """Lowercase and collapse whitespace for stable token assignment."""
    return re.sub(r"\s+", " ", value.strip().lower())


@dataclass
class MaskResult:
    masked_text: str
    vault: dict[str, str]          # token → original value (NEVER logged)
    entity_counts: dict[str, int]
    placeholder_count: int


def _build_analyzer() -> AnalyzerEngine:
    registry = RecognizerRegistry()
    registry.load_predefined_recognizers()
    for rec in get_custom_recognizers():
        registry.add_recognizer(rec)
    return AnalyzerEngine(registry=registry)


# Module-level singletons (loaded once at import time)
_analyzer = _build_analyzer()
_anonymizer = AnonymizerEngine()


def mask_text(text: str) -> MaskResult:
    """
    Analyze and anonymize the OCR text.
    Returns MaskResult with masked_text, vault (keep in memory only),
    entity_counts, and placeholder_count.
    """
    results = _analyzer.analyze(
        text=text,
        entities=_ENTITIES,
        language="en",
    )

    # Build stable placeholder map
    # norm_value → token
    value_to_token: dict[str, str] = {}
    # entity_type → counter
    type_counter: defaultdict[str, int] = defaultdict(int)
    entity_counts: defaultdict[str, int] = defaultdict(int)

    # Sort by start so assignment is deterministic left-to-right
    sorted_results = sorted(results, key=lambda r: r.start)

    operators: dict[str, OperatorConfig] = {}

    for res in sorted_results:
        raw_value = text[res.start:res.end]
        norm = _normalize_value(raw_value)
        entity_counts[res.entity_type] += 1

        if norm not in value_to_token:
            prefix = _PREFIX.get(res.entity_type, "ENTITY")
            type_counter[prefix] += 1
            token = f"<{prefix}_{type_counter[prefix]}>"
            value_to_token[norm] = token

    # Map from original (non-normalized) to token for anonymizer
    # Presidio anonymizer needs a custom operator; we use "replace"
    # with a lambda based on the detected span value.
    # Since Presidio's replace operator takes a fixed string, we build
    # individual calls: replace each entity with its token.

    masked = text
    # Process in reverse order to keep offsets valid
    for res in sorted(sorted_results, key=lambda r: r.start, reverse=True):
        raw_value = text[res.start:res.end]
        norm = _normalize_value(raw_value)
        token = value_to_token[norm]
        masked = masked[:res.start] + token + masked[res.end:]

    # Build vault: token → original raw value
    vault: dict[str, str] = {}
    # We need to map token → first seen raw value
    seen_norm: dict[str, str] = {}
    for res in sorted_results:
        raw_value = text[res.start:res.end]
        norm = _normalize_value(raw_value)
        if norm not in seen_norm:
            seen_norm[norm] = raw_value
    for norm, token in value_to_token.items():
        vault[token] = seen_norm[norm]

    placeholder_count = len(vault)

    return MaskResult(
        masked_text=masked,
        vault=vault,
        entity_counts=dict(entity_counts),
        placeholder_count=placeholder_count,
    )


def restore_field(value: Any, vault: dict[str, str]) -> Any:
    """
    Restore placeholders in a string field value after the model returns.
    Non-string values are returned unchanged.
    """
    if not isinstance(value, str):
        return value
    for token, original in vault.items():
        value = value.replace(token, original)
    return value
