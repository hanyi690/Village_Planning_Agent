from types import SimpleNamespace

from app.contracts.planning.constraint_factor import ConstraintFactor
from app.contracts.planning.intent_graph import PlanRelationIntent, PlanningIntentGraph
from app.contracts.spatial.spatial_reference_contracts import (
    ResolvedSpatialRef,
    SpatialReferenceSpec,
)
from app.domain.ground.aggregate import build_candidate_site
from app.domain.ground.constraint_factors import (
    compile_constraint_factors,
    evaluate_relation_satisfaction,
)


def _context():
    return SimpleNamespace(
        current_parcels=lambda: [
            SimpleNamespace(
                bsm="P-1",
                geometry={
                    "type": "Polygon",
                    "coordinates":[[[0, 0], [0, 1], [1, 1], [1, 0], [0, 0]]],
                },
                area_sqm=10000,
            )
        ]
    )


def test_line_target_keeps_parcel_union_as_corridor_candidate():
    spec = SpatialReferenceSpec(
        type="directional",
        target_id="sewer-1",
        spec_id="spec-1",
    )
    resolved = ResolvedSpatialRef(
        final_bsms=["P-1"],
        reference_geometry_wkt="POLYGON((0 0,0 1,1 1,1 0,0 0))",
        confidence=0.9,
    )

    candidate = build_candidate_site(
        spec,
        resolved,
        0,
        _context(),
        target_kind="linear",
        expected_output_kind="line",
    )

    assert candidate.geometry is not None
    assert candidate.geometry.target_id == "sewer-1"
    assert candidate.candidate_id == candidate.geometry.candidate_id
    assert candidate.geometry.kind == "polygon"
    assert candidate.geometry.role == "corridor_candidate"
    assert candidate.geometry.is_executable is False


def test_real_line_reference_can_be_an_execution_geometry():
    spec = SpatialReferenceSpec(type="directional", target_id="road-1")
    resolved = ResolvedSpatialRef(
        final_bsms=["P-1"],
        reference_geometry_wkt="LINESTRING(0 0,1 1)",
        confidence=0.9,
    )

    candidate = build_candidate_site(
        spec,
        resolved,
        0,
        _context(),
        target_kind="road",
        expected_output_kind="line",
    )

    assert candidate.geometry is not None
    assert candidate.geometry.target_id == "road-1"
    assert candidate.candidate_id == candidate.geometry.candidate_id
    assert candidate.geometry.role == "execution_geometry"
    assert candidate.geometry.is_executable is True


def test_grounding_returns_unverified_relations_as_unknown_or_deferred():
    graph = PlanningIntentGraph(
        nodes=[],
        relations=[
            PlanRelationIntent(
                relation_id="r1",
                relation_template="serve",
                subject_ref="facility-1",
                object_ref="missing-zone",
                criticality="hard",
                evidence_refs=["claim:c1"],
            )
        ],
    )
    factors = compile_constraint_factors(graph)
    satisfaction = evaluate_relation_satisfaction(factors, [])

    assert len(factors) == 1
    assert isinstance(factors[0], ConstraintFactor)
    assert factors[0].hard is True
    assert satisfaction[0].status == "deferred"
