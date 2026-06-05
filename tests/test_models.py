"""Tests for SupplierInvoice model validation logic."""

from datetime import date
from decimal import Decimal

import pytest

from invoice_extract.models import InvoiceAmounts, SupplierInvoice


def _make_invoice(**overrides) -> SupplierInvoice:
    defaults = dict(
        supplier_name="Ferretería Ejemplo S.L.",
        tax_id="B12345678",
        invoice_number="F-2026-001",
        issue_date=date(2026, 1, 15),
        due_date=None,
        amounts=InvoiceAmounts(
            tax_base=Decimal("100.00"),
            vat_rate=Decimal("21"),
            vat_amount=Decimal("21.00"),
            total=Decimal("121.00"),
        ),
        confidence=0.95,
        source_document="invoice.pdf",
    )
    defaults.update(overrides)
    return SupplierInvoice(**defaults)


# --- arithmetic validation ---

def test_valid_invoice_has_no_issues():
    invoice = _make_invoice()
    assert invoice.issues == []
    assert invoice.needs_review is False


def test_total_mismatch_triggers_review():
    invoice = _make_invoice(
        amounts=InvoiceAmounts(
            tax_base=Decimal("100.00"),
            vat_rate=Decimal("21"),
            vat_amount=Decimal("21.00"),
            total=Decimal("130.00"),  # wrong total
        )
    )
    assert invoice.needs_review is True
    assert any("total" in issue for issue in invoice.issues)


def test_vat_amount_mismatch_triggers_review():
    invoice = _make_invoice(
        amounts=InvoiceAmounts(
            tax_base=Decimal("100.00"),
            vat_rate=Decimal("21"),
            vat_amount=Decimal("10.00"),  # should be 21.00
            total=Decimal("110.00"),
        )
    )
    assert invoice.needs_review is True
    assert len(invoice.issues) >= 1


def test_both_checks_pass_no_review():
    """Rounding-safe amounts within tolerance should not trigger review."""
    invoice = _make_invoice(
        amounts=InvoiceAmounts(
            tax_base=Decimal("99.99"),
            vat_rate=Decimal("21"),
            vat_amount=Decimal("21.00"),  # 99.99 * 21 / 100 = 20.9979 → within 0.02
            total=Decimal("120.99"),
        )
    )
    assert invoice.needs_review is False
    assert invoice.issues == []


# --- tax ID format validation ---

def test_tax_id_letter_plus_digits_passes():
    """Standard CIF: letter + 8 digits."""
    invoice = _make_invoice(tax_id="A87654321")
    assert invoice.tax_id == "A87654321"
    assert invoice.issues == []
    assert invoice.needs_review is False


def test_tax_id_digits_plus_letter_passes():
    """Standard NIF: 8 digits + letter."""
    invoice = _make_invoice(tax_id="12345678Z")
    assert invoice.tax_id == "12345678Z"
    assert invoice.issues == []


def test_tax_id_nie_format_passes():
    """NIE format: letter + 7 digits + letter."""
    invoice = _make_invoice(tax_id="X1234567L")
    assert invoice.tax_id == "X1234567L"
    assert invoice.issues == []


def test_tax_id_normalization_strips_es_prefix():
    invoice = _make_invoice(tax_id="ESB12345678")
    assert invoice.tax_id == "B12345678"
    assert invoice.issues == []


def test_tax_id_normalization_uppercases_and_strips_spaces():
    invoice = _make_invoice(tax_id=" b 12345678 ")
    assert invoice.tax_id == "B12345678"
    assert invoice.issues == []


def test_invalid_tax_id_nine_digits_flags_review():
    """9 digits with no letter is not a valid Spanish tax ID."""
    invoice = _make_invoice(tax_id="123456789")
    assert invoice.needs_review is True
    assert any("unrecognised format" in issue for issue in invoice.issues)


def test_none_tax_id_skips_format_validation():
    invoice = _make_invoice(tax_id=None)
    assert invoice.tax_id is None
    assert invoice.issues == []
    assert invoice.needs_review is False
