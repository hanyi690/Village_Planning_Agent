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


def test_suitability_role_policy_distinguishes_site_footprint_from_overlay() -> None:
    source = box(0.0, 0.0, 400.0, 200.0)
    parcel = SimpleNamespace(
        bsm="P-ROLE",
        geometry=source,
        area_sqm=80_000.0,
    )

    class Context:
        workspace = SimpleNamespace(
            metadata=SimpleNamespace(crs="EPSG:3857"),
            lines={"roads_current": []},
            points={"facilities_current": [], "hazard_points": []},
            polygons={
                "farmland_protection": [
                    SimpleNamespace(
                        geometry={
                            "type": "Polygon",
                            "coordinates": [list(box(0.0, 0.0, 150.0, 200.0).exterior.coords)],
                        }
                    )
                ],
                "ecological_redline": [],
            },
            tables=SimpleNamespace(population=None),
            rasters={},
        )
        constraint_index = None

        def current_parcels(self):
            return [parcel]

    grounding = GroundingResult(
        candidates=[
            CandidateSite(
                site_id="site:overlay",
                target_ref="T-OVERLAY",
                source_parcels=["P-ROLE"],
                available_geometry_wkt=source.wkt,
                hard_constraint_result=HardConstraintResult(passed=True),
            ),
            CandidateSite(
                site_id="site:footprint",
                target_ref="T-SITE",
                source_parcels=["P-ROLE"],
                available_geometry_wkt=source.wkt,
                hard_constraint_result=HardConstraintResult(passed=True),
            ),
        ]
    )
    intent = SimpleNamespace(
        site_area_targets=[
            SimpleNamespace(
                target_id="T-OVERLAY",
                expected_output_kind="polygon",
                materialization_role="protection_overlay",
                footprint_area_m2=None,
                area_ha=None,
            ),
            SimpleNamespace(
                target_id="T-SITE",
                expected_output_kind="polygon",
                materialization_role="site_footprint",
                footprint_area_m2=6_000.0,
                area_ha=None,
            ),
        ],
        zone_targets=[],
    )

    surface = build_suitability_surface(grounding, Context(), plan_intent=intent)
    by_target = {candidate.target_id: candidate for candidate in surface.candidates}

    overlay = by_target["T-OVERLAY"]
    site = by_target["T-SITE"]

    assert overlay.materialization_role == "protection_overlay"
    assert overlay.role_policy_key == "materialization_role_policy_v1:protection_overlay"
    assert "FARMLAND_PROTECTION_OVERLAP" not in overlay.exclusion_reasons
    assert any(
        factor["factor_code"] == "FARMLAND_PROTECTION_OVERLAP"
        and factor["policy"] == "overlay_constraint"
        and factor["triggered"] is True
        and factor["hard_exclusion"] is False
        for factor in overlay.hard_constraint_factors
    )

    assert site.materialization_role == "site_footprint"
    assert site.role_policy_key == "materialization_role_policy_v1:site_footprint"
    assert site.hard_feasible is False
    assert "FARMLAND_PROTECTION_OVERLAP" in site.exclusion_reasons
    assert any(
        factor["factor_code"] == "FARMLAND_PROTECTION_OVERLAP"
        and factor["policy"] == "site_hard_exclusion"
        and factor["triggered"] is True
        and factor["hard_exclusion"] is True
        for factor in site.hard_constraint_factors
    )
    assert surface.provenance["materialization_role_policy_version"] == (
        "materialization_role_policy_v1"
    )


def test_suitability_fails_closed_when_materialization_role_is_missing() -> None:
    source = box(0.0, 0.0, 200.0, 200.0)
    parcel = SimpleNamespace(
        bsm="P-UNKNOWN-ROLE",
        geometry=source,
        area_sqm=40_000.0,
    )

    class Context:
        workspace = SimpleNamespace(
            metadata=SimpleNamespace(crs="EPSG:3857"),
            lines={"roads_current": []},
            points={"facilities_current": [], "hazard_points": []},
            polygons={"farmland_protection": [], "ecological_redline": []},
            tables=SimpleNamespace(population=None),
            rasters={},
        )
        constraint_index = None

        def current_parcels(self):
            return [parcel]

    grounding = GroundingResult(
        candidates=[
            CandidateSite(
                site_id="site:unknown-role",
                target_ref="T-UNKNOWN",
                source_parcels=["P-UNKNOWN-ROLE"],
                available_geometry_wkt=source.wkt,
                hard_constraint_result=HardConstraintResult(passed=True),
            )
        ]
    )
    intent = SimpleNamespace(
        site_area_targets=[
            SimpleNamespace(
                target_id="T-UNKNOWN",
                expected_output_kind="polygon",
                materialization_role=None,
                footprint_area_m2=6_000.0,
                area_ha=None,
            )
        ],
        zone_targets=[],
    )

    surface = build_suitability_surface(grounding, Context(), plan_intent=intent)
    candidate = surface.candidates[0]

    assert candidate.materialization_role == "unknown"
    assert candidate.hard_feasible is False
    assert "MATERIALIZATION_ROLE_POLICY_UNAVAILABLE" in candidate.exclusion_reasons
    assert any(
        factor["factor_code"] == "MATERIALIZATION_ROLE_POLICY_UNAVAILABLE"
        and factor["policy"] == "site_hard_exclusion"
        and factor["triggered"] is True
        and factor["hard_exclusion"] is True
        for factor in candidate.hard_constraint_factors
    )
    assert candidate.evaluation_trace[0]["result"] == "fail_closed"


def test_context_free_overlay_applies_role_policy_to_structured_failure() -> None:
    grounding = GroundingResult(
        candidates=[
            CandidateSite(
                site_id="site:context-free-overlay",
                target_ref="T-CONTEXT-FREE-OVERLAY",
                source_parcels=["P-CONTEXT-FREE-OVERLAY"],
                hard_constraint_factors=[
                    {
                        "factor_code": "FARMLAND_PROTECTION_OVERLAP",
                        "triggered": True,
                    }
                ],
                hard_constraint_result=HardConstraintResult(
                    passed=False,
                    violation_detail="farmland protection overlap",
                ),
            )
        ]
    )
    intent = SimpleNamespace(
        site_area_targets=[
            SimpleNamespace(
                target_id="T-CONTEXT-FREE-OVERLAY",
                materialization_role="functional_overlay",
            )
        ],
        zone_targets=[],
    )

    surface = build_suitability_surface(grounding, plan_intent=intent)
    candidate = surface.candidates[0]

    assert candidate.materialization_role == "functional_overlay"
    assert candidate.hard_feasible is True
    assert "FARMLAND_PROTECTION_OVERLAP" not in candidate.exclusion_reasons
    factor = next(
        item
        for item in candidate.hard_constraint_factors
        if item["factor_code"] == "FARMLAND_PROTECTION_OVERLAP"
    )
    assert factor["policy"] == "overlay_constraint"
    assert factor["hard_exclusion"] is False
    assert surface.provenance == {
        "materialization_role_policy_version": "materialization_role_policy_v1",
        "evaluated_materialization_roles": ["functional_overlay"],
    }


def test_context_free_overlay_without_role_aware_factors_is_deferred() -> None:
    grounding = GroundingResult(
        candidates=[
            CandidateSite(
                site_id="site:context-free-deferred",
                target_ref="T-CONTEXT-FREE-DEFERRED",
                source_parcels=["P-CONTEXT-FREE-DEFERRED"],
                hard_constraint_result=HardConstraintResult(
                    passed=False,
                    violation_detail="prohibited constraint overlap",
                ),
            )
        ]
    )
    intent = SimpleNamespace(
        site_area_targets=[
            SimpleNamespace(
                target_id="T-CONTEXT-FREE-DEFERRED",
                materialization_role="restoration_overlay",
            )
        ],
        zone_targets=[],
    )

    candidate = build_suitability_surface(
        grounding, plan_intent=intent
    ).candidates[0]

    assert candidate.hard_feasible is False
    assert "HARD_CONSTRAINT_EVALUATION_DEFERRED" in candidate.exclusion_reasons
    assert "hard_constraints_not_proven" not in candidate.exclusion_reasons
    deferred = next(
        item
        for item in candidate.hard_constraint_factors
        if item["factor_code"] == "HARD_CONSTRAINT_EVALUATION_DEFERRED"
    )
    assert deferred["policy"] == "overlay_constraint"
    assert deferred["hard_exclusion"] is False
    assert candidate.evaluation_trace[-1]["result"] == "deferred"


@pytest.mark.parametrize(
    "materialization_role",
    [
        "site_footprint",
        "land_use_assignment",
        "functional_overlay",
        "protection_overlay",
        "restoration_overlay",
        "unknown",
    ],
)
@pytest.mark.parametrize(
    ("factor_code", "expected_policy"),
    [
        ("HAZARD_POINT_BUFFER", "overlay_constraint"),
        ("farmland_protection", "overlay_constraint"),
        ("ROAD_ACCESS_DISTANCE", "advisory"),
        ("EXISTING_FACILITY_PROXIMITY", "advisory"),
    ],
)
def test_context_free_role_factor_matrix_is_closed_and_fail_closed(
    materialization_role: str,
    factor_code: str,
    expected_policy: str,
) -> None:
    grounding = GroundingResult(
        candidates=[
            CandidateSite(
                site_id=f"site:matrix:{materialization_role}:{factor_code}",
                target_ref="T-CONTEXT-FREE-MATRIX",
                source_parcels=["P-CONTEXT-FREE-MATRIX"],
                hard_constraint_factors=[
                    {"factor_code": factor_code, "triggered": True}
                ],
                hard_constraint_result=HardConstraintResult(passed=False),
            )
        ]
    )
    role_value = (
        materialization_role
        if materialization_role != "unknown"
        else "unknown_role_from_provider"
    )
    intent = SimpleNamespace(
        site_area_targets=[
            SimpleNamespace(
                target_id="T-CONTEXT-FREE-MATRIX",
                materialization_role=role_value,
            )
        ],
        zone_targets=[],
    )

    candidate = build_suitability_surface(
        grounding, plan_intent=intent
    ).candidates[0]
    factor = next(
        item
        for item in candidate.hard_constraint_factors
        if item["factor_code"] == factor_code
        or (
            factor_code == "HAZARD_POINT_BUFFER"
            and item["factor_code"] == "HAZARD_POINT_BUFFER"
        )
    )

    if materialization_role == "unknown":
        assert candidate.hard_feasible is False
        assert factor["policy"] == "site_hard_exclusion"
        assert factor["hard_exclusion"] is True
        assert "MATERIALIZATION_ROLE_POLICY_UNAVAILABLE" in (
            candidate.exclusion_reasons
        )
        assert candidate.evaluation_trace[-1]["result"] == "fail_closed"
        return

    expected_factor_policy = (
        "site_hard_exclusion"
        if expected_policy != "advisory"
        and materialization_role in {"site_footprint", "land_use_assignment"}
        else expected_policy
    )
    assert factor["policy"] == expected_factor_policy
    if expected_policy == "advisory":
        assert factor["hard_exclusion"] is False
        assert candidate.hard_feasible is False
        assert candidate.evaluation_trace[-1]["result"] == (
            "deferred"
            if materialization_role.endswith("overlay")
            else "failed"
        )
    elif materialization_role.endswith("overlay"):
        assert factor["hard_exclusion"] is False
        assert candidate.hard_feasible is True
        assert candidate.evaluation_trace[-1]["result"] == "passed_by_role_policy"
    else:
        assert factor["hard_exclusion"] is True
        assert candidate.hard_feasible is False
        assert factor_code in candidate.exclusion_reasons
        assert candidate.evaluation_trace[-1]["result"] == "failed"


def test_context_free_unknown_factor_never_uses_overlay_default() -> None:
    grounding = GroundingResult(
        candidates=[
            CandidateSite(
                site_id="site:context-free-unknown-factor",
                target_ref="T-CONTEXT-FREE-UNKNOWN-FACTOR",
                source_parcels=["P-CONTEXT-FREE-UNKNOWN-FACTOR"],
                hard_constraint_factors=[
                    {"factor_code": "UNRECOGNIZED_FACTOR", "triggered": True}
                ],
                hard_constraint_result=HardConstraintResult(passed=False),
            )
        ]
    )
    intent = SimpleNamespace(
        site_area_targets=[
            SimpleNamespace(
                target_id="T-CONTEXT-FREE-UNKNOWN-FACTOR",
                materialization_role="functional_overlay",
            )
        ],
        zone_targets=[],
    )

    candidate = build_suitability_surface(
        grounding, plan_intent=intent
    ).candidates[0]
    factor = next(
        item
        for item in candidate.hard_constraint_factors
        if item["factor_code"] == "UNKNOWN_HARD_CONSTRAINT_FACTOR"
    )

    assert candidate.hard_feasible is False
    assert factor["policy"] == "site_hard_exclusion"
    assert factor["hard_exclusion"] is True
    assert "UNKNOWN_HARD_CONSTRAINT_FACTOR" in candidate.exclusion_reasons
    assert candidate.evaluation_trace[-1]["result"] == "failed"


def test_context_backed_missing_parcel_keeps_role_failure_separate() -> None:
    source = box(0.0, 0.0, 20.0, 20.0)

    class Context:
        workspace = SimpleNamespace(
            metadata=SimpleNamespace(crs="EPSG:3857"),
            lines={"roads_current": []},
            points={"facilities_current": [], "hazard_points": []},
            polygons={"farmland_protection": [], "ecological_redline": []},
            tables=SimpleNamespace(population=None),
            rasters={},
        )
        constraint_index = None

        def current_parcels(self):
            return []

    grounding = GroundingResult(
        candidates=[
            CandidateSite(
                site_id="site:missing-parcel",
                target_ref="T-MISSING-PARCEL",
                source_parcels=["P-MISSING-PARCEL"],
                available_geometry_wkt=source.wkt,
                hard_constraint_result=HardConstraintResult(passed=True),
            )
        ]
    )
    intent = SimpleNamespace(
        site_area_targets=[
            SimpleNamespace(
                target_id="T-MISSING-PARCEL",
                materialization_role="unknown_future_overlay",
                expected_output_kind="polygon",
            )
        ],
        zone_targets=[],
    )

    candidate = build_suitability_surface(
        grounding, Context(), plan_intent=intent
    ).candidates[0]

    assert candidate.materialization_role == "unknown"
    assert candidate.role_policy_key == ""
    assert candidate.hard_feasible is False
    assert "MATERIALIZATION_ROLE_POLICY_UNAVAILABLE" in candidate.exclusion_reasons
    assert "CANDIDATE_SOURCE_PARCEL_NOT_FOUND:P-MISSING-PARCEL" in (
        candidate.exclusion_reasons
    )
    assert any(
        factor["factor_code"] == "MATERIALIZATION_ROLE_POLICY_UNAVAILABLE"
        for factor in candidate.hard_constraint_factors
    )
    assert candidate.evaluation_trace[0]["result"] == "fail_closed"
    assert candidate.evaluation_trace[-1]["result"] == "missing"


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
                identity_confidence=0.9,
                geometry_confidence=0.9,
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
