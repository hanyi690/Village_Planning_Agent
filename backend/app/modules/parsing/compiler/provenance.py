"""Provenance construction for compiler fragments."""
from __future__ import annotations

from app.modules.schema.contracts.provenance import Provenance


def build_fragment_provenance(
    dimension_key: str,
    report_id: str,
    run_id: str,
    section_locators: list[str],
) -> Provenance:
    """Provenance pointing back to the source dimension report + sections."""
    return Provenance(
        source="l1_observe",
        run_id=run_id,
        module="l1_observe",
        trace=[dimension_key, report_id],
        natural_language_description=(
            "sections: " + ", ".join(section_locators)
            if section_locators
            else None
        ),
    )


__all__ = ["build_fragment_provenance"]
