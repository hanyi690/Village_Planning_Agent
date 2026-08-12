"""Spatial query port - geometry and spatial-reference query boundary.

Implemented by kg-side adapters (KG spatial reference resolution) and
consumed by spatial_ops / agent layers.  This is the synchronous, KG-bound
spatial read protocol; ``app.contracts.ports.spatial.SpatialQueryPort`` is the
async workspace-based read boundary (blueprint M2) and stays distinct.
"""
from __future__ import annotations

from typing import Any, Protocol

from app.contracts.spatial.spatial_reference_contracts import (
    CandidateSet, SpatialReferenceSpec,
)


class SpatialQueryPort(Protocol):
    def query_by_bbox(self, run_id: str, bbox: tuple[float, float, float, float]) -> list[dict[str, Any]]: ...
    def query_by_geometry(self, run_id: str, wkt: str) -> list[dict[str, Any]]: ...
    def compute_overlap(self, run_id: str, wkt_a: str, wkt_b: str) -> float: ...
    def nearest_features(self, run_id: str, wkt: str, layer: str, k: int = 5) -> list[dict[str, Any]]: ...
    def resolve_candidates(self, run_id: str, spec: SpatialReferenceSpec) -> CandidateSet: ...


__all__ = ["SpatialQueryPort"]
