"""
Generate synthetic supplier invoices, purchase orders, and payment receipts.
Run: python scripts/generate_samples.py

Outputs:
  data/samples/   — PDF files (30–50 documents)
  data/test_sheet.csv  — 20-document test sheet
"""
from __future__ import annotations

import csv
import os
import random
import sys
from datetime import date, timedelta
from pathlib import Path

# ---- ReportLab ---------------------------------------------------------------
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from reportlab.lib import colors

SAMPLES_DIR = Path(__file__).resolve().parent.parent / "data" / "samples"
TEST_SHEET = Path(__file__).resolve().parent.parent / "data" / "test_sheet.csv"
SAMPLES_DIR.mkdir(parents=True, exist_ok=True)

random.seed(42)

# ─── Fake data pools ──────────────────────────────────────────────────────────
SUPPLIERS = [
    "Northwind Stationery Pvt Ltd",
    "Lakshmi Office Supplies",
    "Akash Paper Mart",
    "Bharat Packaging Co",
    "Sunrise Logistics",
    "Delta Freight Solutions",
    "Horizon Electronics",
    "Kumar & Sons Hardware",
    "Sai Enterprises",
    "Metro Cleaners",
    "Regal Printers",
    "Swift Courier Services",
    "Eastern Textiles",
    "Prestige Furniture",
    "National Rubber Co",
]

BANK_ACCOUNTS = [
    ("50200012345678", "HDFC0001234"),
    ("911010012345678", "UTIB0002567"),
    ("1234567890", "SBIN0003001"),
    ("9876543210123", "ICIC0004789"),
]

CONTACT_NAMES = [
    "Ravi Menon", "Priya Sharma", "Arun Kumar", "Deepa Nair", "Suresh Patel",
]

CONTACT_PHONES = [
    "+91 98765 43210", "+91 87654 32109", "+91 76543 21098",
]


def _rand_date() -> str:
    start = date(2026, 1, 1)
    d = start + timedelta(days=random.randint(0, 300))
    return d.isoformat()


def _inv_number(i: int) -> str:
    return f"INV-{20000 + i:05d}"


def _po_number(i: int) -> str:
    return f"PO-{7000 + i:04d}"


def _tax(base: float) -> float:
    return round(base * 0.18, 2)


def _total(base: float, tax: float) -> float:
    return round(base + tax, 2)


STYLES = getSampleStyleSheet()


def _make_invoice_pdf(
    path: Path,
    supplier: str,
    inv_num: str,
    inv_date: str,
    po_num: str,
    base_amount: float,
    tax: float,
    total: float,
    include_bank: bool = True,
    contact_name: str | None = None,
    contact_phone: str | None = None,
) -> None:
    doc = SimpleDocTemplate(str(path), pagesize=A4)
    story = []

    story.append(Paragraph("<b>TAX INVOICE</b>", STYLES["Title"]))
    story.append(Spacer(1, 0.3 * cm))

    if contact_name:
        story.append(Paragraph(f"Contact: {contact_name}", STYLES["Normal"]))
    if contact_phone:
        story.append(Paragraph(f"Phone: {contact_phone}", STYLES["Normal"]))

    story.append(Paragraph(f"<b>Supplier:</b> {supplier}", STYLES["Normal"]))
    story.append(Paragraph(f"<b>Invoice Number:</b> {inv_num}", STYLES["Normal"]))
    story.append(Paragraph(f"<b>Invoice Date:</b> {inv_date}", STYLES["Normal"]))
    story.append(Paragraph(f"<b>PO Reference:</b> {po_num}", STYLES["Normal"]))
    story.append(Spacer(1, 0.5 * cm))

    table_data = [
        ["Description", "Amount (₹)"],
        ["Goods / Services supplied", f"{base_amount:,.2f}"],
        ["GST (18%)", f"{tax:,.2f}"],
        ["Total", f"{total:,.2f}"],
    ]
    t = Table(table_data, colWidths=[10 * cm, 5 * cm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2C3E50")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
    ]))
    story.append(t)

    if include_bank:
        bank_acc, ifsc = random.choice(BANK_ACCOUNTS)
        story.append(Spacer(1, 1 * cm))
        story.append(Paragraph("─" * 80, STYLES["Normal"]))
        story.append(Paragraph(
            f"Bank Transfer Details: A/C No: {bank_acc} | IFSC: {ifsc} | "
            "Please use the invoice number as the payment reference.",
            STYLES["Normal"],
        ))

    doc.build(story)


def _make_po_pdf(
    path: Path,
    supplier: str,
    po_num: str,
    po_date: str,
    order_total: float,
) -> None:
    doc = SimpleDocTemplate(str(path), pagesize=A4)
    story = []
    story.append(Paragraph("<b>PURCHASE ORDER</b>", STYLES["Title"]))
    story.append(Spacer(1, 0.3 * cm))
    story.append(Paragraph(f"<b>PO Number:</b> {po_num}", STYLES["Normal"]))
    story.append(Paragraph(f"<b>Supplier:</b> {supplier}", STYLES["Normal"]))
    story.append(Paragraph(f"<b>Date:</b> {po_date}", STYLES["Normal"]))
    story.append(Spacer(1, 0.5 * cm))

    table_data = [
        ["Description", "Order Total (₹)"],
        ["Per purchase agreement", f"{order_total:,.2f}"],
    ]
    t = Table(table_data, colWidths=[10 * cm, 5 * cm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1A5276")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
    ]))
    story.append(t)
    doc.build(story)


def _make_receipt_pdf(
    path: Path,
    supplier: str,
    amount: float,
    receipt_date: str,
) -> None:
    doc = SimpleDocTemplate(str(path), pagesize=A4)
    story = []
    story.append(Paragraph("<b>PAYMENT RECEIPT</b>", STYLES["Title"]))
    story.append(Spacer(1, 0.3 * cm))
    story.append(Paragraph(f"<b>Paid to:</b> {supplier}", STYLES["Normal"]))
    story.append(Paragraph(f"<b>Amount (₹):</b> {amount:,.2f}", STYLES["Normal"]))
    story.append(Paragraph(f"<b>Date:</b> {receipt_date}", STYLES["Normal"]))
    story.append(Paragraph("Transfer successful. This receipt is for records only.", STYLES["Normal"]))
    doc.build(story)


# ─── Test sheet ───────────────────────────────────────────────────────────────

def main() -> None:
    records = []  # for test sheet

    i = 0  # invoice counter

    # ── 1. Exact-match pairs (Approve) × 6 ───────────────────────────────────
    for _ in range(6):
        supplier = random.choice(SUPPLIERS)
        base = round(random.uniform(5000, 80000), 2)
        tax = _tax(base)
        total = _total(base, tax)
        inv = _inv_number(i)
        po = _po_number(i)
        d = _rand_date()

        inv_path = SAMPLES_DIR / f"invoice_{i:03d}_approve.pdf"
        po_path = SAMPLES_DIR / f"po_{i:03d}_approve.pdf"
        _make_invoice_pdf(inv_path, supplier, inv, d, po, base, tax, total,
                          contact_name=random.choice(CONTACT_NAMES),
                          contact_phone=random.choice(CONTACT_PHONES))
        _make_po_pdf(po_path, supplier, po, d, total)

        records.append({
            "file": inv_path.name, "doc_type": "supplier_invoice",
            "supplier_name": supplier, "invoice_number": inv,
            "invoice_date": d, "po_number": po,
            "tax_amount": tax, "total_amount": total,
            "expected_status": "Approve",
        })
        records.append({
            "file": po_path.name, "doc_type": "purchase_order",
            "supplier_name": supplier, "invoice_number": None,
            "invoice_date": None, "po_number": po,
            "tax_amount": None, "total_amount": total,
            "expected_status": "—",
        })
        i += 1

    # ── 2. Off-by-1-rupee pairs (Hold) × 3 ───────────────────────────────────
    for _ in range(3):
        supplier = random.choice(SUPPLIERS)
        base = round(random.uniform(5000, 50000), 2)
        tax = _tax(base)
        total = _total(base, tax)
        inv = _inv_number(i)
        po = _po_number(i)
        d = _rand_date()

        inv_path = SAMPLES_DIR / f"invoice_{i:03d}_hold_1rs.pdf"
        po_path = SAMPLES_DIR / f"po_{i:03d}_hold_1rs.pdf"
        _make_invoice_pdf(inv_path, supplier, inv, d, po, base, tax, total)
        _make_po_pdf(po_path, supplier, po, d, total + 1.0)  # 1 rupee gap

        records.append({
            "file": inv_path.name, "doc_type": "supplier_invoice",
            "supplier_name": supplier, "invoice_number": inv,
            "invoice_date": d, "po_number": po,
            "tax_amount": tax, "total_amount": total,
            "expected_status": "Hold",
        })
        i += 1

    # ── 3. Large-discrepancy pairs (Hold) × 3 ────────────────────────────────
    for _ in range(3):
        supplier = random.choice(SUPPLIERS)
        base = round(random.uniform(10000, 100000), 2)
        tax = _tax(base)
        total = _total(base, tax)
        po_total = total + random.choice([500, 1000, 2500, 5000])
        inv = _inv_number(i)
        po = _po_number(i)
        d = _rand_date()

        inv_path = SAMPLES_DIR / f"invoice_{i:03d}_hold_large.pdf"
        po_path = SAMPLES_DIR / f"po_{i:03d}_hold_large.pdf"
        _make_invoice_pdf(inv_path, supplier, inv, d, po, base, tax, total)
        _make_po_pdf(po_path, supplier, po, d, po_total)

        records.append({
            "file": inv_path.name, "doc_type": "supplier_invoice",
            "supplier_name": supplier, "invoice_number": inv,
            "invoice_date": d, "po_number": po,
            "tax_amount": tax, "total_amount": total,
            "expected_status": "Hold",
        })
        i += 1

    # ── 4. Duplicate invoice (submit same INV number twice) × 2 ──────────────
    for dup_idx in range(2):
        supplier = random.choice(SUPPLIERS)
        base = round(random.uniform(8000, 60000), 2)
        tax = _tax(base)
        total = _total(base, tax)
        inv = _inv_number(i)
        po = _po_number(i)
        d = _rand_date()

        # First submission
        inv_path_a = SAMPLES_DIR / f"invoice_{i:03d}_dup_first.pdf"
        _make_invoice_pdf(inv_path_a, supplier, inv, d, po, base, tax, total)

        # Second submission (same invoice number, slightly different date formatting)
        inv_path_b = SAMPLES_DIR / f"invoice_{i:03d}_dup_second.pdf"
        alt_inv = inv.replace("-", " ")  # "INV 20xxx" – normalizes to same
        _make_invoice_pdf(inv_path_b, supplier, alt_inv, d, po, base, tax, total)

        # Matching PO so both submissions are full pairs (first → Approve, second → Duplicate).
        # Not added to `records`, so the 20-row test sheet is unchanged.
        _make_po_pdf(SAMPLES_DIR / f"po_{i:03d}_dup.pdf", supplier, po, d, total)

        records.append({
            "file": inv_path_a.name, "doc_type": "supplier_invoice",
            "supplier_name": supplier, "invoice_number": inv,
            "invoice_date": d, "po_number": po,
            "tax_amount": tax, "total_amount": total,
            "expected_status": "Approve (first seen)",
        })
        records.append({
            "file": inv_path_b.name, "doc_type": "supplier_invoice",
            "supplier_name": supplier, "invoice_number": alt_inv,
            "invoice_date": d, "po_number": po,
            "tax_amount": tax, "total_amount": total,
            "expected_status": "Duplicate",
        })
        i += 1

    # ── 5. Invoice with bank account on footer (PII masking proof) × 3 ───────
    for _ in range(3):
        supplier = random.choice(SUPPLIERS)
        base = round(random.uniform(5000, 40000), 2)
        tax = _tax(base)
        total = _total(base, tax)
        inv = _inv_number(i)
        po = _po_number(i)
        d = _rand_date()

        inv_path = SAMPLES_DIR / f"invoice_{i:03d}_bankfooter.pdf"
        _make_invoice_pdf(inv_path, supplier, inv, d, po, base, tax, total,
                          include_bank=True,
                          contact_name=random.choice(CONTACT_NAMES),
                          contact_phone=random.choice(CONTACT_PHONES))
        po_path = SAMPLES_DIR / f"po_{i:03d}_bankfooter.pdf"
        _make_po_pdf(po_path, supplier, po, d, total)

        records.append({
            "file": inv_path.name, "doc_type": "supplier_invoice",
            "supplier_name": supplier, "invoice_number": inv,
            "invoice_date": d, "po_number": po,
            "tax_amount": tax, "total_amount": total,
            "expected_status": "Approve",
            "note": "Bank account on footer — must not appear in JSON or log",
        })
        i += 1

    # ── 6. Payment receipts (Not applicable) × 2 ─────────────────────────────
    for _ in range(2):
        supplier = random.choice(SUPPLIERS)
        amount = round(random.uniform(10000, 80000), 2)
        d = _rand_date()
        rec_path = SAMPLES_DIR / f"receipt_{i:03d}.pdf"
        _make_receipt_pdf(rec_path, supplier, amount, d)
        records.append({
            "file": rec_path.name, "doc_type": "payment_receipt",
            "supplier_name": supplier, "invoice_number": None,
            "invoice_date": d, "po_number": None,
            "tax_amount": None, "total_amount": amount,
            "expected_status": "Not applicable",
        })
        i += 1

    # ── 7. Extra invoices / POs to reach 30+ files ───────────────────────────
    while i < 20:
        supplier = random.choice(SUPPLIERS)
        base = round(random.uniform(2000, 90000), 2)
        tax = _tax(base)
        total = _total(base, tax)
        inv = _inv_number(i)
        po = _po_number(i)
        d = _rand_date()
        inv_path = SAMPLES_DIR / f"invoice_{i:03d}_extra.pdf"
        po_path = SAMPLES_DIR / f"po_{i:03d}_extra.pdf"
        _make_invoice_pdf(inv_path, supplier, inv, d, po, base, tax, total)
        _make_po_pdf(po_path, supplier, po, d, total)
        records.append({
            "file": inv_path.name, "doc_type": "supplier_invoice",
            "supplier_name": supplier, "invoice_number": inv,
            "invoice_date": d, "po_number": po,
            "tax_amount": tax, "total_amount": total,
            "expected_status": "Approve",
        })
        i += 1

    print(f"Generated {len(list(SAMPLES_DIR.iterdir()))} PDF files in {SAMPLES_DIR}")

    # ── Write test sheet (20 docs) ────────────────────────────────────────────
    test_records = records[:20]
    fieldnames = [
        "file", "doc_type", "supplier_name", "invoice_number",
        "invoice_date", "po_number", "tax_amount", "total_amount",
        "expected_status", "note",
    ]
    TEST_SHEET.parent.mkdir(parents=True, exist_ok=True)
    with open(TEST_SHEET, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(test_records)

    print(f"Test sheet written: {TEST_SHEET} ({len(test_records)} rows)")


if __name__ == "__main__":
    main()
