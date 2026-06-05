"""PDF rasterisation and LLM-based invoice extraction."""

import base64
import json
import re
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import fitz  # PyMuPDF

from .models import InvoiceAmounts, SupplierInvoice
from .validate import flag_for_review

_SYSTEM_PROMPT_TEMPLATE = """You are an invoice data extraction assistant.
Extract the following fields from the invoice image(s) and return ONLY a valid JSON object — no markdown, no code fences, no extra text.

{recipient_context}
Required JSON keys:
  supplier_name  – name of the invoice issuer / seller (string)
  tax_id         – supplier tax ID, or null if not found (string or null)
  invoice_number – invoice reference number (string)
  issue_date     – issue date in ISO format YYYY-MM-DD (string)
  due_date       – payment due date in ISO format YYYY-MM-DD, or null (string or null)
  tax_base       – taxable base amount as a decimal number
  vat_rate       – VAT rate as a percentage number, NOT a fraction (e.g. 21 for 21% VAT, never 0.21)
  vat_amount     – VAT amount as a decimal number
  total          – total amount including VAT as a decimal number
  confidence     – your self-assessed extraction confidence between 0.0 and 1.0

Note: source invoices are typically in Spanish, so the relevant fields may appear under Spanish labels such as "base imponible", "cuota IVA", "tipo IVA", "vencimiento", "datos fiscales del emisor", or "datos fiscales cliente".

Return exactly one JSON object. Use dot-notation decimals (e.g. 121.00), not locale-specific formatting."""


def _build_system_prompt(recipient_name: str | None, recipient_tax_id: str | None) -> str:
    if recipient_name or recipient_tax_id:
        parts = []
        if recipient_name:
            parts.append(f'name "{recipient_name}"')
        if recipient_tax_id:
            parts.append(f'tax ID "{recipient_tax_id}"')
        hint = " and ".join(parts)
        context = (
            f"Important context: the invoice recipient (buyer) has {hint}"
            " — never extract this entity as the supplier_name or tax_id."
            " The supplier is always the issuer (seller) of the invoice."
        )
    else:
        context = (
            "Important context: supplier_name and tax_id must identify the invoice issuer (seller),"
            " never the buyer or recipient."
        )
    return _SYSTEM_PROMPT_TEMPLATE.format(recipient_context=context)


def _normalize_tax_id(tax_id: str) -> str:
    tax_id = tax_id.upper().replace(' ', '').replace('-', '')
    if tax_id.startswith('ES'):
        tax_id = tax_id[2:]
    return tax_id


def pdf_to_images(pdf_path: str | Path, dpi: int = 200) -> list[bytes]:
    """Rasterise every page of *pdf_path* to PNG and return raw bytes per page."""
    doc = fitz.open(str(pdf_path))
    matrix = fitz.Matrix(dpi / 72, dpi / 72)
    images: list[bytes] = []
    for page in doc:
        pix = page.get_pixmap(matrix=matrix)
        images.append(pix.tobytes("png"))
    doc.close()
    return images


def _parse_json_response(text: str) -> dict[str, Any]:
    """Return parsed JSON, stripping accidental markdown code fences if present."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return json.loads(text)


def extract_invoice(
    pdf_path: str | Path,
    client: Any,
    model: str = "gpt-4o",
    min_confidence: float = 0.8,
    recipient_name: str | None = None,
    recipient_tax_id: str | None = None,
) -> SupplierInvoice:
    """Extract structured invoice data from *pdf_path* using *client*.

    *client* must expose the ``chat.completions.create`` interface (OpenAI SDK style).
    No API keys are read here; the caller is responsible for configuring *client*.

    *recipient_name* and *recipient_tax_id* identify the invoice buyer.  When provided,
    the system prompt explicitly tells the model not to extract the recipient as the
    supplier.  If the extracted tax_id matches *recipient_tax_id* (after normalisation),
    the invoice is flagged for human review.
    """
    pdf_path = Path(pdf_path)
    images = pdf_to_images(pdf_path)

    system_prompt = _build_system_prompt(recipient_name, recipient_tax_id)

    content: list[dict[str, Any]] = [{"type": "text", "text": "Extract the invoice data from the following page(s):"}]
    for img_bytes in images:
        b64 = base64.b64encode(img_bytes).decode()
        content.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{b64}"},
            }
        )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": content},
    ]

    response = client.chat.completions.create(
        model=model,
        messages=messages,
        response_format={"type": "json_object"},
    )

    raw_text = response.choices[0].message.content
    data = _parse_json_response(raw_text)

    amounts = InvoiceAmounts(
        tax_base=Decimal(str(data["tax_base"])),
        vat_rate=Decimal(str(data["vat_rate"])),
        vat_amount=Decimal(str(data["vat_amount"])),
        total=Decimal(str(data["total"])),
    )

    invoice = SupplierInvoice(
        supplier_name=data["supplier_name"],
        tax_id=data.get("tax_id"),
        invoice_number=data["invoice_number"],
        issue_date=date.fromisoformat(data["issue_date"]),
        due_date=(
            date.fromisoformat(data["due_date"])
            if data.get("due_date")
            else None
        ),
        amounts=amounts,
        confidence=float(data["confidence"]),
        source_document=pdf_path.name,
    )

    invoice = flag_for_review(invoice, min_confidence=min_confidence)

    if recipient_tax_id and invoice.tax_id:
        # invoice.tax_id is already normalised by SupplierInvoice.normalize_tax_id
        if invoice.tax_id == _normalize_tax_id(recipient_tax_id):
            invoice.issues.append(
                f"Extracted tax_id ({invoice.tax_id}) matches the recipient tax ID"
                " — the extracted supplier may be the invoice recipient, not the supplier"
            )
            invoice.needs_review = True

    return invoice
