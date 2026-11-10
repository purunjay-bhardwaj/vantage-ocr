"""
End-to-end tests of POST /v1/extract with OCR, masker and LLM replaced by
deterministic fakes. They check the security properties the plan promises:
masked text only reaches the LLM, the vault is cleared, uploads are deleted,
and no PII reaches logs.

Fake document format (bytes after the %PDF header):
    TYPE=<doc_type>;INV=<number>;TOTAL=<amount>;<free text with PII>
"""
from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.extract.models import LLMOutput, VantageFields
from app.ocr.reader import OcrResult
from tests.conftest import PII_BANK, PII_NAME, PII_PHONE, fake_mask_text


def doc(doc_type: str, total: float | None, inv: str = "", extra: str = "") -> bytes:
    t = "" if total is None else str(total)
    return f"%PDF-1.4\nTYPE={doc_type};INV={inv};TOTAL={t};{extra}".encode()


def fake_ocr(file_bytes: bytes, mime: str) -> OcrResult:
    text = file_bytes.split(b"\n", 1)[1].decode()
    return OcrResult(text=text, mean_confidence=95.0, page_count=1, used_fallback=False)


class FakeLLM:
    def __init__(self):
        self.seen: list[str] = []
        self.fail: str | None = None

    def __call__(self, masked_text: str) -> LLMOutput:
        self.seen.append(masked_text)
        if self.fail:
            raise ValueError(self.fail)
        kv = dict(re.findall(r"(TYPE|INV|TOTAL)=([^;]*)", masked_text))
        # Echo any person placeholder as supplier name, and a bank token into po_number
        person = re.search(r"<PERSON_\d+>", masked_text)
        bank = re.search(r"<BANK_\d+>", masked_text)
        return LLMOutput(
            document_type=kv["TYPE"],
            fields=VantageFields(
                supplier_name=person.group(0) if person else None,
                invoice_number=kv.get("INV") or None,
                po_number=bank.group(0) if bank else None,
                total_amount=float(kv["TOTAL"]) if kv.get("TOTAL") else None,
            ),
        )


@pytest.fixture
def api(monkeypatch, tmp_path):
    vaults: list[dict] = []

    def tracking_mask(text):
        r = fake_mask_text(text)
        vaults.append(r.vault)
        return r

    fake_llm = FakeLLM()
    monkeypatch.setattr(main, "ocr_file", fake_ocr)
    monkeypatch.setattr(main, "mask_text", tracking_mask)
    monkeypatch.setattr(main, "call_llm", fake_llm)
    monkeypatch.setattr(main, "_UPLOAD_DIR", tmp_path / "uploads")
    with TestClient(main.app) as client:
        yield client, fake_llm, vaults, tmp_path / "uploads"


def post(client, d1: bytes, d2: bytes | None = None, name1="Ravi_Menon_invoice.pdf"):
    files = {"file1": (name1, d1, "application/pdf")}
    if d2 is not None:
        files["file2"] = ("po.pdf", d2, "application/pdf")
    return client.post("/v1/extract", files=files)


PII_TEXT = f"Contact {PII_NAME} {PII_PHONE} Bank A/C {PII_BANK}"


def test_health(api):
    client, *_ = api
    assert client.get("/health").json() == {"status": "ok"}


def test_approve_then_duplicate(api):
    client, *_ = api
    r = post(client, doc("supplier_invoice", 1000.0, "INV-20000"), doc("purchase_order", 1000.0))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["check"]["status"] == "Approve"
    assert body["document_type"] == "supplier_invoice"
    assert set(body["pipeline"]["timings_ms"]) == {"ocr", "pii", "llm", "rule"}

    r2 = post(client, doc("supplier_invoice", 1000.0, "INV 20000"), doc("purchase_order", 1000.0))
    assert r2.json()["check"]["status"] == "Duplicate"


def test_po_first_still_reports_invoice_fields(api):
    client, *_ = api
    r = post(client, doc("purchase_order", 5.0), doc("supplier_invoice", 5.0, "INV-9"))
    assert r.json()["document_type"] == "supplier_invoice"
    assert r.json()["fields"]["invoice_number"] == "INV-9"


@pytest.mark.parametrize("d1,d2,status", [
    (doc("supplier_invoice", 1000.0, "INV-1"), doc("purchase_order", 1001.0), "Hold"),
    (doc("supplier_invoice", 1000.0, "INV-2"), None, "Incomplete"),
    (doc("payment_receipt", 500.0), None, "Not applicable"),
])
def test_statuses(api, d1, d2, status):
    client, *_ = api
    assert post(client, d1, d2).json()["check"]["status"] == status


def test_pii_never_reaches_llm_and_vault_cleared(api, capsys):
    client, fake_llm, vaults, _ = api
    r = post(client, doc("supplier_invoice", 10.0, "INV-5", PII_TEXT), doc("purchase_order", 10.0))
    assert r.status_code == 200
    for sent in fake_llm.seen:
        assert PII_NAME not in sent and PII_BANK not in sent and PII_PHONE not in sent
    assert "<PERSON_1>" in fake_llm.seen[0]
    assert all(v == {} for v in vaults), "vault must be cleared at request end"

    body = r.json()
    assert body["fields"]["supplier_name"] == PII_NAME          # restored for display
    assert body["fields"]["po_number"] is None                   # bank token dropped, never restored
    assert PII_BANK not in r.text
    assert body["pii"]["masked_before_llm"] is True
    assert body["pii"]["entity_counts"]["BANK_ACCOUNT"] == 1

    logs = capsys.readouterr().out
    for secret in (PII_NAME, PII_BANK, PII_PHONE, "Ravi_Menon_invoice.pdf", "INV-5"):
        assert secret not in logs


def test_uploads_deleted_on_success_and_failure(api):
    client, fake_llm, _, upload_dir = api
    post(client, doc("supplier_invoice", 1.0, "INV-6"), doc("purchase_order", 1.0))
    assert list(upload_dir.glob("*")) == []
    fake_llm.fail = "schema_invalid"
    post(client, doc("supplier_invoice", 1.0, "INV-7"))
    assert list(upload_dir.glob("*")) == []


def test_llm_schema_error_is_422(api):
    client, fake_llm, vaults, _ = api
    fake_llm.fail = "schema_invalid"
    r = post(client, doc("supplier_invoice", 1.0, "INV-8", PII_TEXT))
    assert r.status_code == 422
    assert r.json()["detail"] == "Could not read this document."
    assert all(v == {} for v in vaults), "vault cleared even when the LLM fails"


def test_llm_unavailable_is_502(api):
    client, fake_llm, *_ = api
    fake_llm.fail = "llm_unavailable"
    assert post(client, doc("supplier_invoice", 1.0, "INV-9")).status_code == 502


def test_bad_magic_bytes_400(api):
    client, *_ = api
    r = client.post("/v1/extract", files={"file1": ("x.pdf", b"hello", "application/pdf")})
    assert r.status_code == 400


def test_too_large_413(api, monkeypatch):
    client, *_ = api
    monkeypatch.setattr(main.settings, "max_upload_bytes", 100)
    r = client.post("/v1/extract", files={"file1": ("x.pdf", b"%PDF" + b"0" * 200, "application/pdf")})
    assert r.status_code == 413


def test_empty_ocr_422(api, monkeypatch):
    client, *_ = api
    monkeypatch.setattr(main, "ocr_file",
                        lambda b, m: OcrResult(text="  ", mean_confidence=None, page_count=1, used_fallback=True))
    assert post(client, doc("supplier_invoice", 1.0)).status_code == 422


def test_unexpected_error_is_generic_500(api, monkeypatch):
    client, *_ = api

    def boom(b, m):
        raise RuntimeError(f"tesseract choked on {PII_NAME}")
    monkeypatch.setattr(main, "ocr_file", boom)
    r = post(client, doc("supplier_invoice", 1.0))
    assert r.status_code == 500
    assert PII_NAME not in r.text


def test_cors_restricted(api):
    client, *_ = api
    ok = client.options("/v1/extract", headers={"Origin": "http://localhost:8501",
                                                "Access-Control-Request-Method": "POST"})
    bad = client.options("/v1/extract", headers={"Origin": "http://evil.example",
                                                 "Access-Control-Request-Method": "POST"})
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:8501"
    assert "access-control-allow-origin" not in bad.headers


def test_four_spans_without_pii(api, _spans):
    client, *_ = api
    post(client, doc("supplier_invoice", 10.0, "INV-55", PII_TEXT), doc("purchase_order", 10.0))
    spans = _spans.get_finished_spans()
    names = [s.name for s in spans]
    assert names.count("ocr") == 2 and names.count("pii") == 2 and names.count("llm") == 2
    assert names.count("rule") == 1
    dump = repr([dict(s.attributes) for s in spans])
    for secret in (PII_NAME, PII_BANK, PII_PHONE, "INV-55", "Ravi_Menon_invoice.pdf"):
        assert secret not in dump
