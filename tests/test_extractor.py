"""Tests for extract_invoice — no real PDF or network calls."""

import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from invoice_extract.extractor import extract_invoice, _parse_json_response


_CANONICAL_PAYLOAD = {
    "supplier_name": "Distribuciones Ejemplo S.L.",
    "tax_id": "B98765432",
    "invoice_number": "2026-0042",
    "issue_date": "2026-02-01",
    "due_date": "2026-03-01",
    "tax_base": 200.00,
    "vat_rate": 21,
    "vat_amount": 42.00,
    "total": 242.00,
    "confidence": 0.97,
}


def _fake_client(payload: dict) -> MagicMock:
    """Return a mock OpenAI-style client that responds with *payload* as JSON."""
    message = SimpleNamespace(content=json.dumps(payload))
    choice = SimpleNamespace(message=message)
    response = SimpleNamespace(choices=[choice])
    client = MagicMock()
    client.chat.completions.create.return_value = response
    return client


@pytest.fixture()
def patched_pdf(tmp_path):
    """Provide a fake PDF path and monkeypatch pdf_to_images to return dummy bytes."""
    fake_pdf = tmp_path / "invoice.pdf"
    fake_pdf.write_bytes(b"%PDF-fake")
    with patch("invoice_extract.extractor.pdf_to_images", return_value=[b"\x89PNG\r\n"]):
        yield fake_pdf


# --- assembly and basic behaviour ---

def test_extract_invoice_assembles_model(patched_pdf):
    client = _fake_client(_CANONICAL_PAYLOAD)
    invoice = extract_invoice(patched_pdf, client)

    assert invoice.supplier_name == "Distribuciones Ejemplo S.L."
    assert invoice.tax_id == "B98765432"
    assert invoice.invoice_number == "2026-0042"
    assert invoice.issue_date == date(2026, 2, 1)
    assert invoice.due_date == date(2026, 3, 1)
    assert invoice.amounts.tax_base == Decimal("200.00")
    assert invoice.amounts.vat_rate == Decimal("21")
    assert invoice.amounts.vat_amount == Decimal("42.00")
    assert invoice.amounts.total == Decimal("242.00")
    assert invoice.confidence == pytest.approx(0.97)
    assert invoice.source_document == "invoice.pdf"


def test_extract_invoice_no_review_on_valid_data(patched_pdf):
    client = _fake_client(_CANONICAL_PAYLOAD)
    invoice = extract_invoice(patched_pdf, client, min_confidence=0.8)
    assert invoice.needs_review is False
    assert invoice.issues == []


def test_extract_invoice_flags_low_confidence(patched_pdf):
    payload = {**_CANONICAL_PAYLOAD, "confidence": 0.5}
    client = _fake_client(payload)
    invoice = extract_invoice(patched_pdf, client, min_confidence=0.8)
    assert invoice.needs_review is True
    assert any("confidence" in issue.lower() for issue in invoice.issues)


def test_extract_invoice_null_optional_fields(patched_pdf):
    payload = {**_CANONICAL_PAYLOAD, "tax_id": None, "due_date": None}
    client = _fake_client(payload)
    invoice = extract_invoice(patched_pdf, client)
    assert invoice.tax_id is None
    assert invoice.due_date is None


# --- recipient_tax_id checks ---

def test_extract_invoice_recipient_tax_id_match_flags_review(patched_pdf):
    """Extracted tax_id == recipient_tax_id → flagged as likely recipient, not supplier."""
    client = _fake_client(_CANONICAL_PAYLOAD)
    invoice = extract_invoice(patched_pdf, client, recipient_tax_id="B98765432")
    assert invoice.needs_review is True
    assert any("recipient" in issue.lower() for issue in invoice.issues)


def test_extract_invoice_recipient_tax_id_es_prefix_normalised(patched_pdf):
    """recipient_tax_id with ES prefix is normalised before comparison."""
    client = _fake_client(_CANONICAL_PAYLOAD)
    invoice = extract_invoice(patched_pdf, client, recipient_tax_id="ESB98765432")
    assert invoice.needs_review is True
    assert any("recipient" in issue.lower() for issue in invoice.issues)


def test_extract_invoice_recipient_tax_id_no_match_clean(patched_pdf):
    """When tax IDs differ, no recipient-related issue is added."""
    client = _fake_client(_CANONICAL_PAYLOAD)
    invoice = extract_invoice(patched_pdf, client, recipient_tax_id="A12345678")
    assert invoice.needs_review is False
    assert invoice.issues == []


def test_extract_invoice_without_recipient_params_unchanged(patched_pdf):
    """Omitting recipient params produces a clean result on valid data."""
    client = _fake_client(_CANONICAL_PAYLOAD)
    invoice = extract_invoice(patched_pdf, client)
    assert invoice.needs_review is False
    assert invoice.issues == []


# --- JSON parsing helpers ---

def test_parse_json_strips_markdown_fences():
    raw = "```json\n{\"key\": 1}\n```"
    result = _parse_json_response(raw)
    assert result == {"key": 1}


def test_parse_json_clean_passthrough():
    raw = '{"key": "value"}'
    assert _parse_json_response(raw) == {"key": "value"}
