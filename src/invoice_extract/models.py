"""Pydantic v2 models for structured invoice data."""

import re
from datetime import date
from decimal import Decimal

from pydantic import BaseModel, field_validator, model_validator

_CIF_PATTERN = re.compile(r'^([A-Z]\d{8}|\d{8}[A-Z]|[A-Z]\d{7}[A-Z])$')


class Importes(BaseModel):
    base_imponible: Decimal
    tipo_iva: Decimal
    cuota_iva: Decimal
    total: Decimal


class FacturaProveedor(BaseModel):
    proveedor: str
    cif: str | None
    numero_factura: str
    fecha_emision: date
    fecha_vencimiento: date | None
    importes: Importes
    confianza: float
    incidencias: list[str] = []
    requiere_revision: bool = False
    documento_origen: str

    @field_validator('cif', mode='before')
    @classmethod
    def normalize_cif(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = str(v).upper().replace(' ', '').replace('-', '')
        if v.startswith('ES'):
            v = v[2:]
        return v

    @model_validator(mode="after")
    def validate_fields(self) -> "FacturaProveedor":
        imp = self.importes
        tolerance = Decimal("0.02")

        base_plus_tax = imp.base_imponible + imp.cuota_iva
        if abs(base_plus_tax - imp.total) > tolerance:
            self.incidencias.append(
                f"base_imponible ({imp.base_imponible}) + cuota_iva ({imp.cuota_iva})"
                f" = {base_plus_tax} does not match total ({imp.total})"
            )
            self.requiere_revision = True

        expected_tax = imp.base_imponible * imp.tipo_iva / Decimal("100")
        if abs(imp.cuota_iva - expected_tax) > tolerance:
            self.incidencias.append(
                f"cuota_iva ({imp.cuota_iva}) does not match"
                f" base_imponible * tipo_iva / 100 ({expected_tax:.4f})"
            )
            self.requiere_revision = True

        if self.cif is not None and not _CIF_PATTERN.match(self.cif):
            self.incidencias.append(
                f"CIF/NIF '{self.cif}' has an unrecognised format"
            )
            self.requiere_revision = True

        return self
