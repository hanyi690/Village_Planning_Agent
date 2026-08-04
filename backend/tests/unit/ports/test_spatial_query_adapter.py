from __future__ import annotations

from app.modules.kg.adapters.spatial_query_adapter import KGSpatialQueryAdapter
from app.modules.schema.contracts.spatial_reference_contracts import (
    CandidateSet, RefObject, SpatialReferenceSpec,
)


def test_resolve_candidates_attributive(kg):
    adapter = KGSpatialQueryAdapter(kg)
    spec = SpatialReferenceSpec(type="attributive", attr_filter={"dlbm_in": ["0101"]})
    result = adapter.resolve_candidates("run-1", spec)
    assert isinstance(result, CandidateSet)
    assert "P001" in result.bsms


def test_resolve_candidates_topological(kg):
    adapter = KGSpatialQueryAdapter(kg)
    spec = SpatialReferenceSpec(
        type="topological",
        reference=RefObject(kind="entity_type", filter={"rdf_type": "Road"}),
        topo="sfTouches",
    )
    result = adapter.resolve_candidates("run-1", spec)
    assert "P002" in result.bsms


def test_stubs_return_empty(kg):
    adapter = KGSpatialQueryAdapter(kg)
    assert adapter.query_by_bbox("run-1", (0.0, 0.0, 1.0, 1.0)) == []
    assert adapter.query_by_geometry("run-1", "POINT(0 0)") == []
    assert adapter.nearest_features("run-1", "POINT(0 0)", "Parcel") == []
    assert adapter.compute_overlap("run-1", "POINT(0 0)", "POINT(1 1)") == 0.0


def test_resolve_candidates_fails_gracefully():
    adapter = KGSpatialQueryAdapter(None)
    spec = SpatialReferenceSpec(type="attributive", attr_filter={"dlbm_in": ["0101"]})
    result = adapter.resolve_candidates("run-1", spec)
    assert isinstance(result, CandidateSet)
    assert result.bsms == []
