"""Contract tests for spatial reference DSL (closed-set, Pydantic-validated)."""
import pytest
from pydantic import ValidationError


def test_ref_object_entity_type_kind():
    from app.modules.schema.contracts.spatial_ref_contracts import RefObject
    ro = RefObject(kind="entity_type", filter={"label_contains": "\u5b66\u6821"})
    assert ro.kind == "entity_type"
    assert ro.filter == {"label_contains": "\u5b66\u6821"}


def test_ref_object_kind_closed_set():
    from app.modules.schema.contracts.spatial_ref_contracts import RefObject
    with pytest.raises(ValidationError):
        RefObject(kind="invalid_kind")


def test_spatial_reference_spec_directional():
    from app.modules.schema.contracts.spatial_ref_contracts import SpatialReferenceSpec, RefObject
    spec = SpatialReferenceSpec(
        type="directional",
        reference=RefObject(kind="village"),
        direction="E",
    )
    assert spec.type == "directional"
    assert spec.direction == "E"
    assert spec.topo is None


def test_spatial_reference_spec_topological_closed_set():
    from app.modules.schema.contracts.spatial_ref_contracts import SpatialReferenceSpec
    spec = SpatialReferenceSpec(type="topological", topo="sfTouches")
    assert spec.topo == "sfTouches"
    with pytest.raises(ValidationError):
        SpatialReferenceSpec(type="topological", topo="invalid_relation")


def test_spatial_reference_spec_composed_children():
    from app.modules.schema.contracts.spatial_ref_contracts import SpatialReferenceSpec
    child = SpatialReferenceSpec(type="attributive", attr_filter={"dlbm_in": ["0301", "0302"]})
    parent = SpatialReferenceSpec(type="composed", op="and", children=[child])
    assert parent.children[0].type == "attributive"


def test_candidate_set_dataclass():
    from app.modules.schema.contracts.spatial_ref_contracts import CandidateSet
    cs = CandidateSet(bsms=["P001", "P002"], ref_bsms=["F001"])
    assert cs.bsms == ["P001", "P002"]
    assert cs.ref_bsms == ["F001"]
    assert cs.ref_geometry_wkt is None


def test_resolved_spatial_ref_dataclass():
    from app.modules.schema.contracts.spatial_ref_contracts import ResolvedSpatialRef
    r = ResolvedSpatialRef(
        final_bsms=["P001"],
        bbox=[113.0, 23.0, 113.5, 23.5],
        reference_geometry_wkt="POINT(113.25 23.25)",
        confidence=0.9,
        provenance={"spec_type": "directional", "decided_by": "rule"},
    )
    assert r.final_bsms == ["P001"]
    assert r.confidence == 0.9