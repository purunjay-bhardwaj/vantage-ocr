"""
Vantage Retail – OCR Connector  ·  Streamlit UI
"""
from __future__ import annotations

import json
import time

import httpx
import streamlit as st

import os

API_URL = os.environ.get("VANTAGE_API_URL", "http://localhost:8000/v1/extract")

st.set_page_config(
    page_title="Vantage Retail · OCR Connector",
    page_icon="🧾",
    layout="centered",
)

st.title("🧾 Vantage Retail · Supplier Invoice Checker")
st.caption("Upload a supplier invoice + purchase order to check if totals match and the invoice is new.")

# ─── Upload ────────────────────────────────────────────────────────────────────
col1, col2 = st.columns(2)
with col1:
    st.subheader("Document 1")
    file1 = st.file_uploader(
        "Supplier invoice or purchase order",
        type=["pdf", "png", "jpg", "jpeg"],
        key="file1",
    )
with col2:
    st.subheader("Document 2 (optional)")
    file2 = st.file_uploader(
        "Paired document for comparison",
        type=["pdf", "png", "jpg", "jpeg"],
        key="file2",
    )

run = st.button("▶ Run check", type="primary", disabled=(file1 is None))

if run and file1 is not None:
    with st.spinner("Processing…"):
        files: dict = {"file1": (file1.name, file1.read(), file1.type)}
        if file2 is not None:
            files["file2"] = (file2.name, file2.read(), file2.type)

        try:
            t0 = time.perf_counter()
            resp = httpx.post(API_URL, files=files, timeout=60.0)
            wall_ms = int((time.perf_counter() - t0) * 1000)
        except httpx.ConnectError:
            st.error("❌ Could not connect to the API. Is the FastAPI server running on port 8000?")
            st.stop()
        except httpx.TimeoutException:
            st.error("❌ The API took too long to respond. Try again.")
            st.stop()

    if resp.status_code != 200:
        try:
            detail = resp.json().get("detail", "Unknown error")
        except ValueError:
            detail = "Unknown error"
        st.error(f"❌ {resp.status_code}: {detail}")
        st.stop()

    data = resp.json()

    # ─── Status badge ──────────────────────────────────────────────────────────
    status = data["check"]["status"]
    status_color = {
        "Approve": "🟢",
        "Hold": "🟡",
        "Duplicate": "🔴",
        "Incomplete": "🟠",
        "Not applicable": "⚪",
    }.get(status, "⚪")

    st.markdown(f"## {status_color} **{status}**")
    st.markdown(f"> {data['check']['reason']}")

    # ─── Extracted fields ─────────────────────────────────────────────────────
    st.subheader("Extracted fields")
    fields = data["fields"]
    fcol1, fcol2 = st.columns(2)
    with fcol1:
        st.metric("Document type", data["document_type"].replace("_", " ").title())
        st.metric("Supplier", fields.get("supplier_name") or "—")
        st.metric("Invoice number", fields.get("invoice_number") or "—")
        st.metric("Invoice date", fields.get("invoice_date") or "—")
    with fcol2:
        st.metric("PO number", fields.get("po_number") or "—")
        tax = fields.get("tax_amount")
        st.metric("Tax (₹)", f"{tax:,.2f}" if tax is not None else "—")
        total = fields.get("total_amount")
        st.metric("Total (₹)", f"{total:,.2f}" if total is not None else "—")

    # ─── PII panel ────────────────────────────────────────────────────────────
    with st.expander("🔒 PII masking"):
        pii = data["pii"]
        st.write(f"**Masked before LLM:** {'✅ Yes' if pii['masked_before_llm'] else '❌ No'}")
        ec = pii.get("entity_counts", {})
        if ec:
            st.write("**Detected entity types:**")
            for etype, count in ec.items():
                st.write(f"  • {etype}: {count}")
        else:
            st.write("No PII entities detected.")

    # ─── Trace panel ──────────────────────────────────────────────────────────
    with st.expander("📊 Pipeline trace"):
        pipe = data["pipeline"]
        timings = pipe.get("timings_ms", {})

        cols = st.columns(4)
        for i, stage in enumerate(["ocr", "pii", "llm", "rule"]):
            ms = timings.get(stage, "—")
            cols[i].metric(stage.upper(), f"{ms} ms" if isinstance(ms, int) else ms)

        st.write(f"**OCR engine:** {pipe['ocr_engine']}")
        st.write(f"**Used vision fallback:** {'Yes' if pipe['used_vision_fallback'] else 'No'}")
        st.write(f"**Request ID:** `{data['request_id']}`")
        st.write(f"**Wall time:** {wall_ms} ms")

    # ─── Raw JSON ─────────────────────────────────────────────────────────────
    with st.expander("📄 Raw JSON response"):
        st.json(data)
