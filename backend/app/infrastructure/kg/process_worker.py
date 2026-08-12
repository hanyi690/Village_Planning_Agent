"""Process-isolated Layer 1 KG builder.

RDFLib construction is deliberately isolated from the FastAPI process.  A
Windows native crash in RDFLib or one of its geometry dependencies must not
terminate the planning runtime before it can persist a diagnostic terminal.
"""

from __future__ import annotations

from typing import Any, Dict


def build_layer1_turtle_worker(
    village_name: str,
    bundle: Any,
    parcel_relations: Any,
) -> Dict[str, Any]:
    """Build a KG in a fresh process and return only serializable data."""
    from app.infrastructure.kg.builder import KGBuilder

    kg = KGBuilder.build(
        village_name,
        bundle,
        parcel_relations=parcel_relations,
    )
    return {
        "turtle": kg.to_turtle(),
        "triple_count": kg.get_triple_count(),
        "parcel_count": kg.get_parcel_count(),
    }


__all__ = ["build_layer1_turtle_worker"]
