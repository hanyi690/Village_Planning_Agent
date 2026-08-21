"""Place evidence index and deterministic evidence scorer.

Pure module (no ``app.agent`` / application-layer imports). Builds a
versioned ``PlaceEvidenceIndex`` from a ``PlanningContext`` and yields
``PlaceResolutionResult`` via ``EvidenceGraph``.
"""
from __future__ import annotations

from .place_evidence_index import PlaceEvidenceIndex
from .evidence_scorer import WEIGHTS, score_candidate, total

__all__ = [
    "PlaceEvidenceIndex",
    "score_candidate",
    "WEIGHTS",
    "total",
]
