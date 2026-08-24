import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from shapely import wkt
from shapely.geometry import box, shape

from app.contracts.spatial.grounding_contracts import CandidateSite, GroundingResult, HardConstraintResult
from app.contracts.spatial.candidate_geometry import CandidateGeometry
from app.contracts.spatial.grounded_problem import (
    GroundedCandidateDomain,
    GroundedPlanningProblem,
    GroundedTargetDomain,
)
from app.domain.allocation.refined_candidate_catalog import refine_grounded_problem
from app.domain.suitability.service import build_suitability_surface
from app.domain.suitability.subgeometry import derive_planning_subgeometry
from app.spatial.model.crs_engine import project_geometry


def test_subgeometry_uses_metric_crs_for_wgs84_bundle_geometry() -> None:
    source = box(116.0, 23.0, 116.001, 23.0008)

    result = derive_planning_subgeometry(
        source.wkt,
        source_crs="EPSG:4326",
        target_area_ha=0.6,
    )

    assert result is not None
    assert result.operation == "obb_subdivide"
    assert result.metric_crs.startswith("EPSG:")
    assert 0.5 <= result.planning_area_ha <= 0.7
    assert 0.0 < result.coverage_ratio < 1.0
    assert result.remainder_geometry_wkts
    output = wkt.loads(result.geometry_wkt)
    assert source.buffer(1e-9).covers(output)

    metric_source = project_geometry(source, "EPSG:4326", result.metric_crs)
    metric_output = project_geometry(output, "EPSG:4326", result.metric_crs)
    assert metric_output.area <= metric_source.area


def test_subgeometry_applies_allowed_and_avoid_geometry_before_split() -> None:
    source = box(0.0, 0.0, 100.0, 100.0)
    result = derive_planning_subgeometry(
        source.wkt,
        source_crs="EPSG:3857",
        target_area_ha=0.5,
        allowed_geometry_wkt=box(0.0, 0.0, 100.0, 80.0).wkt,
        avoid_geometry_wkts=[box(0.0, 0.0, 20.0, 80.0).wkt],
    )

    assert result is not None
    assert result.feasible
    assert "intersected_allowed_geometry" in result.diagnostics
    assert "subtracted_avoid_geometry" in result.diagnostics
    assert result.availability_status == "partially_available"
    assert result.eligible_area_ha > 0
    assert result.excluded_area_ha > 0
    output = wkt.loads(result.geometry_wkt)
    assert output.intersection(box(0.0, 0.0, 20.0, 80.0)).area == 0.0
    assert result.planning_area_ha <= 0.5 * 1.05


def test_subgeometry_fails_closed_when_requested_area_is_unavailable() -> None:
    result = derive_planning_subgeometry(
        box(0.0, 0.0, 100.0, 100.0).wkt,
        source_crs="EPSG:3857",
        target_area_ha=2.0,
    )

    assert result is not None
    assert not result.feasible
    assert result.geometry_wkt
    assert "planning_area_insufficient" in result.diagnostics


def test_subgeometry_rejects_irregular_obb_sliver_instead_of_approving_it() -> None:
    payload = json.loads(
        (
            Path(__file__).parents[1]
            / "fixtures/mvp_village/gis/landuse.geojson"
        ).read_text(encoding="utf-8")
    )
    source = shape(next(
        feature["geometry"]
        for feature in payload["features"]
        if str(feature.get("properties", {}).get("BSM"))
        == "441426211000049353"
    ))

    result = derive_planning_subgeometry(
        source.wkt,
        source_crs="EPSG:4326",
        target_area_ha=2.0,
        tolerance_pct=5.0,
    )

    assert result is not None
    assert result.operation == "obb_subdivide"
    assert result.planning_area_ha < 2.0 * 0.95
    assert "planning_area_insufficient" in result.diagnostics
    assert not result.feasible


def test_subgeometry_distinguishes_fully_unavailable_from_partial_overlap() -> None:
    result = derive_planning_subgeometry(
        box(0.0, 0.0, 100.0, 100.0).wkt,
        source_crs="EPSG:3857",
        avoid_geometry_wkts=[box(0.0, 0.0, 100.0, 100.0).wkt],
    )

    assert result is not None
    assert result.availability_status == "fully_unavailable"
    assert result.eligible_area_ha == 0.0
    assert result.excluded_area_ha == result.source_area_ha
    assert not result.feasible


def test_fully_unavailable_candidate_cannot_become_execution_geometry() -> None:
    candidate = CandidateGeometry(
        target_id="T-UNAVAILABLE",
        kind="polygon",
        role="execution_geometry",
        wkt=box(0.0, 0.0, 10.0, 10.0).wkt,
        availability_status="fully_unavailable",
        eligible_area_ha=0.0,
        excluded_area_ha=1.0,
    )

    assert not candidate.is_executable


def test_candidate_rejects_contradictory_availability_areas() -> None:
    with pytest.raises(ValueError, match="fully_unavailable candidate"):
        CandidateGeometry(
            target_id="T-CONTRADICTORY",
            kind="polygon",
            role="execution_geometry",
            wkt=box(0.0, 0.0, 10.0, 10.0).wkt,
            availability_status="fully_unavailable",
            planning_area_ha=0.1,
        )
    with pytest.raises(ValueError, match="eligible_area_ha cannot exceed"):
        CandidateGeometry(
            target_id="T-OVERFLOW",
            kind="polygon",
            role="execution_geometry",
            wkt=box(0.0, 0.0, 10.0, 10.0).wkt,
            source_area_ha=1.0,
            eligible_area_ha=1.1,
            availability_status="partially_available",
        )
    with pytest.raises(ValueError, match="planning_area_ha cannot exceed eligible_area_ha"):
        CandidateGeometry(
            target_id="T-PLANNING-OVERFLOW",
            kind="polygon",
            role="execution_geometry",
            wkt=box(0.0, 0.0, 10.0, 10.0).wkt,
            source_area_ha=1.0,
            planning_area_ha=0.8,
            eligible_area_ha=0.6,
            excluded_area_ha=0.4,
            availability_status="partially_available",
        )


def test_unknown_parcel_availability_cannot_become_execution_geometry() -> None:
    candidate = CandidateGeometry(
        target_id="T-UNKNOWN",
        kind="polygon",
        role="execution_geometry",
        spatial_domain_kind="parcel_extent",
        wkt=box(0.0, 0.0, 10.0, 10.0).wkt,
        source_bsms=["P-UNKNOWN"],
        availability_status="unknown",
    )

    assert not candidate.is_executable


def test_suitability_promotes_clipped_geometry_for_site_area_target() -> None:
    source = box(0.0, 0.0, 400.0, 200.0)
    parcel = SimpleNamespace(
        bsm="P-LARGE",
        geometry={
            "type": "Polygon",
            "coordinates": [list(source.exterior.coords)],
        },
        area_sqm=80_000.0,
    )

    class Context:
        workspace = SimpleNamespace(
            metadata=SimpleNamespace(crs="EPSG:3857"),
            lines={"roads_current": []},
            points={"facilities_current": [], "hazard_points": []},
            polygons={
                "farmland_protection": [],
                "ecological_redline": [],
            },
            tables=SimpleNamespace(population=None),
            rasters={},
        )

        def current_parcels(self):
            return [parcel]

    grounding = GroundingResult(
        candidates=[
            CandidateSite(
                site_id="site:T1",
                target_ref="T1",
                source_parcels=["P-LARGE"],
                available_geometry_wkt=source.wkt,
                hard_constraint_result=HardConstraintResult(passed=True),
            )
        ]
    )
    intent = SimpleNamespace(
        site_area_targets=[
            SimpleNamespace(
                target_id="T1",
                expected_output_kind="polygon",
                materialization_role="site_footprint",
                footprint_area_m2=6_000.0,
                area_ha=None,
            )
        ],
        zone_targets=[],
    )

    surface = build_suitability_surface(grounding, Context(), plan_intent=intent)

    candidate = surface.candidates[0]
    assert candidate.geometry_operation == "obb_subdivide"
    assert candidate.source_area_ha == 8.0
    assert 0.55 <= candidate.available_area_ha <= 0.65
    assert 0.06 <= candidate.coverage_ratio <= 0.09
    assert wkt.loads(candidate.available_geometry_wkt).area <= source.area


def test_suitability_keeps_partial_parcel_availability_and_neighbor_refs() -> None:
    source = box(0.0, 0.0, 400.0, 200.0)
    neighbor = box(400.0, 0.0, 800.0, 200.0)
    parcel = SimpleNamespace(
        bsm="P-PARTIAL",
        geometry=source,
        area_sqm=80_000.0,
    )
    adjacent = SimpleNamespace(
        bsm="P-NEIGHBOR",
        geometry=neighbor,
        area_sqm=80_000.0,
    )

    class ConstraintRows:
        def iterrows(self):
            yield 0, {"constraint_type": "farmland_protection", "geometry": box(0, 0, 100, 200)}

    class ConstraintIndex:
        _gdf = ConstraintRows()

        def geometry_in_constraint(self, _geometry):
            return []

    class Context:
        workspace = SimpleNamespace(
            metadata=SimpleNamespace(crs="EPSG:3857"),
            lines={"roads_current": []},
            points={"facilities_current": [], "hazard_points": []},
            polygons={"farmland_protection": [], "ecological_redline": []},
            tables=SimpleNamespace(population=None),
            rasters={},
        )
        constraint_index = ConstraintIndex()

        def current_parcels(self):
            return [parcel, adjacent]

    grounding = GroundingResult(
        candidates=[
            CandidateSite(
                site_id="site:partial",
                target_ref="T-PARTIAL",
                source_parcels=["P-PARTIAL"],
                available_geometry_wkt=source.wkt,
                hard_constraint_result=HardConstraintResult(passed=True),
            )
        ]
    )
    intent = SimpleNamespace(
        site_area_targets=[
            SimpleNamespace(
                target_id="T-PARTIAL",
                expected_output_kind="polygon",
                materialization_role="site_footprint",
                footprint_area_m2=6_000.0,
                area_ha=None,
            )
        ],
        zone_targets=[],
    )

    candidate = build_suitability_surface(
        grounding, Context(), plan_intent=intent
    ).candidates[0]

    assert candidate.availability_status == "partially_available"
    assert candidate.eligible_area_ha is not None
    assert candidate.excluded_area_ha is not None
    assert candidate.eligible_area_ha < candidate.source_area_ha
    assert candidate.excluded_area_ha > 0
    assert candidate.adjacent_parcel_bsms == ["P-NEIGHBOR"]
    assert candidate.adjacency_evidence_refs == [
        "bundle:landuse_current:P-PARTIAL:adjacent:P-NEIGHBOR"
    ]


def test_refinement_materializes_facility_parcel_as_executable_point() -> None:
    parcel = box(116.0, 23.0, 116.001, 23.001)
    problem = GroundedPlanningProblem(
        target_domains=[
            GroundedTargetDomain(
                target_id="facility-1",
                target_kind="facility",
                expected_output_kind="point",
                candidate_site_refs=["source:parcel:P1"],
                status="candidate_only",
            )
        ],
        candidate_domains=[
            GroundedCandidateDomain(
                target_id="facility-1",
                candidate_ids=["grounded-1"],
                candidate_geometry_refs=["grounded-1"],
                status="candidate_only",
            )
        ],
        candidate_geometries=[
            CandidateGeometry(
                candidate_id="grounded-1",
                target_id="facility-1",
                kind="polygon",
                role="parcel_candidate",
                wkt=parcel.wkt,
                crs="EPSG:4326",
                granularity="parcel_extent",
                spatial_domain_kind="parcel_extent",
                source_ref="source:parcel:P1",
                source_bsms=["P1"],
                hard_constraint_status="pending",
            )
        ],
    )
    surface = SimpleNamespace(candidates=[SimpleNamespace(
        target_id="facility-1",
        source_parcels=["P1"],
        available_geometry_wkt=parcel.wkt,
        hard_feasible=True,
        score=0.9,
        available_area_ha=0.01,
        geometry_crs="EPSG:4326",
        feature_ref="source:parcel:P1",
        geometry_operation="bundle_extent",
    )])

    refined = refine_grounded_problem(problem, surface)

    assert refined is not None
    executable = [
        item for item in refined.candidate_geometries
        if item.target_id == "facility-1" and item.is_executable
    ]
    assert len(executable) == 1
    assert executable[0].kind == "point"
    assert executable[0].role == "execution_geometry"
    assert executable[0].generation_operation == "select_parcel_representative_point"
    assert wkt.loads(executable[0].wkt).geom_type == "Point"
    assert executable[0].uncertainty_reason == "exact_bsm_refinement"
    assert executable[0].uncertainty_radius_m == 0.0
    assert refined.candidate_domains[0].candidate_ids == [executable[0].candidate_id]
