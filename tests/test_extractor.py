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
    "proveedor": "Distribuciones Ejemplo S.L.",
    "cif": "B98765432",
    "numero_factura": "2026-0042",
    "fecha_emision": "2026-02-01",
    "fecha_vencimiento": "2026-03-01",
    "base_imponible": 200.00,
    "tipo_iva": 21,
    "cuota_iva": 42.00,
    "total": 242.00,
    "confianza": 0.97,
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
    fake_pdf = tmp_path / "factura.pdf"
    fake_pdf.write_bytes(b"%PDF-fake")
    with patch("invoice_extract.extractor.pdf_to_images", return_value=[b"\x89PNG\r\n"]):
        yield fake_pdf


# --- assembly and basic behaviour ---

def test_extract_invoice_assembles_factura(patched_pdf):
    client = _fake_client(_CANONICAL_PAYLOAD)
    factura = extract_invoice(patched_pdf, client)

    assert factura.proveedor == "Distribuciones Ejemplo S.L."
    assert factura.cif == "B98765432"
    assert factura.numero_factura == "2026-0042"
    assert factura.fecha_emision == date(2026, 2, 1)
    assert factura.fecha_vencimiento == date(2026, 3, 1)
    assert factura.importes.base_imponible == Decimal("200.00")
    assert factura.importes.tipo_iva == Decimal("21")
    assert factura.importes.cuota_iva == Decimal("42.00")
    assert factura.importes.total == Decimal("242.00")
    assert factura.confianza == pytest.approx(0.97)
    assert factura.documento_origen == "factura.pdf"


def test_extract_invoice_no_revision_on_valid_data(patched_pdf):
    client = _fake_client(_CANONICAL_PAYLOAD)
    factura = extract_invoice(patched_pdf, client, min_confidence=0.8)
    assert factura.requiere_revision is False
    assert factura.incidencias == []


def test_extract_invoice_flags_low_confidence(patched_pdf):
    payload = {**_CANONICAL_PAYLOAD, "confianza": 0.5}
    client = _fake_client(payload)
    factura = extract_invoice(patched_pdf, client, min_confidence=0.8)
    assert factura.requiere_revision is True
    assert any("confidence" in inc.lower() for inc in factura.incidencias)


def test_extract_invoice_null_optional_fields(patched_pdf):
    payload = {**_CANONICAL_PAYLOAD, "cif": None, "fecha_vencimiento": None}
    client = _fake_client(payload)
    factura = extract_invoice(patched_pdf, client)
    assert factura.cif is None
    assert factura.fecha_vencimiento is None


# --- recipient_tax_id checks ---

def test_extract_invoice_recipient_cif_match_flags_revision(patched_pdf):
    """Extracted CIF == recipient_tax_id → flagged as likely recipient, not supplier."""
    client = _fake_client(_CANONICAL_PAYLOAD)
    factura = extract_invoice(patched_pdf, client, recipient_tax_id="B98765432")
    assert factura.requiere_revision is True
    assert any("recipient" in inc.lower() for inc in factura.incidencias)


def test_extract_invoice_recipient_tax_id_es_prefix_normalised(patched_pdf):
    """recipient_tax_id with ES prefix is normalised before comparison."""
    client = _fake_client(_CANONICAL_PAYLOAD)
    factura = extract_invoice(patched_pdf, client, recipient_tax_id="ESB98765432")
    assert factura.requiere_revision is True
    assert any("recipient" in inc.lower() for inc in factura.incidencias)


def test_extract_invoice_recipient_cif_no_match_clean(patched_pdf):
    """When CIFs differ, no recipient-related incidencia is added."""
    client = _fake_client(_CANONICAL_PAYLOAD)
    factura = extract_invoice(patched_pdf, client, recipient_tax_id="A12345678")
    assert factura.requiere_revision is False
    assert factura.incidencias == []


def test_extract_invoice_without_recipient_params_unchanged(patched_pdf):
    """Omitting recipient params produces the same result as before."""
    client = _fake_client(_CANONICAL_PAYLOAD)
    factura = extract_invoice(patched_pdf, client)
    assert factura.requiere_revision is False
    assert factura.incidencias == []


# --- JSON parsing helpers ---

def test_parse_json_strips_markdown_fences():
    raw = "```json\n{\"key\": 1}\n```"
    result = _parse_json_response(raw)
    assert result == {"key": 1}


def test_parse_json_clean_passthrough():
    raw = '{"key": "value"}'
    assert _parse_json_response(raw) == {"key": "value"}
