from app.check.rules import run_check
from app.check.store import is_duplicate, record_invoice
from app.extract.models import LLMOutput, VantageFields


def inv(total=1000.0, number="INV-20000"):
    return LLMOutput(document_type="supplier_invoice",
                     fields=VantageFields(invoice_number=number, total_amount=total))


def po(total=1000.0):
    return LLMOutput(document_type="purchase_order", fields=VantageFields(total_amount=total))


def receipt():
    return LLMOutput(document_type="payment_receipt", fields=VantageFields(total_amount=500.0))


def test_approve_and_records():
    r = run_check(inv(), po())
    assert r.status == "Approve"
    assert is_duplicate("INV20000")


def test_order_of_documents_does_not_matter():
    assert run_check(po(), inv()).status == "Approve"


def test_hold_one_rupee():
    assert run_check(inv(1000.0), po(1001.0)).status == "Hold"


def test_hold_one_paisa():
    assert run_check(inv(1000.00), po(1000.01)).status == "Hold"


def test_rounding_matches():
    assert run_check(inv(35400), po(35400.004)).status == "Approve"


def test_duplicate_with_normalized_number():
    run_check(inv(number="INV-20411"), po())
    r = run_check(inv(number="INV 204 11"), po())
    assert r.status == "Duplicate"


def test_duplicate_wins_over_hold():
    run_check(inv(), po())
    r = run_check(inv(), po(9999.0))
    assert r.status == "Duplicate"
    assert "Totals also do not match" in r.reason


def test_duplicate_wins_over_incomplete():
    record_invoice("INV20000")
    assert run_check(inv()).status == "Duplicate"


def test_incomplete_invoice_only_does_not_burn_number():
    assert run_check(inv()).status == "Incomplete"
    assert not is_duplicate("INV20000")
    assert run_check(inv(), po()).status == "Approve"


def test_incomplete_po_only():
    assert run_check(po()).status == "Incomplete"


def test_incomplete_missing_total():
    assert run_check(inv(total=None), po()).status == "Incomplete"


def test_incomplete_two_invoices():
    assert run_check(inv(), inv(number="INV-1")).status == "Incomplete"


def test_receipt_not_applicable():
    assert run_check(receipt()).status == "Not applicable"
    assert run_check(receipt(), receipt()).status == "Not applicable"


def test_receipt_with_invoice_is_incomplete():
    assert run_check(receipt(), inv()).status == "Incomplete"


def test_reason_has_no_invoice_number():
    run_check(inv(), po())
    r = run_check(inv(), po())
    assert "INV" not in r.reason
