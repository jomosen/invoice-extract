"""PDF rasterisation and LLM-based invoice extraction."""

import base64
import json
import re
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import fitz  # PyMuPDF

from .models import FacturaProveedor, Importes
from .validate import flag_for_review

_SYSTEM_PROMPT_TEMPLATE = """You are an invoice data extraction assistant.
Extract the following fields from the invoice image(s) and return ONLY a valid JSON object — no markdown, no code fences, no extra text.

{recipient_context}
Required JSON keys:
  proveedor        – supplier name (string)
  cif              – supplier tax ID, or null if not found (string or null)
  numero_factura   – invoice number (string)
  fecha_emision    – issue date in ISO format YYYY-MM-DD (string)
  fecha_vencimiento – due date in ISO format YYYY-MM-DD, or null (string or null)
  base_imponible   – taxable base amount as a decimal number
  tipo_iva         – VAT rate as a percentage number, NOT a fraction (e.g. 21 for 21% VAT, never 0.21)
  cuota_iva        – VAT amount as a decimal number
  total            – total amount including VAT as a decimal number
  confianza        – your self-assessed extraction confidence between 0.0 and 1.0

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
            " — never extract this entity as the proveedor (supplier)."
        )
    else:
        context = (
            "Important context: the proveedor must be the invoice issuer (seller),"
            " never the buyer/recipient."
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
) -> FacturaProveedor:
    """Extract structured invoice data from *pdf_path* using *client*.

    *client* must expose the ``chat.completions.create`` interface (OpenAI SDK style).
    No API keys are read here; the caller is responsible for configuring *client*.

    *recipient_name* and *recipient_tax_id* identify the invoice buyer.  When provided,
    the system prompt explicitly tells the model not to extract the recipient as the
    supplier.  If the extracted CIF matches *recipient_tax_id* (after normalisation),
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

    importes = Importes(
        base_imponible=Decimal(str(data["base_imponible"])),
        tipo_iva=Decimal(str(data["tipo_iva"])),
        cuota_iva=Decimal(str(data["cuota_iva"])),
        total=Decimal(str(data["total"])),
    )

    factura = FacturaProveedor(
        proveedor=data["proveedor"],
        cif=data.get("cif"),
        numero_factura=data["numero_factura"],
        fecha_emision=date.fromisoformat(data["fecha_emision"]),
        fecha_vencimiento=(
            date.fromisoformat(data["fecha_vencimiento"])
            if data.get("fecha_vencimiento")
            else None
        ),
        importes=importes,
        confianza=float(data["confianza"]),
        documento_origen=pdf_path.name,
    )

    factura = flag_for_review(factura, min_confidence=min_confidence)

    if recipient_tax_id and factura.cif:
        # factura.cif is already normalised by FacturaProveedor.normalize_cif
        if factura.cif == _normalize_tax_id(recipient_tax_id):
            factura.incidencias.append(
                f"Extracted supplier CIF ({factura.cif}) matches the recipient tax ID"
                " — the extracted proveedor may be the invoice recipient, not the supplier"
            )
            factura.requiere_revision = True

    return factura
