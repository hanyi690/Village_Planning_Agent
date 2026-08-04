from __future__ import annotations

from typing import Any

from app.modules.ports.spatial_query import SpatialQueryPort
from app.modules.schema.contracts.spatial_reference_contracts import (
    CandidateSet, SpatialReferenceSpec,
)


class KGSpatialQueryAdapter(SpatialQueryPort):
    def __init__(self, kg):
        self._kg = kg

    def resolve_candidates(self, run_id: str, spec: SpatialReferenceSpec) -> CandidateSet:
        try:
            from app.modules.kg.queries.spatial_ref import resolve_candidates
            return resolve_candidates(self._kg, spec)
        except Exception:
            return CandidateSet()

    def query_by_bbox(self, run_id: str, bbox: tuple[float, float, float, float]) -> list[dict[str, Any]]:
        # Geometry queries are Wave-G-deferred (not needed by GROUND thin orchestrator).
        return []

    def query_by_geometry(self, run_id: str, wkt: str) -> list[dict[str, Any]]:
        # Geometry queries are Wave-G-deferred (not needed by GROUND thin orchestrator).
        return []

    def compute_overlap(self, run_id: str, wkt_a: str, wkt_b: str) -> float:
        # Geometry queries are Wave-G-deferred (not needed by GROUND thin orchestrator).
        return 0.0

    def nearest_features(self, run_id: str, wkt: str, layer: str, k: int = 5) -> list[dict[str, Any]]:
        # Geometry queries are Wave-G-deferred (not needed by GROUND thin orchestrator).
        return []
