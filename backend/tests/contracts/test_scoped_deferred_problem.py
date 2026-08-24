from app.contracts.planning.constraint_factor import ConstraintFactor, RelationSatisfaction
from app.contracts.spatial.candidate_geometry import CandidateGeometry
from app.contracts.spatial.grounded_problem import (
    GroundedCandidateDomain,
    GroundedPlanningProblem,
    GroundedTargetDomain,
)
from app.domain.ground.scoped_problem import scope_grounded_problem


def _problem() -> GroundedPlanningProblem:
    return GroundedPlanningProblem(
        target_domains=[
            GroundedTargetDomain(
                target_id="facility",
                candidate_site_refs=["facility-candidate"],
                geometry_roles=["execution_geometry"],
                status="resolved",
            ),
            GroundedTargetDomain(
                target_id="road",
                candidate_site_refs=["road-candidate"],
                geometry_roles=["corridor_candidate"],
                status="candidate_only",
            ),
        ],
        candidate_domains=[
            GroundedCandidateDomain(
                target_id="facility",
                candidate_ids=["facility-candidate"],
                candidate_geometry_refs=["facility-candidate"],
                status="resolved",
            ),
            GroundedCandidateDomain(
                target_id="road",
                candidate_ids=["road-candidate"],
                status="candidate_only",
            ),
        ],
        candidate_geometries=[
            CandidateGeometry(
                candidate_id="facility-candidate",
                target_id="facility",
                kind="point",
                role="execution_geometry",
                wkt="POINT (0 0)",
                crs="EPSG:3857",
                source_ref="source:facility",
                source_refs=["source:facility"],
                hard_constraint_status="passed",
            ),
            CandidateGeometry(
                candidate_id="road-candidate",
                target_id="road",
                kind="line",
                role="corridor_candidate",
                wkt="LINESTRING (0 0, 1 1)",
                crs="EPSG:3857",
                source_ref="source:road",
                source_refs=["source:road"],
            ),
        ],
        constraint_factors=[
            ConstraintFactor(
                factor_id="factor:facility-road",
                kind="near",
                subject_ref="facility",
                object_ref="road",
                hard=True,
            ),
            ConstraintFactor(
                factor_id="factor:facility-global",
                kind="within_allowed_area",
                subject_ref="facility",
                object_ref_kind="constraint",
                object_ref="allowed-area",
                hard=True,
            ),
        ],
        relation_satisfaction=[
            RelationSatisfaction(
                relation_id="relation:facility-road",
                subject_ref="facility",
                object_ref="road",
                factor_ids=["factor:facility-road"],
                criticality="hard",
            ),
            RelationSatisfaction(
                relation_id="relation:facility-global",
                subject_ref="facility",
                object_ref="allowed-area",
                factor_ids=["factor:facility-global"],
                criticality="hard",
            ),
        ],
    )


def test_scoped_problem_excludes_deferred_target_and_relations() -> None:
    parent = _problem()
    child = scope_grounded_problem(
        parent,
        ["road"],
        source_refs=["artifact:deferral_ledger:ledger-1"],
        reason="operator approved road deferral",
    )

    assert child.scope_policy == "deferred_target_subset"
    assert child.parent_problem_fingerprint == parent.fingerprint
    assert child.fingerprint != parent.fingerprint
    assert child.deferred_target_ids == ["road"]
    assert [item.target_id for item in child.target_domains] == ["facility"]
    assert [item.target_id for item in child.candidate_domains] == ["facility"]
    assert [item.target_id for item in child.candidate_geometries] == ["facility"]
    assert [item.factor_id for item in child.constraint_factors] == ["factor:facility-global"]
    assert [item.relation_id for item in child.relation_satisfaction] == ["relation:facility-global"]
    assert child.can_solve is True
    assert "artifact:deferral_ledger:ledger-1" in child.scope_source_refs


def test_scoped_problem_rejects_unknown_target() -> None:
    try:
        scope_grounded_problem(_problem(), ["missing"])
    except ValueError as exc:
        assert "missing" in str(exc)
    else:  # pragma: no cover - defensive assertion
        raise AssertionError("unknown deferred target must fail closed")


def test_scoped_problem_preserves_cumulative_deferrals() -> None:
    parent = _problem()
    first = scope_grounded_problem(parent, ["road"])
    second = scope_grounded_problem(first, ["facility"])

    assert second.deferred_target_ids == ["facility", "road"]
    assert second.target_domains == []
    assert second.candidate_domains == []
    assert second.candidate_geometries == []
