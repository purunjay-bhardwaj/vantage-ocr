"""
Score the running API against data/test_sheet.csv and the sample pairs.

Usage (API must be running on :8000 with a valid OPENAI_API_KEY):
    python -m scripts.evaluate                 # full run
    python -m scripts.evaluate --skip-fields   # only the status run

Phase 1 – field + document-type accuracy: each test-sheet file is sent alone.
          (A lone invoice is Incomplete and is not recorded, so this does not
          pollute the duplicate store.)
Phase 2 – status accuracy: every pair in data/samples is sent in the order a
          clerk would submit them, after resetting the duplicate store.

Writes data/eval_report.json (field values are not included — only match flags).
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.check.normalize import normalize_invoice_number  # noqa: E402
from app.check.store import reset_store  # noqa: E402

SAMPLES = ROOT / "data" / "samples"
SHEET = ROOT / "data" / "test_sheet.csv"
REPORT = ROOT / "data" / "eval_report.json"

FIELDS = ["supplier_name", "invoice_number", "invoice_date", "po_number", "tax_amount", "total_amount"]

# (file1, file2 or None, expected status) – order matters for duplicates
PAIRS: list[tuple[str, str | None, str]] = (
    [(f"invoice_{i:03d}_approve.pdf", f"po_{i:03d}_approve.pdf", "Approve") for i in range(6)]
    + [(f"invoice_{i:03d}_hold_1rs.pdf", f"po_{i:03d}_hold_1rs.pdf", "Hold") for i in range(6, 9)]
    + [(f"invoice_{i:03d}_hold_large.pdf", f"po_{i:03d}_hold_large.pdf", "Hold") for i in range(9, 12)]
    + [p for i in (12, 13) for p in (
        (f"invoice_{i:03d}_dup_first.pdf", f"po_{i:03d}_dup.pdf", "Approve"),
        (f"invoice_{i:03d}_dup_second.pdf", f"po_{i:03d}_dup.pdf", "Duplicate"),
    )]
    + [(f"invoice_{i:03d}_bankfooter.pdf", f"po_{i:03d}_bankfooter.pdf", "Approve") for i in range(14, 17)]
    + [("receipt_017.pdf", None, "Not applicable"), ("receipt_018.pdf", None, "Not applicable")]
    + [("invoice_019_extra.pdf", "po_019_extra.pdf", "Approve")]
    + [("invoice_019_extra.pdf", None, "Duplicate")]       # resubmitted alone → still Duplicate
    + [("po_000_approve.pdf", None, "Incomplete")]
)


def _blank(v):
    return None if v in (None, "", "—") else v


def _norm_text(v):
    return None if v is None else " ".join(str(v).lower().split())


def field_match(name: str, expected, got) -> bool:
    expected, got = _blank(expected), _blank(got)
    if expected is None or got is None:
        return expected is None and got is None
    if name in ("tax_amount", "total_amount"):
        return abs(float(expected) - float(got)) < 0.01
    if name in ("invoice_number", "po_number"):
        return normalize_invoice_number(str(expected)) == normalize_invoice_number(str(got))
    return _norm_text(expected) == _norm_text(got)


def send(client: httpx.Client, url: str, f1: str, f2: str | None) -> dict:
    files = {"file1": (f1, (SAMPLES / f1).read_bytes(), "application/pdf")}
    if f2:
        files["file2"] = (f2, (SAMPLES / f2).read_bytes(), "application/pdf")
    r = client.post(url, files=files)
    if r.status_code != 200:
        return {"_error": r.status_code}
    return r.json()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api-url", default="http://localhost:8000/v1/extract")
    ap.add_argument("--skip-fields", action="store_true")
    args = ap.parse_args()

    report: dict = {"fields": {}, "doc_type": {}, "status": []}
    with httpx.Client(timeout=120.0) as client:
        # ── Phase 1 ────────────────────────────────────────────────────────────
        if not args.skip_fields:
            reset_store()
            rows = list(csv.DictReader(SHEET.open(encoding="utf-8")))
            hits = {f: 0 for f in FIELDS}
            dt_hits = 0
            for row in rows:
                body = send(client, args.api_url, row["file"], None)
                if "_error" in body:
                    print(f"  ! {row['file']}: HTTP {body['_error']}")
                    continue
                dt_ok = body["document_type"] == row["doc_type"]
                dt_hits += dt_ok
                misses = []
                for f in FIELDS:
                    ok = field_match(f, row[f], body["fields"].get(f))
                    hits[f] += ok
                    if not ok:
                        misses.append(f)
                print(f"  {'✓' if dt_ok and not misses else '✗'} {row['file']:<32} "
                      f"type={'ok' if dt_ok else 'WRONG'} misses={misses or '-'}")
            n = len(rows)
            total_hits = sum(hits.values())
            report["fields"] = {f: round(hits[f] / n, 3) for f in FIELDS}
            report["fields"]["overall"] = round(total_hits / (n * len(FIELDS)), 3)
            report["doc_type"] = {"accuracy": round(dt_hits / n, 3), "n": n}

        # ── Phase 2 ────────────────────────────────────────────────────────────
        reset_store()
        ok_count = 0
        for f1, f2, expected in PAIRS:
            body = send(client, args.api_url, f1, f2)
            got = body.get("check", {}).get("status", f"HTTP {body.get('_error')}")
            ok = got == expected
            ok_count += ok
            report["status"].append({"file1": f1, "file2": f2, "expected": expected, "got": got, "ok": ok})
            print(f"  {'✓' if ok else '✗'} {f1:<32} + {str(f2):<26} expected={expected:<15} got={got}")
        report["status_accuracy"] = round(ok_count / len(PAIRS), 3)
        reset_store()  # leave the demo store clean

    print("\n── Summary ──")
    if report["fields"]:
        print(f"Field match (overall): {report['fields']['overall']:.1%}  (target ≥ 90%)")
        print(f"Document-type accuracy: {report['doc_type']['accuracy']:.1%}  (target ≥ 95%)")
    print(f"Rule/status accuracy:  {report['status_accuracy']:.1%}  (target 100%)")
    REPORT.write_text(json.dumps(report, indent=2))
    print(f"Report written to {REPORT.relative_to(ROOT)}")
    return 0 if report["status_accuracy"] == 1.0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
