# Vantage Retail · OCR Connector

**Team Omega · Build Fast with AI · Week 2**

Supplier invoice checker for Vantage Retail's accounts payable team.
Classifies scanned documents (invoice / PO / receipt), extracts six structured fields, masks PII before any network call, and applies one business rule: _do totals match, and have we seen this invoice before?_

---

## Quick start

### Prerequisites

| Tool | Version |
|------|---------|
| Python | 3.11+ |
| Tesseract OCR | 5.x (`sudo apt install tesseract-ocr`) |
| Poppler | any (`sudo apt install poppler-utils`) |

```bash
# 1. Clone and enter
git clone https://github.com/<your-org>/vantage-ocr.git
cd vantage-ocr

# 2. Install Python dependencies
pip install -r requirements.txt

# 3. Download the spaCy English model (required by Presidio)
python -m spacy download en_core_web_lg

# 4. Set your API key
cp .env.example .env
# Edit .env and add your OPENAI_API_KEY (any OpenAI-compatible endpoint works)

# 5. Generate synthetic samples (optional – already committed)
python scripts/generate_samples.py

# 6. Start the API server
uvicorn app.main:app --reload

# 7. Start the Streamlit UI (new terminal)
streamlit run streamlit_app.py
```

Open **http://localhost:8501** in your browser.

---

## API

```
POST /v1/extract
Content-Type: multipart/form-data

file1  (required) — PDF, PNG, or JPEG
file2  (optional) — paired document for pair check
```

### Response

```json
{
  "request_id": "7c1e0a4e-...",
  "document_type": "supplier_invoice",
  "fields": {
    "supplier_name": "Northwind Stationery Pvt Ltd",
    "invoice_number": "INV-20411",
    "invoice_date": "2026-03-03",
    "po_number": "PO-7781",
    "tax_amount": 5400.0,
    "total_amount": 35400.0
  },
  "check": {
    "status": "Approve",
    "reason": "Invoice total equals purchase-order total."
  },
  "pii": {
    "masked_before_llm": true,
    "entity_counts": { "PERSON": 2, "PHONE_NUMBER": 1, "BANK_ACCOUNT": 1 }
  },
  "pipeline": {
    "ocr_engine": "tesseract",
    "used_vision_fallback": false,
    "timings_ms": { "ocr": 640, "pii": 38, "llm": 1102, "rule": 3 }
  }
}
```

---

## Invoice-number normalization rule

**Rule:** Strip leading/trailing whitespace → remove all spaces and hyphens → uppercase.

| Raw | Normalized |
|-----|-----------|
| `INV-20411` | `INV20411` |
| `inv 204 11` | `INV20411` |
| `INV 204-11` | `INV20411` |

The same rule is applied at both storage time and lookup time, so `INV-20411` and `INV 204-11` correctly resolve to the same duplicate.

---

## Status logic

| Status | When |
|--------|------|
| **Duplicate** | Normalized invoice number already in the local SQLite store. Wins over all other statuses. |
| **Approve** | Totals match to the paisa (2 decimal places) and invoice is new. |
| **Hold** | Totals differ by any amount and invoice is new. Even a 1-paisa gap is a Hold. |
| **Incomplete** | Invoice or purchase order is missing from the uploaded files. |
| **Not applicable** | The only file uploaded is a payment receipt. |

### Total comparison

Both totals are rounded to 2 decimal places before comparison. `35400.00` and `35400` match. A gap of ₹0.01 is a Hold.

---

## When a page prints two totals

Some invoice layouts print a _subtotal_ (before tax) and a _grand total_ (after tax). This pipeline extracts **`total_amount` as the grand total** — the largest, final amount due — which is what the PO order total should also reflect. Tax is extracted separately in `tax_amount` and displayed, but the core Approve/Hold check uses only `total_amount`.

---

## PII masking design

All five steps run in this order: **upload → OCR (local) → Presidio mask (local) → LLM call (masked text only) → restore for display**.

The dangerous moment is the network call. Personal data never leaves your machine.

1. **Presidio** detects: `PERSON`, `PHONE_NUMBER`, `EMAIL_ADDRESS`, `BANK_ACCOUNT`, `IFSC`, `AADHAAR`, `PAN`, and more. See `app/pii/recognizers.py` for custom Indian-context recognizers.
2. Each distinct value gets a **stable placeholder** (`<PERSON_1>`, `<BANK_1>`, …) for the life of one request. Values are normalized (lowercased + whitespace collapsed) before token assignment, so `"RAVI MENON"` and `"ravi menon"` get the same token.
3. The **vault** (token → real value) is held in memory only, never written to disk or logs.
4. The LLM prompt tells the model to copy placeholders unchanged and return JSON only.
5. Real values are **restored after the model call**, inside your process, for display only.
6. The vault is cleared when the request ends.

Bank account numbers are masked and dropped — the model is never asked to echo one. A trace that contains a name fails the masking criterion.

---

## Telemetry

Four spans: **ocr**, **pii**, **llm**, **rule**.

The console exporter prints one JSON-lines entry per stage. To use Jaeger, set `OTEL_EXPORTER_OTLP_ENDPOINT` in `.env`.

**What is logged:**

| Logged ✅ | Never logged ❌ |
|-----------|----------------|
| `request_id`, stage, duration | OCR text or prompt |
| OCR engine, char count, fallback flag | Field values (names, accounts) |
| Entity counts by type | Placeholder vault |
| Model name, prompt version | Original filenames |
| Check status label (`duplicate=true`) | Invoice numbers as metric labels |

---

## Accuracy (20-document test sheet)

See `data/test_sheet.csv` for ground truth. Expected accuracy numbers after running against the synthetic set:

| Metric | Target |
|--------|--------|
| Field match (after normalization) | ≥ 90% |
| Document-type accuracy | ≥ 95% |
| Rule accuracy | 100% (deterministic given correct fields) |

---

## Project structure

```
vantage-ocr/
├── app/
│   ├── main.py              # FastAPI app + pipeline orchestration
│   ├── config.py            # Settings (env vars)
│   ├── ocr/
│   │   ├── upload.py        # Magic-byte validation, random storage names
│   │   └── reader.py        # Tesseract OCR, fallback logic
│   ├── pii/
│   │   ├── masker.py        # Presidio masking, stable placeholders, vault
│   │   └── recognizers.py   # Custom Indian-context recognizers
│   ├── extract/
│   │   ├── models.py        # Pydantic schemas
│   │   └── llm.py           # One LLM call, JSON parse, schema validation
│   ├── check/
│   │   ├── normalize.py     # Invoice-number normalization rule
│   │   ├── store.py         # SQLite duplicate store
│   │   └── rules.py         # Business rule (Approve/Hold/Duplicate/…)
│   └── telemetry/
│       └── otel.py          # OpenTelemetry setup, safe_log
├── streamlit_app.py         # Streamlit UI
├── scripts/
│   └── generate_samples.py  # Synthetic document generator
├── data/
│   ├── samples/             # Generated PDFs (38 files)
│   └── test_sheet.csv       # 20-document test sheet
├── .env.example
└── requirements.txt
```

---

## Demo script

1. **Approve** — upload `invoice_000_approve.pdf` + `po_000_approve.pdf`. Totals match → ✅ Approve.
2. **Hold** — upload `invoice_006_hold_1rs.pdf` + `po_006_hold_1rs.pdf`. 1-rupee gap → 🟡 Hold.
3. **Duplicate** — run Approve again with the same invoice. Second run → 🔴 Duplicate.
4. **Bank account masking** — upload `invoice_012_bankfooter.pdf`. Bank account on footer is absent from the JSON response and absent from all trace lines.

The trace panel in the UI shows four stage durations, entity counts, and masked_before_llm=true.

---

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENAI_API_KEY` | — | **Required.** Any OpenAI-compatible key. |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | Override for Together/Groq/local. |
| `OPENAI_MODEL` | `gpt-4o-mini` | Model name. |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | _(console)_ | Jaeger OTLP endpoint. |
| `MAX_UPLOAD_BYTES` | `10485760` | 10 MB cap on uploads. |

The API key is read from the environment at request time. Never commit `.env`.

---

## Stretch goal (tax line-item check)

Not yet implemented. The core check ships first. The stretch goal adds a line-item table extraction step and compares the sum of line-item taxes against the printed `tax_amount`. If they differ by more than ₹1, a warning is appended to `check.reason` without changing the status.
