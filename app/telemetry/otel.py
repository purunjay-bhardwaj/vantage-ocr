"""
OpenTelemetry setup.
Uses OTLP gRPC exporter if OTEL_EXPORTER_OTLP_ENDPOINT is set,
otherwise falls back to a console (stdout) JSON-lines exporter.

Deny-list enforced: OCR text, prompt, model completion, field values,
filenames, and placeholder vaults never enter spans or logs.
"""
from __future__ import annotations

import json
import logging
import sys
import time
from contextlib import contextmanager
from typing import Generator

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
from opentelemetry.sdk.resources import Resource

from app.config import settings

log = logging.getLogger(__name__)

_tracer: trace.Tracer | None = None


def setup_telemetry(service_name: str = "vantage-ocr") -> None:
    """Call once at startup. Safe to call again (no-op after the first call)."""
    global _tracer
    if _tracer is not None:
        return

    resource = Resource.create({"service.name": service_name})
    provider = TracerProvider(resource=resource)

    if settings.otel_exporter_otlp_endpoint:
        try:
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
            exporter = OTLPSpanExporter(endpoint=settings.otel_exporter_otlp_endpoint)
            provider.add_span_processor(BatchSpanProcessor(exporter))
        except Exception as exc:
            log.warning("otlp_setup_failed class=%s falling_back_to_console", type(exc).__name__)
            provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
    else:
        provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))

    trace.set_tracer_provider(provider)
    _tracer = trace.get_tracer(service_name)


def get_tracer() -> trace.Tracer:
    global _tracer
    if _tracer is None:
        setup_telemetry()
    return _tracer  # type: ignore[return-value]


# ─── Safe structured log ───────────────────────────────────────────────────────
#
# Allow-list, not just deny-list: only these keys may appear in `extra`, and
# only with scalar values (or a flat dict of str → int for entity counts).
# Anything else is dropped and counted, so a careless caller cannot leak
# OCR text, field values, the vault, or filenames into logs.

ALLOWED_EXTRA_KEYS: frozenset[str] = frozenset({
    "ocr_engine", "page_count", "char_count", "used_fallback", "mean_confidence",
    "entity_counts", "placeholder_count",
    "doc_type", "model", "prompt_version",
    "status", "duplicate",
    "error_class", "http_status", "file_count",
})

DENIED_KEYS: frozenset[str] = frozenset({
    "text", "ocr_text", "masked_text", "prompt", "completion", "raw",
    "fields", "vault", "filename", "file_name", "path",
    "supplier_name", "invoice_number", "po_number", "invoice_date",
    "tax_amount", "total_amount", "reason",
})

_SCALAR = (str, int, float, bool, type(None))


def _safe_value(key: str, value):
    if key == "entity_counts":
        if isinstance(value, dict) and all(
            isinstance(k, str) and isinstance(v, int) for k, v in value.items()
        ):
            return True, dict(value)
        return False, None
    if isinstance(value, _SCALAR):
        # Guard against long free-text sneaking in through an allowed key
        if isinstance(value, str) and len(value) > 64:
            return False, None
        return True, value
    return False, None


def sanitize_extra(extra: dict | None) -> tuple[dict, int]:
    """Return (clean_extra, dropped_count)."""
    clean: dict = {}
    dropped = 0
    for key, value in (extra or {}).items():
        if key in DENIED_KEYS or key not in ALLOWED_EXTRA_KEYS:
            dropped += 1
            continue
        ok, v = _safe_value(key, value)
        if ok:
            clean[key] = v
        else:
            dropped += 1
    return clean, dropped


def safe_log(
    *,
    request_id: str,
    stage: str,
    duration_ms: int,
    extra: dict | None = None,
) -> dict:
    """
    Emit one JSON-lines log entry containing only allow-listed fields.
    Returns the emitted entry (handy for tests).
    """
    entry: dict = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "level": "info",
        "request_id": request_id,
        "stage": stage,
        "duration_ms": int(duration_ms),
    }
    clean, dropped = sanitize_extra(extra)
    entry.update(clean)
    if dropped:
        entry["dropped_keys"] = dropped
    print(json.dumps(entry), file=sys.stdout, flush=True)
    return entry
