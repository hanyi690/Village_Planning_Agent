from __future__ import annotations

from types import SimpleNamespace

from app.contracts.spatial.spatial_reference_contracts import (
    ResolvedSpatialRef,
    SpatialReferenceSpec,
)
from app.domain.ground.aggregate import build_candidate_site
from app.domain.ground.candidate_domain_builder import build_candidate_domains


def _empty_context() -> SimpleNamespace:
    return SimpleNamespace(current_parcels=lambda: [])


def test_exact_point_is_a_candidate_without_parcel_area() -> None:
    candidate = build_candidate_site(
        SpatialReferenceSpec(type="place_name", target_id="facility-1"),
        ResolvedSpatialRef(
            reference_geometry_wkt="POINT (116 23)",
            confidence=0.95,
            provenance={"path": "kg:facility:1"},
        ),
        0,
        _empty_context(),
        target_kind="facility",
        expected_output_kind="point",
    )

    domains = build_candidate_domains([candidate])
    assert candidate.available_area_ha == 0
    assert candidate.geometry is not None
    # A facility point is an executable planning geometry even without a
    # positive-area parcel; generic place anchors remain candidate-only.
    assert candidate.geometry.role == "execution_geometry"
    assert domains[0].candidate_ids == [candidate.geometry.candidate_id]
    assert domains[0].status == "resolved"


def test_exact_line_is_a_candidate_without_parcel_area() -> None:
    candidate = build_candidate_site(
        SpatialReferenceSpec(type="directional", target_id="road-1"),
        ResolvedSpatialRef(
            reference_geometry_wkt="LINESTRING (116 23, 116.01 23.01)",
            confidence=0.9,
            provenance={"path": "network:road:1"},
        ),
        0,
        _empty_context(),
        target_kind="road",
        expected_output_kind="line",
    )

    domains = build_candidate_domains([candidate])
    assert candidate.available_area_ha == 0
    assert candidate.geometry is not None
    assert candidate.geometry.role == "execution_geometry"
    assert candidate.geometry.is_executable is True
    assert domains[0].status == "resolved"
