"""Post-extraction validation rules applied deterministically."""

from .models import SupplierInvoice


def flag_for_review(invoice: SupplierInvoice, min_confidence: float = 0.8) -> SupplierInvoice:
    """Mark *invoice* for human review when model confidence is below *min_confidence*.

    Existing issues are preserved.  Returns the (possibly mutated) invoice.
    """
    if invoice.confidence < min_confidence:
        invoice.issues.append(
            f"Model confidence ({invoice.confidence:.2f}) is below the minimum"
            f" threshold ({min_confidence:.2f})"
        )
        invoice.needs_review = True
    return invoice
