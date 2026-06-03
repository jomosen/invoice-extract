"""Tests for flag_for_review validation helper."""

from datetime import date
from decimal import Decimal

from invoice_extract.models import FacturaProveedor, Importes
from invoice_extract.validate import flag_for_review


def _base_factura(confianza: float) -> FacturaProveedor:
    return FacturaProveedor(
        proveedor="Acme S.L.",
        cif=None,
        numero_factura="F-001",
        fecha_emision=date(2026, 3, 1),
        fecha_vencimiento=None,
        importes=Importes(
            base_imponible=Decimal("100.00"),
            tipo_iva=Decimal("21"),
            cuota_iva=Decimal("21.00"),
            total=Decimal("121.00"),
        ),
        confianza=confianza,
        documento_origen="test.pdf",
    )


def test_low_confidence_marks_revision():
    factura = _base_factura(confianza=0.6)
    result = flag_for_review(factura, min_confidence=0.8)
    assert result.requiere_revision is True
    assert len(result.incidencias) == 1
    assert "0.60" in result.incidencias[0]
    assert "0.80" in result.incidencias[0]


def test_exact_threshold_does_not_mark_revision():
    factura = _base_factura(confianza=0.8)
    result = flag_for_review(factura, min_confidence=0.8)
    assert result.requiere_revision is False
    assert result.incidencias == []


def test_high_confidence_no_new_incidencias():
    factura = _base_factura(confianza=0.95)
    result = flag_for_review(factura, min_confidence=0.8)
    assert result.requiere_revision is False
    assert result.incidencias == []


def test_existing_incidencias_are_preserved():
    factura = _base_factura(confianza=0.5)
    factura.incidencias.append("pre-existing issue")
    result = flag_for_review(factura, min_confidence=0.8)
    assert "pre-existing issue" in result.incidencias
    assert len(result.incidencias) == 2
