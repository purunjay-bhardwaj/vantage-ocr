import json

import pytest
from openai import APIConnectionError

from app.extract import llm
from app.extract.llm import call_llm, parse_llm_reply

GOOD = {
    "document_type": "supplier_invoice",
    "fields": {"supplier_name": "<PERSON_1>", "invoice_number": "INV-1",
               "invoice_date": "2026-05-21", "po_number": "PO-7000",
               "tax_amount": 10.5, "total_amount": 110.5},
}


def test_plain_json():
    out = parse_llm_reply(json.dumps(GOOD))
    assert out.fields.total_amount == 110.5
    assert out.fields.supplier_name == "<PERSON_1>"


@pytest.mark.parametrize("wrap", ["```json\n{}\n```", "```\n{}\n```", "```JSON {} ```"])
def test_fences_stripped(wrap):
    out = parse_llm_reply(wrap.replace("{}", json.dumps(GOOD)))
    assert out.document_type == "supplier_invoice"


@pytest.mark.parametrize("raw_type", ["Supplier Invoice", "supplier-invoice", " SUPPLIER_INVOICE "])
def test_doc_type_normalized(raw_type):
    out = parse_llm_reply(json.dumps({**GOOD, "document_type": raw_type}))
    assert out.document_type == "supplier_invoice"


def test_amount_strings_parsed():
    d = json.loads(json.dumps(GOOD))
    d["fields"]["total_amount"] = "₹35,400.00"
    d["fields"]["tax_amount"] = "Rs. 1,200"
    out = parse_llm_reply(json.dumps(d))
    assert out.fields.total_amount == 35400.0
    assert out.fields.tax_amount == 1200.0


@pytest.mark.parametrize("raw", ["not json", "[]", "{}", json.dumps({**GOOD, "document_type": "bank_statement"})])
def test_invalid_rejected(raw):
    with pytest.raises(ValueError, match="schema_invalid"):
        parse_llm_reply(raw)


class _FakeCompletions:
    def __init__(self, reply=None, exc=None):
        self.reply, self.exc, self.calls = reply, exc, []

    def create(self, **kw):
        self.calls.append(kw)
        if self.exc:
            raise self.exc

        class M:  # minimal response shape
            pass
        msg = M(); msg.content = self.reply
        ch = M(); ch.message = msg
        resp = M(); resp.choices = [ch]
        return resp


def _client(completions):
    class C:
        pass
    c = C(); c.chat = C(); c.chat.completions = completions
    return c


def test_call_llm_sends_temperature_zero(monkeypatch):
    comp = _FakeCompletions(reply=json.dumps(GOOD))
    monkeypatch.setattr(llm, "_get_client", lambda: _client(comp))
    call_llm("masked text")
    assert comp.calls[0]["temperature"] == 0
    assert comp.calls[0]["messages"][1]["content"] == "masked text"


def test_call_llm_network_error(monkeypatch):
    import httpx
    exc = APIConnectionError(request=httpx.Request("POST", "http://x"))
    monkeypatch.setattr(llm, "_get_client", lambda: _client(_FakeCompletions(exc=exc)))
    with pytest.raises(ValueError, match="llm_unavailable"):
        call_llm("x")
