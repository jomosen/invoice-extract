"""Post-extraction validation rules applied deterministically."""

from .models import FacturaProveedor


def flag_for_review(factura: FacturaProveedor, min_confidence: float = 0.8) -> FacturaProveedor:
    """Mark *factura* for human review when model confidence is below *min_confidence*.

    Existing incidencias are preserved.  Returns the (possibly mutated) factura.
    """
    if factura.confianza < min_confidence:
        factura.incidencias.append(
            f"Model confidence ({factura.confianza:.2f}) is below the minimum"
            f" threshold ({min_confidence:.2f})"
        )
        factura.requiere_revision = True
    return factura
