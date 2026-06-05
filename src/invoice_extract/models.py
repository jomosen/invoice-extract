"""Pydantic v2 models for structured invoice data."""

import re
from datetime import date
from decimal import Decimal

from pydantic import BaseModel, field_validator, model_validator

_TAX_ID_PATTERN = re.compile(r'^([A-Z]\d{8}|\d{8}[A-Z]|[A-Z]\d{7}[A-Z])$')


class InvoiceAmounts(BaseModel):
    tax_base: Decimal
    vat_rate: Decimal
    vat_amount: Decimal
    total: Decimal


class SupplierInvoice(BaseModel):
    supplier_name: str
    tax_id: str | None
    invoice_number: str
    issue_date: date
    due_date: date | None
    amounts: InvoiceAmounts
    confidence: float
    issues: list[str] = []
    needs_review: bool = False
    source_document: str

    @field_validator('tax_id', mode='before')
    @classmethod
    def normalize_tax_id(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = str(v).upper().replace(' ', '').replace('-', '')
        if v.startswith('ES'):
            v = v[2:]
        return v

    @model_validator(mode="after")
    def validate_amounts_and_format(self) -> "SupplierInvoice":
        amt = self.amounts
        tolerance = Decimal("0.02")

        base_plus_vat = amt.tax_base + amt.vat_amount
        if abs(base_plus_vat - amt.total) > tolerance:
            self.issues.append(
                f"tax_base ({amt.tax_base}) + vat_amount ({amt.vat_amount})"
                f" = {base_plus_vat} does not match total ({amt.total})"
            )
            self.needs_review = True

        expected_vat = amt.tax_base * amt.vat_rate / Decimal("100")
        if abs(amt.vat_amount - expected_vat) > tolerance:
            self.issues.append(
                f"vat_amount ({amt.vat_amount}) does not match"
                f" tax_base * vat_rate / 100 ({expected_vat:.4f})"
            )
            self.needs_review = True

        if self.tax_id is not None and not _TAX_ID_PATTERN.match(self.tax_id):
            self.issues.append(
                f"Tax ID '{self.tax_id}' has an unrecognised format"
            )
            self.needs_review = True

        return self
