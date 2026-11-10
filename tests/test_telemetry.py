import json

from app.telemetry.otel import safe_log, sanitize_extra


def test_allowed_keys_pass():
    clean, dropped = sanitize_extra({"char_count": 10, "entity_counts": {"PERSON": 2}, "status": "Approve"})
    assert clean == {"char_count": 10, "entity_counts": {"PERSON": 2}, "status": "Approve"}
    assert dropped == 0


def test_denied_and_unknown_keys_dropped():
    clean, dropped = sanitize_extra({
        "text": "Ravi Menon", "vault": {"<PERSON_1>": "Ravi Menon"}, "filename": "a.pdf",
        "invoice_number": "INV-1", "whatever": 1,
    })
    assert clean == {}
    assert dropped == 5


def test_long_string_under_allowed_key_dropped():
    clean, _ = sanitize_extra({"status": "x" * 200})
    assert clean == {}


def test_entity_counts_must_be_int_map():
    clean, _ = sanitize_extra({"entity_counts": {"PERSON": "Ravi Menon"}})
    assert clean == {}


def test_safe_log_prints_json_line(capsys):
    safe_log(request_id="r1", stage="ocr", duration_ms=5, extra={"text": "secret", "char_count": 3})
    line = capsys.readouterr().out.strip().splitlines()[-1]
    entry = json.loads(line)
    assert entry["stage"] == "ocr" and entry["char_count"] == 3
    assert "secret" not in line and entry["dropped_keys"] == 1
