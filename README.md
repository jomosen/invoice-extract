# invoice-extract

![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)

Extract structured invoice data from PDF files using a vision-capable LLM, with deterministic validation.

## What it does

1. Rasterises each PDF page to PNG (via PyMuPDF).
2. Sends the images to a vision LLM (default: `gpt-4o`) with a prompt that requests a JSON response.
3. Parses the response into a typed `SupplierInvoice` Pydantic model.
4. Validates deterministically:
   - **Arithmetic**: tax base + VAT amount must equal total; VAT amount must match `tax_base × vat_rate / 100` (tolerance ±0.02).
   - **Format**: Tax ID is normalised (uppercase, stripped of spaces/hyphens/ES prefix) and checked against Spanish tax ID formats.
   - **Recipient**: if the extracted supplier tax ID matches the provided `recipient_tax_id`, the invoice is flagged for review.
5. Sets `needs_review = True` and records a human-readable reason in `issues` for anything that fails.

## Installation

```bash
pip install -e ".[dev]"
```

## Design: injected client

The package **never** creates an OpenAI client or reads `OPENAI_API_KEY`.  You pass in the client, which makes the library fully testable without credentials or network access.

```python
import os
from openai import OpenAI
from invoice_extract import extract_invoice

client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
model = os.environ.get("OPENAI_MODEL", "gpt-4o")

invoice = extract_invoice("invoice.pdf", client, model=model)

print(invoice.supplier_name, invoice.amounts.total)
if invoice.needs_review:
    print("Needs review:", invoice.issues)
```

## Identifying the invoice recipient

Pass the buyer's identity so the model is explicitly told not to mistake the recipient for the supplier:

```python
invoice = extract_invoice(
    "invoice.pdf",
    client,
    recipient_name="Recipient Company Name",
    recipient_tax_id="B12345678",
)
```

Both parameters are optional.  When omitted, a generic "supplier = issuer" instruction is used instead.  If the extracted `tax_id` matches `recipient_tax_id` (case-insensitive, ES prefix stripped), the invoice is flagged for human review with an explanatory `issues` entry.

## Why deterministic validation

invoice-extract treats the LLM as an extraction engine, not an arbiter of correctness:

1. **The LLM extracts.** It reads the document and returns structured JSON, including a self-assessed confidence score.
2. **Code validates.** Arithmetic checks (tax base + VAT = total), VAT rate consistency, and tax ID format are verified deterministically — the model's output is not trusted on these points.
3. **Doubt is surfaced, not silenced.** Anything that fails a check — or falls below the confidence threshold — sets `needs_review = True` and records a human-readable reason in `issues`.  The LLM's self-reported confidence is used as one signal among several, not as the final word.

## Running tests

```bash
pytest
```

Tests are fully offline — no API calls, no real PDF needed.
