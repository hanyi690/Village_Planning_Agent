"""Place evidence index and deterministic evidence scorer.

Pure module (no ``app.agent`` / ``app.services`` imports). Builds a
versioned ``PlaceEvidenceIndex`` from a ``PlanningContext`` and yields
``PlaceResolutionResult`` via ``PlaceEvidencePort``.
"""
from __future__ import annotations

from .place_evidence_index import PlaceEvidenceIndex
from .place_evidence_port import PlaceEvidencePort
from .evidence_scorer import WEIGHTS, score_candidate, total

__all__ = [
    "PlaceEvidenceIndex",
    "PlaceEvidencePort",
    "score_candidate",
    "WEIGHTS",
    "total",
]