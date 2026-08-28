"""Pure classification materialization helpers for land-design workers.

Pure deterministic logic with no geometry/KG/LLM dependencies, so modules
layered below ``app.modules`` can import it without creating an import cycle.
"""

from __future__ import annotations

from typing import Optional

from app.contracts.artifacts.classification_ref import (
    ClassificationDecision,
    ClassificationRef,
    classification_code_names,
)


def _classification_from_decision(
    decision: Optional[ClassificationDecision],
    *,
    source: str = "derived",
) -> Optional[ClassificationRef]:
    """Materialize only an explicit, namespace-validated classification."""
    if decision is None or decision.status != "resolved":
        return None
    system = decision.code_system.value
    names = classification_code_names(system)
    code = str(decision.selected_code or "").strip()
    if not code or names is None or code not in names:
        return None
    try:
        return ClassificationRef(
            system=decision.code_system,
            code=code,
            canonical_name=names[code],
            source=source,
            evidence_refs=list(decision.evidence_refs),
            decision_ref=decision.target_id,
        )
    except ValueError:
        return None


__all__ = ["_classification_from_decision"]
