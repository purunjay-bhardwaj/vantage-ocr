"""
Shared fixtures.

If Presidio isn't installed (e.g. CI without the spaCy model), a lightweight
stand-in for app.pii.masker is registered so app.main can be imported. API
tests patch mask_text with a deterministic fake either way.
"""
from __future__ import annotations

import importlib.util
import re
import sys
import types
from dataclasses import dataclass

import pytest

if importlib.util.find_spec("presidio_analyzer") is None:
    stub = types.ModuleType("app.pii.masker")

    @dataclass
    class MaskResult:
        masked_text: str
        vault: dict
        entity_counts: dict
        placeholder_count: int

    def mask_text(text: str) -> MaskResult:  # pragma: no cover - replaced in tests
        return MaskResult(text, {}, {}, 0)

    def restore_field(value, vault):
        if not isinstance(value, str):
            return value
        for token, original in vault.items():
            value = value.replace(token, original)
        return value

    stub.MaskResult = MaskResult
    stub.mask_text = mask_text
    stub.restore_field = restore_field
    sys.modules["app.pii.masker"] = stub


@pytest.fixture(scope="session")
def span_exporter():
    """Route spans to memory so tests can inspect them (and nothing hits stdout)."""
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    from app.telemetry import otel

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    otel._tracer = provider.get_tracer("vantage-ocr-test")
    return exporter


@pytest.fixture(autouse=True)
def _spans(span_exporter):
    span_exporter.clear()
    yield span_exporter


@pytest.fixture(autouse=True)
def temp_store(tmp_path, monkeypatch):
    """Every test gets its own empty SQLite duplicate store."""
    from app.config import settings
    monkeypatch.setattr(settings, "invoice_db_path", str(tmp_path / "store.db"))
    yield tmp_path / "store.db"


# ─── Fake PII masker used by API tests ────────────────────────────────────────

PII_NAME = "Ravi Menon"
PII_BANK = "123456789012"
PII_PHONE = "+91 98765 43210"


def fake_mask_text(text: str):
    from app.pii.masker import MaskResult

    vault: dict[str, str] = {}
    counts: dict[str, int] = {}
    masked = text
    for value, token, etype in (
        (PII_NAME, "<PERSON_1>", "PERSON"),
        (PII_BANK, "<BANK_1>", "BANK_ACCOUNT"),
        (PII_PHONE, "<PHONE_1>", "IN_MOBILE"),
    ):
        if re.search(re.escape(value), masked):
            masked = masked.replace(value, token)
            vault[token] = value
            counts[etype] = counts.get(etype, 0) + 1
    return MaskResult(masked, vault, counts, len(vault))
