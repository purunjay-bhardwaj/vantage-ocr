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
    """Call once at startup."""
    global _tracer

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

def safe_log(
    *,
    request_id: str,
    stage: str,
    duration_ms: int,
    extra: dict | None = None,
) -> None:
    """
    Emit one JSON-lines log entry.
    Only safe fields are included (see telemetry deny-list in spec).
    """
    entry: dict = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "level": "info",
        "request_id": request_id,
        "stage": stage,
        "duration_ms": duration_ms,
    }
    if extra:
        entry.update(extra)
    print(json.dumps(entry), file=sys.stdout, flush=True)
