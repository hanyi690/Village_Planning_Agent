"""Provenance construction for compiler fragments."""
from __future__ import annotations

from app.contracts.artifacts.provenance import Provenance


def build_fragment_provenance(
    dimension_key: str,
    report_id: str,
    run_id: str,
    section_locators: list[str],
    *,
    source_module: str = "l1_observe",
) -> Provenance:
    """Provenance pointing back to the source dimension report + sections.

    ``source_module`` stamps both the ``source`` and ``module`` fields so each
    profile records which pipeline stage produced the fragment. Defaults to
    ``"l1_observe"`` for backward compatibility.
    """
    return Provenance(
        source=source_module,
        run_id=run_id,
        module=source_module,
        trace=[dimension_key, report_id],
        natural_language_description=(
            "sections: " + ", ".join(section_locators)
            if section_locators
            else None
        ),
    )


__all__ = ["build_fragment_provenance"]
