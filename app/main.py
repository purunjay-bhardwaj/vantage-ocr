"""
Vantage Retail – OCR Connector API
POST /v1/extract  — one or two files
"""
from __future__ import annotations

import logging
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.check.rules import run_check
from app.config import settings
from app.extract.llm import call_llm
from app.extract.models import (
    CheckResult, ExtractResponse, LLMOutput, PiiInfo, PipelineInfo, VantageFields
)
from app.ocr.reader import ocr_file
from app.ocr.upload import UploadError, random_storage_name, validate_upload
from app.pii.masker import mask_text, restore_field
from app.telemetry.otel import get_tracer, safe_log, setup_telemetry

log = logging.getLogger(__name__)

# Temporary upload directory
_UPLOAD_DIR = Path(__file__).resolve().parent.parent / "data" / "uploads"
_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_telemetry()
    yield


app = FastAPI(title="Vantage OCR Connector", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8501"],  # Streamlit dev origin only
    allow_methods=["POST", "GET"],
    allow_headers=["*"],
)


# ─── Core pipeline ─────────────────────────────────────────────────────────────

def _pipeline_single(file_bytes: bytes, mime: str, request_id: str) -> tuple[LLMOutput, PiiInfo, PipelineInfo, dict]:
    """Run OCR → mask → LLM for one file. Returns LLMOutput + metadata."""
    tracer = get_tracer()
    timings: dict[str, int] = {}

    # Step 2: OCR
    t0 = time.perf_counter()
    with tracer.start_as_current_span("ocr") as span:
        ocr_result = ocr_file(file_bytes, mime)
        span.set_attribute("ocr.engine", "tesseract")
        span.set_attribute("ocr.page_count", ocr_result.page_count)
        span.set_attribute("ocr.char_count", len(ocr_result.text))
        span.set_attribute("ocr.used_fallback", ocr_result.used_fallback)
        if ocr_result.mean_confidence is not None:
            span.set_attribute("ocr.mean_confidence", round(ocr_result.mean_confidence, 1))
    timings["ocr"] = int((time.perf_counter() - t0) * 1000)

    safe_log(
        request_id=request_id,
        stage="ocr",
        duration_ms=timings["ocr"],
        extra={
            "ocr_engine": "tesseract",
            "page_count": ocr_result.page_count,
            "char_count": len(ocr_result.text),
            "used_fallback": ocr_result.used_fallback,
        },
    )

    if ocr_result.error or ocr_result.used_fallback:
        if not ocr_result.text:
            raise HTTPException(status_code=422, detail="Could not read this document.")

    # Step 3: PII masking
    t0 = time.perf_counter()
    with tracer.start_as_current_span("pii") as span:
        mask_result = mask_text(ocr_result.text)
        span.set_attribute("pii.entity_count_total", sum(mask_result.entity_counts.values()))
        span.set_attribute("pii.placeholder_count", mask_result.placeholder_count)
        for etype, count in mask_result.entity_counts.items():
            span.set_attribute(f"pii.entity.{etype.lower()}", count)
    timings["pii"] = int((time.perf_counter() - t0) * 1000)

    safe_log(
        request_id=request_id,
        stage="pii.detect",
        duration_ms=timings["pii"],
        extra={
            "entity_counts": mask_result.entity_counts,
            "placeholder_count": mask_result.placeholder_count,
        },
    )

    # Step 4: LLM extraction
    vault = mask_result.vault
    try:
        t0 = time.perf_counter()
        with tracer.start_as_current_span("llm") as span:
            llm_out = call_llm(mask_result.masked_text)
            span.set_attribute("llm.model", settings.openai_model)
            span.set_attribute("llm.doc_type", llm_out.document_type)
            # Prompt version – safe to log; no user content
            span.set_attribute("llm.prompt_version", "v1")
        timings["llm"] = int((time.perf_counter() - t0) * 1000)
    except ValueError as exc:
        safe_log(request_id=request_id, stage="llm.error", duration_ms=0, extra={"error_class": str(exc)})
        raise HTTPException(status_code=422, detail="Could not read this document.")

    safe_log(
        request_id=request_id,
        stage="llm.extract",
        duration_ms=timings["llm"],
        extra={"doc_type": llm_out.document_type, "model": settings.openai_model},
    )

    # Restore real values BEFORE vault is cleared, inside this process only
    restored_vault = dict(mask_result.vault)  # copy for return
    fields = llm_out.fields
    llm_out.fields = VantageFields(
        supplier_name=restore_field(fields.supplier_name, restored_vault),
        invoice_number=restore_field(fields.invoice_number, restored_vault),
        invoice_date=restore_field(fields.invoice_date, restored_vault),
        po_number=restore_field(fields.po_number, restored_vault),
        tax_amount=fields.tax_amount,
        total_amount=fields.total_amount,
    )

    pii_info = PiiInfo(masked_before_llm=True, entity_counts=mask_result.entity_counts)
    pipeline_info = PipelineInfo(
        ocr_engine="tesseract",
        used_vision_fallback=ocr_result.used_fallback,
        timings_ms=timings,
    )
    return llm_out, pii_info, pipeline_info, restored_vault


# ─── Endpoint ──────────────────────────────────────────────────────────────────

@app.post("/v1/extract", response_model=ExtractResponse)
async def extract(
    file1: UploadFile = File(..., description="Supplier invoice, purchase order, or payment receipt"),
    file2: Optional[UploadFile] = File(default=None, description="Paired document for pair check"),
):
    request_id = str(uuid.uuid4())
    files_written: list[Path] = []

    try:
        # Read and validate uploads
        data1 = await file1.read()
        try:
            mime1 = validate_upload(data1, settings.max_upload_bytes)
        except UploadError as exc:
            raise HTTPException(status_code=400, detail="Could not read this document.")

        data2: bytes | None = None
        mime2: str | None = None
        if file2 and file2.filename:
            data2 = await file2.read()
            try:
                mime2 = validate_upload(data2, settings.max_upload_bytes)
            except UploadError:
                raise HTTPException(status_code=400, detail="Could not read this document.")

        # Save with random names (delete at end)
        p1 = _UPLOAD_DIR / random_storage_name(mime1)
        p1.write_bytes(data1)
        files_written.append(p1)

        p2: Path | None = None
        if data2 and mime2:
            p2 = _UPLOAD_DIR / random_storage_name(mime2)
            p2.write_bytes(data2)
            files_written.append(p2)

        # Pipeline for each file
        llm1, pii1, pipe1, _vault1 = _pipeline_single(data1, mime1, request_id)

        llm2: LLMOutput | None = None
        if data2 and mime2:
            llm2, pii2, pipe2, _vault2 = _pipeline_single(data2, mime2, request_id)
            # Merge entity counts
            for k, v in pii2.entity_counts.items():
                pii1.entity_counts[k] = pii1.entity_counts.get(k, 0) + v
            # Merge timings (sum)
            for k, v in pipe2.timings_ms.items():
                pipe1.timings_ms[k] = pipe1.timings_ms.get(k, 0) + v

        # Step 5: Business rules
        t0 = time.perf_counter()
        tracer = get_tracer()
        with tracer.start_as_current_span("rule") as span:
            check = run_check(llm1, llm2)
            span.set_attribute("rule.status", check.status)
        rule_ms = int((time.perf_counter() - t0) * 1000)
        pipe1.timings_ms["rule"] = rule_ms

        safe_log(
            request_id=request_id,
            stage="rule.check",
            duration_ms=rule_ms,
            extra={"status": check.status},
        )

        return ExtractResponse(
            request_id=request_id,
            document_type=llm1.document_type,
            fields=llm1.fields,
            check=check,
            pii=pii1,
            pipeline=pipe1,
        )

    finally:
        # Delete uploads regardless of outcome
        for p in files_written:
            try:
                p.unlink(missing_ok=True)
            except Exception:
                pass
