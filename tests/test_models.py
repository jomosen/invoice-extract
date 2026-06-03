"""Tests for FacturaProveedor model validation logic."""

from datetime import date
from decimal import Decimal

import pytest

from invoice_extract.models import FacturaProveedor, Importes


def _make_factura(**overrides) -> FacturaProveedor:
    defaults = dict(
        proveedor="Ferretería Ejemplo S.L.",
        cif="B12345678",
        numero_factura="F-2026-001",
        fecha_emision=date(2026, 1, 15),
        fecha_vencimiento=None,
        importes=Importes(
            base_imponible=Decimal("100.00"),
            tipo_iva=Decimal("21"),
            cuota_iva=Decimal("21.00"),
            total=Decimal("121.00"),
        ),
        confianza=0.95,
        documento_origen="factura.pdf",
    )
    defaults.update(overrides)
    return FacturaProveedor(**defaults)


# --- arithmetic validation ---

def test_valid_invoice_has_no_incidencias():
    factura = _make_factura()
    assert factura.incidencias == []
    assert factura.requiere_revision is False


def test_total_mismatch_triggers_revision():
    factura = _make_factura(
        importes=Importes(
            base_imponible=Decimal("100.00"),
            tipo_iva=Decimal("21"),
            cuota_iva=Decimal("21.00"),
            total=Decimal("130.00"),  # wrong total
        )
    )
    assert factura.requiere_revision is True
    assert any("total" in inc for inc in factura.incidencias)


def test_tax_amount_mismatch_triggers_revision():
    factura = _make_factura(
        importes=Importes(
            base_imponible=Decimal("100.00"),
            tipo_iva=Decimal("21"),
            cuota_iva=Decimal("10.00"),  # should be 21.00
            total=Decimal("110.00"),
        )
    )
    assert factura.requiere_revision is True
    assert len(factura.incidencias) >= 1


def test_both_checks_pass_no_revision():
    """Rounding-safe amounts within tolerance should not trigger revision."""
    factura = _make_factura(
        importes=Importes(
            base_imponible=Decimal("99.99"),
            tipo_iva=Decimal("21"),
            cuota_iva=Decimal("21.00"),  # 99.99 * 0.21 = 20.9979 → within 0.02
            total=Decimal("120.99"),
        )
    )
    assert factura.requiere_revision is False
    assert factura.incidencias == []


# --- CIF/NIF format validation ---

def test_cif_letter_plus_digits_passes():
    """Standard CIF: letter + 8 digits."""
    factura = _make_factura(cif="A87654321")
    assert factura.cif == "A87654321"
    assert factura.incidencias == []
    assert factura.requiere_revision is False


def test_nif_digits_plus_letter_passes():
    """Standard NIF: 8 digits + letter."""
    factura = _make_factura(cif="12345678Z")
    assert factura.cif == "12345678Z"
    assert factura.incidencias == []


def test_nie_letter_digits_letter_passes():
    """NIE format: letter + 7 digits + letter."""
    factura = _make_factura(cif="X1234567L")
    assert factura.cif == "X1234567L"
    assert factura.incidencias == []


def test_cif_normalization_strips_es_prefix():
    factura = _make_factura(cif="ESB12345678")
    assert factura.cif == "B12345678"
    assert factura.incidencias == []


def test_cif_normalization_uppercases_and_strips_spaces():
    factura = _make_factura(cif=" b 12345678 ")
    assert factura.cif == "B12345678"
    assert factura.incidencias == []


def test_invalid_cif_nine_digits_adds_incidencia():
    """9 digits with no letter is not a valid Spanish tax ID."""
    factura = _make_factura(cif="123456789")
    assert factura.requiere_revision is True
    assert any("unrecognised format" in inc for inc in factura.incidencias)


def test_none_cif_skips_format_validation():
    factura = _make_factura(cif=None)
    assert factura.cif is None
    assert factura.incidencias == []
    assert factura.requiere_revision is False
