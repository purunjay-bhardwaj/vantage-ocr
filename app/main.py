"""
Vantage Retail – OCR Connector API
POST /v1/extract  — one or two files
GET  /health      — liveness probe
"""
from __future__ import annotations

import logging
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from app.check.rules import run_check
from app.config import settings
from app.extract.llm import PROMPT_VERSION, call_llm
from app.extract.models import ExtractResponse, LLMOutput, PiiInfo, PipelineInfo, VantageFields
from app.ocr.reader import ocr_file
from app.ocr.upload import UploadError, random_storage_name, validate_upload
from app.pii.masker import mask_text, restore_field
from app.telemetry.otel import get_tracer, safe_log, setup_telemetry

log = logging.getLogger(__name__)

_UPLOAD_DIR = Path(__file__).resolve().parent.parent / "data" / "uploads"

# Placeholders whose real value must never be put back into a response field
_NEVER_RESTORE_PREFIXES = ("<BANK_", "<CARD_", "<IFSC_")

_GENERIC_ERROR = "Could not read this document."


@asynccontextmanager
async def lifespan(app: FastAPI):
    _UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    setup_telemetry()
    yield


app = FastAPI(title="Vantage OCR Connector", version="1.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8501"],  # Streamlit dev origin only
    allow_methods=["POST", "GET"],
    allow_headers=["*"],
)


# ─── Helpers ───────────────────────────────────────────────────────────────────

def _restore(value, vault: dict[str, str]):
    """Restore placeholders in one field; drop it if it carries a bank/card token."""
    if isinstance(value, str) and any(p in value for p in _NEVER_RESTORE_PREFIXES):
        return None
    return restore_field(value, vault)


def _restore_fields(fields: VantageFields, vault: dict[str, str]) -> VantageFields:
    return VantageFields(
        supplier_name=_restore(fields.supplier_name, vault),
        invoice_number=_restore(fields.invoice_number, vault),
        invoice_date=_restore(fields.invoice_date, vault),
        po_number=_restore(fields.po_number, vault),
        tax_amount=fields.tax_amount,
        total_amount=fields.total_amount,
    )


def _ms_since(t0: float) -> int:
    return int((time.perf_counter() - t0) * 1000)


# ─── Core pipeline ─────────────────────────────────────────────────────────────

def _pipeline_single(
    file_bytes: bytes, mime: str, request_id: str
) -> tuple[LLMOutput, PiiInfo, PipelineInfo]:
    """Run OCR → mask → LLM → restore for one file. The vault never leaves this function."""
    tracer = get_tracer()
    timings: dict[str, int] = {}

    # Step 2: OCR (local)
    t0 = time.perf_counter()
    with tracer.start_as_current_span("ocr") as span:
        ocr_result = ocr_file(file_bytes, mime)
        span.set_attribute("ocr.engine", "tesseract")
        span.set_attribute("ocr.page_count", ocr_result.page_count)
        span.set_attribute("ocr.char_count", len(ocr_result.text))
        span.set_attribute("ocr.used_fallback", ocr_result.used_fallback)
        if ocr_result.mean_confidence is not None:
            span.set_attribute("ocr.mean_confidence", round(ocr_result.mean_confidence, 1))
    timings["ocr"] = _ms_since(t0)
    safe_log(
        request_id=request_id, stage="ocr", duration_ms=timings["ocr"],
        extra={
            "ocr_engine": "tesseract",
            "page_count": ocr_result.page_count,
            "char_count": len(ocr_result.text),
            "used_fallback": ocr_result.used_fallback,
        },
    )
    if not ocr_result.text or not ocr_result.text.strip():
        raise HTTPException(status_code=422, detail=_GENERIC_ERROR)

    # Step 3: PII masking (local)
    t0 = time.perf_counter()
    with tracer.start_as_current_span("pii") as span:
        mask_result = mask_text(ocr_result.text)
        span.set_attribute("pii.entity_count_total", sum(mask_result.entity_counts.values()))
        span.set_attribute("pii.placeholder_count", mask_result.placeholder_count)
        for etype, count in mask_result.entity_counts.items():
            span.set_attribute(f"pii.entity.{etype.lower()}", count)
    timings["pii"] = _ms_since(t0)
    safe_log(
        request_id=request_id, stage="pii.detect", duration_ms=timings["pii"],
        extra={
            "entity_counts": mask_result.entity_counts,
            "placeholder_count": mask_result.placeholder_count,
        },
    )

    try:
        # Step 4: LLM — masked text only crosses the network
        t0 = time.perf_counter()
        try:
            with tracer.start_as_current_span("llm") as span:
                span.set_attribute("llm.model", settings.openai_model)
                span.set_attribute("llm.prompt_version", PROMPT_VERSION)
                llm_out = call_llm(mask_result.masked_text)
                span.set_attribute("llm.doc_type", llm_out.document_type)
        except ValueError as exc:
            code = str(exc) if str(exc) in ("schema_invalid", "llm_unavailable") else "llm_error"
            safe_log(request_id=request_id, stage="llm.error",
                     duration_ms=_ms_since(t0), extra={"error_class": code})
            if code == "llm_unavailable":
                raise HTTPException(status_code=502, detail="Extraction service unavailable. Try again.")
            raise HTTPException(status_code=422, detail=_GENERIC_ERROR)
        timings["llm"] = _ms_since(t0)
        safe_log(
            request_id=request_id, stage="llm.extract", duration_ms=timings["llm"],
            extra={"doc_type": llm_out.document_type, "model": settings.openai_model,
                   "prompt_version": PROMPT_VERSION},
        )

        # Restore real values for display, inside this process only
        llm_out.fields = _restore_fields(llm_out.fields, mask_result.vault)
    finally:
        # Vault lives for this request only
        mask_result.vault.clear()

    pii_info = PiiInfo(masked_before_llm=True, entity_counts=dict(mask_result.entity_counts))
    pipeline_info = PipelineInfo(
        ocr_engine="tesseract",
        used_vision_fallback=ocr_result.used_fallback,
        timings_ms=timings,
    )
    return llm_out, pii_info, pipeline_info


async def _read_and_validate(upload: UploadFile) -> tuple[bytes, str]:
    data = await upload.read(settings.max_upload_bytes + 1)
    try:
        mime = validate_upload(data, settings.max_upload_bytes)
    except UploadError as exc:
        if str(exc) == "file_too_large":
            raise HTTPException(status_code=413, detail="File is larger than the 10 MB limit.")
        raise HTTPException(status_code=400, detail=_GENERIC_ERROR)
    return data, mime


# ─── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/v1/extract", response_model=ExtractResponse)
async def extract(
    file1: UploadFile = File(..., description="Supplier invoice, purchase order, or payment receipt"),
    file2: Optional[UploadFile] = File(default=None, description="Paired document for pair check"),
):
    request_id = str(uuid.uuid4())
    files_written: list[Path] = []
    t_req = time.perf_counter()

    try:
        data1, mime1 = await _read_and_validate(file1)
        data2: bytes | None = None
        mime2: str | None = None
        if file2 is not None and file2.filename:
            data2, mime2 = await _read_and_validate(file2)

        # Persist with random names only (original filename is never used or logged)
        _UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        for data, mime in ((data1, mime1), (data2, mime2)):
            if data is not None and mime is not None:
                p = _UPLOAD_DIR / random_storage_name(mime)
                p.write_bytes(data)
                files_written.append(p)

        llm1, pii1, pipe1 = _pipeline_single(data1, mime1, request_id)
        llm2: LLMOutput | None = None
        if data2 is not None and mime2 is not None:
            llm2, pii2, pipe2 = _pipeline_single(data2, mime2, request_id)
            for k, v in pii2.entity_counts.items():
                pii1.entity_counts[k] = pii1.entity_counts.get(k, 0) + v
            for k, v in pipe2.timings_ms.items():
                pipe1.timings_ms[k] = pipe1.timings_ms.get(k, 0) + v
            pipe1.used_vision_fallback = pipe1.used_vision_fallback or pipe2.used_vision_fallback

        # Step 5: business rules
        t0 = time.perf_counter()
        with get_tracer().start_as_current_span("rule") as span:
            check = run_check(llm1, llm2)
            span.set_attribute("rule.status", check.status)
            span.set_attribute("rule.duplicate", check.status == "Duplicate")
        pipe1.timings_ms["rule"] = _ms_since(t0)
        safe_log(
            request_id=request_id, stage="rule.check", duration_ms=pipe1.timings_ms["rule"],
            extra={"status": check.status, "duplicate": check.status == "Duplicate",
                   "file_count": len(files_written)},
        )

        # Show the invoice's fields when one was uploaded, else the first doc
        primary = next(
            (d for d in (llm1, llm2) if d is not None and d.document_type == "supplier_invoice"),
            llm1,
        )
        return ExtractResponse(
            request_id=request_id,
            document_type=primary.document_type,
            fields=primary.fields,
            check=check,
            pii=pii1,
            pipeline=pipe1,
        )

    except HTTPException as exc:
        safe_log(request_id=request_id, stage="request.error",
                 duration_ms=_ms_since(t_req), extra={"http_status": exc.status_code})
        raise
    except Exception as exc:  # never echo internals (may contain document text)
        safe_log(request_id=request_id, stage="request.error",
                 duration_ms=_ms_since(t_req),
                 extra={"http_status": 500, "error_class": type(exc).__name__})
        raise HTTPException(status_code=500, detail="Internal error while processing the document.")

    finally:
        for p in files_written:
            try:
                p.unlink(missing_ok=True)
            except OSError:
                pass
