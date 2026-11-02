"""
Step 5 – Business rule check.

Determines status from two documents (invoice + PO) or a single document.
"""
from __future__ import annotations

from app.check.normalize import normalize_invoice_number
from app.check.store import is_duplicate, record_invoice
from app.extract.models import CheckResult, LLMOutput

# Canonical document types as returned by LLM
_INVOICE = "supplier_invoice"
_PO = "purchase_order"
_RECEIPT = "payment_receipt"


def _round2(value: float | None) -> float | None:
    if value is None:
        return None
    return round(value, 2)


def run_check(
    doc1: LLMOutput,
    doc2: LLMOutput | None = None,
) -> CheckResult:
    """
    Apply Vantage business rules.
    doc1 is the primary document; doc2 is the paired document (if supplied).
    """
    types = {doc1.document_type}
    if doc2 is not None:
        types.add(doc2.document_type)

    # --- Single payment receipt ---
    if types == {_RECEIPT}:
        return CheckResult(status="Not applicable", reason="Payment receipt received; no invoice check required.")

    # --- Find invoice and PO ---
    invoice: LLMOutput | None = None
    po: LLMOutput | None = None

    for doc in filter(None, [doc1, doc2]):
        if doc.document_type == _INVOICE:
            invoice = doc
        elif doc.document_type == _PO:
            po = doc

    # --- Incomplete ---
    if invoice is None or po is None:
        return CheckResult(status="Incomplete", reason="Both a supplier invoice and a purchase order are required.")

    # --- Duplicate check (takes priority) ---
    norm_inv = normalize_invoice_number(invoice.fields.invoice_number)
    duplicate = False
    if norm_inv:
        duplicate = is_duplicate(norm_inv)

    inv_total = _round2(invoice.fields.total_amount)
    po_total = _round2(po.fields.total_amount)

    if duplicate:
        warning = ""
        if inv_total is not None and po_total is not None and inv_total != po_total:
            warning = " Totals do not match."
        return CheckResult(
            status="Duplicate",
            reason=f"This invoice number has already been processed.{warning}",
        )

    # Record now (after duplicate check passes)
    if norm_inv:
        record_invoice(norm_inv)

    # --- Totals check ---
    if inv_total is None or po_total is None:
        return CheckResult(
            status="Incomplete",
            reason="Could not determine totals from one or both documents.",
        )

    if inv_total == po_total:
        return CheckResult(
            status="Approve",
            reason="Invoice total equals purchase-order total.",
        )
    else:
        return CheckResult(
            status="Hold",
            reason=f"Invoice total ({inv_total:.2f}) does not match purchase-order total ({po_total:.2f}).",
        )
