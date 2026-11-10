"""
Step 5 – Business rule check.

Priority chain (first match wins):
  1. Not applicable – the only document(s) are payment receipts
  2. Duplicate      – invoice number already processed (wins over everything else)
  3. Incomplete     – invoice or PO missing, or a total could not be read
  4. Approve        – totals equal to the paisa
  5. Hold           – totals differ by any amount

An invoice number is recorded only when the pair is fully checked (Approve or
Hold). Uploading an invoice without its PO therefore does not "burn" the
number, and the later complete submission is not flagged Duplicate.

Reasons never contain names, invoice numbers or account numbers.
"""
from __future__ import annotations

from app.check.normalize import normalize_invoice_number
from app.check.store import is_duplicate, record_invoice
from app.extract.models import CheckResult, LLMOutput

_INVOICE = "supplier_invoice"
_PO = "purchase_order"
_RECEIPT = "payment_receipt"


def _round2(value: float | None) -> float | None:
    if value is None:
        return None
    return round(value, 2)


def _duplicate(totals_mismatch: bool) -> CheckResult:
    warning = " Totals also do not match." if totals_mismatch else ""
    return CheckResult(
        status="Duplicate",
        reason=f"This invoice number has already been processed.{warning}",
    )


def run_check(doc1: LLMOutput, doc2: LLMOutput | None = None) -> CheckResult:
    """Apply Vantage business rules. doc2 is the paired document, if supplied."""
    docs = [d for d in (doc1, doc2) if d is not None]
    types = {d.document_type for d in docs}

    # 1. Receipts only
    if types == {_RECEIPT}:
        return CheckResult(
            status="Not applicable",
            reason="Payment receipt received; no invoice check required.",
        )

    invoice = next((d for d in docs if d.document_type == _INVOICE), None)
    po = next((d for d in docs if d.document_type == _PO), None)

    inv_total = _round2(invoice.fields.total_amount) if invoice else None
    po_total = _round2(po.fields.total_amount) if po else None
    mismatch = inv_total is not None and po_total is not None and inv_total != po_total

    # 2. Duplicate (any time an invoice with a readable number is present)
    norm_inv = normalize_invoice_number(invoice.fields.invoice_number) if invoice else None
    if norm_inv and is_duplicate(norm_inv):
        return _duplicate(mismatch)

    # 3. Incomplete
    if invoice is None or po is None:
        return CheckResult(
            status="Incomplete",
            reason="Both a supplier invoice and a purchase order are required.",
        )
    if inv_total is None or po_total is None:
        return CheckResult(
            status="Incomplete",
            reason="Could not determine totals from one or both documents.",
        )

    # Fully checked → record so a resubmission is caught
    if norm_inv and not record_invoice(norm_inv):
        return _duplicate(mismatch)  # concurrent request recorded it first

    # 4 / 5. Totals
    if inv_total == po_total:
        return CheckResult(status="Approve", reason="Invoice total equals purchase-order total.")
    return CheckResult(
        status="Hold",
        reason=(
            f"Invoice total ({inv_total:.2f}) does not match "
            f"purchase-order total ({po_total:.2f})."
        ),
    )
