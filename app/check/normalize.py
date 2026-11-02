"""
Invoice-number normalization rule.

Rule (documented in README):
  1. Strip leading/trailing whitespace.
  2. Remove all spaces and hyphens.
  3. Uppercase.

Examples:
  "INV-20411"  →  "INV20411"
  "inv 204 11" →  "INV20411"
  "INV 204-11" →  "INV20411"
"""
import re


def normalize_invoice_number(raw: str | None) -> str | None:
    if raw is None:
        return None
    s = raw.strip()
    s = re.sub(r"[\s\-]", "", s)
    return s.upper()
