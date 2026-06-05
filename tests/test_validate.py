"""Tests for flag_for_review validation helper."""

from datetime import date
from decimal import Decimal

from invoice_extract.models import InvoiceAmounts, SupplierInvoice
from invoice_extract.validate import flag_for_review


def _base_invoice(confidence: float) -> SupplierInvoice:
    return SupplierInvoice(
        supplier_name="Acme S.L.",
        tax_id=None,
        invoice_number="F-001",
        issue_date=date(2026, 3, 1),
        due_date=None,
        amounts=InvoiceAmounts(
            tax_base=Decimal("100.00"),
            vat_rate=Decimal("21"),
            vat_amount=Decimal("21.00"),
            total=Decimal("121.00"),
        ),
        confidence=confidence,
        source_document="test.pdf",
    )


def test_low_confidence_marks_review():
    invoice = _base_invoice(confidence=0.6)
    result = flag_for_review(invoice, min_confidence=0.8)
    assert result.needs_review is True
    assert len(result.issues) == 1
    assert "0.60" in result.issues[0]
    assert "0.80" in result.issues[0]


def test_exact_threshold_does_not_mark_review():
    invoice = _base_invoice(confidence=0.8)
    result = flag_for_review(invoice, min_confidence=0.8)
    assert result.needs_review is False
    assert result.issues == []


def test_high_confidence_no_new_issues():
    invoice = _base_invoice(confidence=0.95)
    result = flag_for_review(invoice, min_confidence=0.8)
    assert result.needs_review is False
    assert result.issues == []


def test_existing_issues_are_preserved():
    invoice = _base_invoice(confidence=0.5)
    invoice.issues.append("pre-existing issue")
    result = flag_for_review(invoice, min_confidence=0.8)
    assert "pre-existing issue" in result.issues
    assert len(result.issues) == 2
