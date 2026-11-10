import sqlite3

from app.check.store import is_duplicate, record_invoice, reset_store


def test_record_then_duplicate():
    assert not is_duplicate("INV1")
    assert record_invoice("INV1") is True
    assert is_duplicate("INV1")


def test_second_record_reports_conflict():
    assert record_invoice("INV2") is True
    assert record_invoice("INV2") is False


def test_reset():
    record_invoice("INV3")
    reset_store()
    assert not is_duplicate("INV3")


def test_schema_holds_no_pii(temp_store):
    record_invoice("INV4")
    con = sqlite3.connect(temp_store)
    cols = [r[1] for r in con.execute("PRAGMA table_info(seen_invoices)")]
    con.close()
    assert cols == ["norm_number", "seen_at"]


def test_blank_db_path_falls_back_to_default(monkeypatch):
    from app.check import store
    from app.config import settings
    monkeypatch.setattr(settings, "invoice_db_path", "  ")
    assert store._db_path() == store._DEFAULT
