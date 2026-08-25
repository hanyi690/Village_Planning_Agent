from __future__ import annotations

from types import SimpleNamespace

from app.contracts.spatial.spatial_reference_contracts import (
    ResolvedSpatialRef,
    SpatialReferenceSpec,
)
from app.contracts.spatial.grounded_problem import (
    GroundedCandidateDomain,
    GroundedPlanningProblem,
    GroundedTargetDomain,
)
from app.contracts.spatial.candidate_geometry import CandidateGeometry
from app.domain.allocation.refined_candidate_catalog import refine_grounded_problem
from app.domain.ground.aggregate import build_candidate_sites
from app.domain.ground.candidate_domain_builder import build_candidate_domains
from app.domain.suitability.model import SuitabilityCandidate, SuitabilitySurface


def _context() -> SimpleNamespace:
    return SimpleNamespace(
        constraint_index=None,
        current_parcels=lambda: [
            SimpleNamespace(
                bsm="P-1",
                area_sqm=10000,
                geometry={
                    "type": "Polygon",
                    "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]],
                },
            ),
            SimpleNamespace(
                bsm="P-2",
                area_sqm=10000,
                geometry={
                    "type": "Polygon",
                    "coordinates": [[[2, 0], [3, 0], [3, 1], [2, 1], [2, 0]]],
                },
            ),
        ],
    )


def test_precise_multi_parcel_resolution_exposes_independent_parcel_alternatives() -> None:
    candidates = build_candidate_sites(
        SpatialReferenceSpec(type="place_name", target_id="facility-1"),
        ResolvedSpatialRef(
            final_bsms=["P-1", "P-2"],
            spatial_domain_kind="parcel_set",
            confidence=0.7,
            provenance={"path": "evidence:candidates"},
        ),
        0,
        _context(),
        target_kind="facility",
        expected_output_kind="point",
    )

    assert [candidate.source_parcels for candidate in candidates] == [["P-1"], ["P-2"]]
    assert [candidate.geometry.generation_operation for candidate in candidates] == [
        "grounded_parcel_alternative",
        "grounded_parcel_alternative",
    ]
    assert all(candidate.geometry.wkt.startswith("POLYGON") for candidate in candidates)
    assert all(candidate.geometry.role == "parcel_candidate" for candidate in candidates)
    assert all(candidate.geometry.is_executable is False for candidate in candidates)
    assert all(candidate.metrics["candidate_variant"] == "parcel" for candidate in candidates)
    assert all(candidate.geometry.hard_constraint_status == "pending" for candidate in candidates)


def test_parcel_set_domain_is_not_collapsed_before_constraint_evaluation() -> None:
    """A parcel-set recall result must be evaluated one parcel at a time."""

    class _Overlap:
        constraint_type = "farmland_protection"

    class _ConstraintIndex:
        def geometry_in_constraint(self, geometry):
            return [_Overlap()] if geometry["coordinates"][0][0][0] < 1.5 else []

    context = _context()
    context.constraint_index = _ConstraintIndex()
    candidates = build_candidate_sites(
        SpatialReferenceSpec(type="place_name", target_id="facility-2"),
        ResolvedSpatialRef(
            final_bsms=["P-1", "P-2"],
            spatial_domain_kind="parcel_set",
            confidence=0.7,
            provenance={"path": "l1:parcel_set"},
        ),
        0,
        context,
        target_kind="facility",
        expected_output_kind="point",
    )

    assert [candidate.source_parcels for candidate in candidates] == [["P-1"], ["P-2"]]
    assert [candidate.geometry.hard_constraint_status for candidate in candidates] == [
        "failed",
        "passed",
    ]


def test_explicit_point_geometry_is_not_replaced_by_parcel_alternatives() -> None:
    candidates = build_candidate_sites(
        SpatialReferenceSpec(type="place_name", target_id="facility-1"),
        ResolvedSpatialRef(
            final_bsms=["P-1", "P-2"],
            reference_geometry_wkt="POINT (0.5 0.5)",
            confidence=0.95,
            provenance={"path": "kg:facility"},
        ),
        0,
        _context(),
        target_kind="facility",
        expected_output_kind="point",
    )

    assert len(candidates) == 1
    assert candidates[0].geometry.kind == "point"
    assert candidates[0].geometry.granularity == "exact_feature"
    assert candidates[0].geometry.generation_operation == "grounded_candidate"


def test_parcel_alternatives_keep_independent_hard_constraint_results() -> None:
    class _Overlap:
        constraint_type = "farmland_protection"

    class _ConstraintIndex:
        def geometry_in_constraint(self, geometry):
            # Only the western parcel is prohibited in this fixture.
            return [_Overlap()] if geometry["coordinates"][0][0][0] < 1.5 else []

    context = _context()
    context.constraint_index = _ConstraintIndex()
    candidates = build_candidate_sites(
        SpatialReferenceSpec(type="place_name", target_id="site-1"),
        ResolvedSpatialRef(
            final_bsms=["P-1", "P-2"],
            confidence=0.7,
            uncertainty_reason="grounded_anchor",
            provenance={"path": "evidence:candidates"},
        ),
        0,
        context,
        target_kind="site_area",
        expected_output_kind="polygon",
    )

    assert [candidate.geometry.hard_constraint_status for candidate in candidates] == [
        "failed",
        "passed",
    ]
    assert "farmland_protection" in candidates[0].hard_constraint_result.violation_detail


def test_failed_authoritative_polygon_is_downgraded_to_candidate_only() -> None:
    class _Overlap:
        constraint_type = "farmland_protection"

    class _ConstraintIndex:
        def geometry_in_constraint(self, geometry):
            return [_Overlap()]

    context = _context()
    context.constraint_index = _ConstraintIndex()
    candidates = build_candidate_sites(
        SpatialReferenceSpec(type="place_name", target_id="site-1"),
        ResolvedSpatialRef(
            final_bsms=["P-1"],
            reference_geometry_wkt="POLYGON ((0 0, 1 0, 1 1, 0 1, 0 0))",
            confidence=0.9,
            provenance={"path": "kg:site"},
        ),
        0,
        context,
        target_kind="site_area",
        expected_output_kind="polygon",
    )

    assert candidates[0].geometry.hard_constraint_status == "failed"
    assert candidates[0].geometry.role == "parcel_candidate"
    assert candidates[0].geometry.is_executable is False
    assert build_candidate_domains(candidates)[0].status == "candidate_only"


def test_select_refinement_only_promotes_hard_feasible_parcel_and_keeps_lineage() -> None:
    class _Overlap:
        constraint_type = "farmland_protection"

    class _ConstraintIndex:
        def geometry_in_constraint(self, geometry):
            return [_Overlap()] if geometry["coordinates"][0][0][0] < 1.5 else []

    context = _context()
    context.constraint_index = _ConstraintIndex()
    candidates = build_candidate_sites(
        SpatialReferenceSpec(type="place_name", target_id="site-1"),
        ResolvedSpatialRef(
            final_bsms=["P-1", "P-2"],
            confidence=0.7,
            provenance={"path": "evidence:candidates"},
        ),
        0,
        context,
        target_kind="site_area",
        expected_output_kind="polygon",
    )
    assert all(candidate.geometry.role == "parcel_candidate" for candidate in candidates)
    assert all(candidate.geometry.is_executable is False for candidate in candidates)
    problem = GroundedPlanningProblem(
        target_domains=[
            GroundedTargetDomain(
                target_id="site-1",
                target_kind="site_area",
                expected_output_kind="polygon",
                status="candidate_only",
            )
        ],
        candidate_domains=build_candidate_domains(candidates),
        candidate_geometries=[candidate.geometry for candidate in candidates],
    )
    surface = SuitabilitySurface(
        candidates=[
            SuitabilityCandidate(
                candidate_id="suitability:P-1",
                target_id="site-1",
                source_parcels=["P-1"],
                available_geometry_wkt=candidates[0].available_geometry_wkt,
                hard_feasible=False,
                exclusion_reasons=["farmland constraint"],
                evidence_refs=["suitability:P-1"],
                feature_ref="feature:P-1",
            ),
            SuitabilityCandidate(
                candidate_id="suitability:P-2",
                target_id="site-1",
                source_parcels=["P-2"],
                available_geometry_wkt=candidates[1].available_geometry_wkt,
                hard_feasible=True,
                evidence_refs=["suitability:P-2"],
                feature_ref="feature:P-2",
            ),
        ]
    )

    refined = refine_grounded_problem(problem, surface)

    generated = [
        item
        for item in refined.candidate_geometries
        if item.generation_operation == "select_parcel_refinement"
    ]
    by_bsm = {item.source_bsms[0]: item for item in generated}
    assert by_bsm["P-1"].hard_constraint_status == "failed"
    assert by_bsm["P-1"].role == "parcel_candidate"
    assert by_bsm["P-1"].is_executable is False
    assert by_bsm["P-2"].hard_constraint_status == "passed"
    assert by_bsm["P-2"].role == "execution_geometry"
    assert by_bsm["P-2"].is_executable is True
    assert by_bsm["P-2"].source_refs == ["evidence:candidates", "feature:P-2"]
    assert by_bsm["P-2"].evidence_refs == ["P-2", "suitability:P-2"]


def test_select_refinement_does_not_promote_score_into_geometry_confidence() -> None:
    source = CandidateGeometry(
        target_id="site-score-boundary",
        kind="polygon",
        role="parcel_candidate",
        wkt="POLYGON ((0 0, 0.02 0, 0.02 0.02, 0 0.02, 0 0))",
        spatial_domain_kind="parcel_extent",
        source_bsms=["P-SCORE"],
        source_area_ha=1.0,
        identity_confidence=0.45,
        geometry_confidence=0.6,
        source_ref="ground:score-boundary",
        evidence_refs=["ground:score-boundary"],
    )
    problem = GroundedPlanningProblem(
        target_domains=[
            GroundedTargetDomain(
                target_id="site-score-boundary",
                target_kind="site_area",
                expected_output_kind="polygon",
                status="candidate_only",
            )
        ],
        candidate_geometries=[source],
    )
    surface = SuitabilitySurface(
        candidates=[
            SuitabilityCandidate(
                candidate_id="surface:P-SCORE",
                target_id="site-score-boundary",
                source_parcels=["P-SCORE"],
                score=1.8,
                hard_feasible=True,
                available_geometry_wkt=source.wkt,
                available_area_ha=0.4,
                source_area_ha=1.0,
                availability_status="fully_available",
                eligible_area_ha=1.0,
                excluded_area_ha=0.0,
                evidence_refs=["surface:P-SCORE"],
            )
        ]
    )

    refined = refine_grounded_problem(problem, surface)
    selected = next(
        item
        for item in refined.candidate_geometries
        if item.source_bsms == ["P-SCORE"]
        and item.generation_operation == "select_parcel_refinement"
    )

    assert selected.identity_confidence == 0.45
    assert selected.geometry_confidence == 0.6
    assert selected.schema_status == "valid"
    assert selected.suitability_score == 1.8


def test_high_suitability_does_not_close_incomplete_grounding() -> None:
    source = CandidateGeometry(
        target_id="site-grounding-gap",
        kind="polygon",
        role="parcel_candidate",
        wkt="POLYGON ((0 0, 0.02 0, 0.02 0.02, 0 0.02, 0 0))",
        spatial_domain_kind="parcel_extent",
        source_bsms=["P-GAP"],
        source_area_ha=1.0,
        identity_confidence=0.0,
        geometry_confidence=0.0,
        source_ref="ground:gap",
        evidence_refs=["ground:gap"],
    )
    problem = GroundedPlanningProblem(
        target_domains=[
            GroundedTargetDomain(
                target_id="site-grounding-gap",
                target_kind="site_area",
                expected_output_kind="polygon",
                status="candidate_only",
            )
        ],
        candidate_domains=[
            GroundedCandidateDomain(
                target_id="site-grounding-gap",
                candidate_ids=[source.candidate_id],
                candidate_geometry_refs=[source.candidate_id],
                status="candidate_only",
            )
        ],
        candidate_geometries=[source],
    )
    surface = SuitabilitySurface(
        candidates=[
            SuitabilityCandidate(
                candidate_id="surface:P-GAP",
                target_id="site-grounding-gap",
                source_parcels=["P-GAP"],
                score=9.5,
                hard_feasible=True,
                available_geometry_wkt=source.wkt,
                available_area_ha=0.5,
                source_area_ha=1.0,
                availability_status="fully_available",
                eligible_area_ha=1.0,
                excluded_area_ha=0.0,
                evidence_refs=["surface:P-GAP"],
            )
        ]
    )

    refined = refine_grounded_problem(problem, surface)
    selected = next(
        item
        for item in refined.candidate_geometries
        if item.source_bsms == ["P-GAP"]
        and item.generation_operation == "select_parcel_refinement"
    )

    assert selected.role == "execution_geometry"
    assert selected.is_executable is False
    assert refined.candidate_completeness.status == "human_required"
    assert refined.can_solve is False
    assert any(domain.status == "candidate_only" for domain in refined.candidate_domains)
