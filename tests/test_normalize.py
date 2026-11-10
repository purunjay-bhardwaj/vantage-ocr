import pytest

from app.check.normalize import normalize_invoice_number


@pytest.mark.parametrize("raw", ["INV-20411", "inv 204 11", "INV 204-11", "  inv-20411  ", "INV20411"])
def test_variants_normalize_to_same(raw):
    assert normalize_invoice_number(raw) == "INV20411"


def test_none_passthrough():
    assert normalize_invoice_number(None) is None


def test_slashes_are_kept():
    # Only spaces and hyphens are removed — documented rule
    assert normalize_invoice_number("inv/24/001") == "INV/24/001"
