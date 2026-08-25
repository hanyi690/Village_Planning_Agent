from app.contracts.planning.constraint_factor import ConstraintFactor
from app.domain.allocation.master_coordinator import MasterCandidate, coordinate_master


def _candidate(target_id: str, candidate_id: str, wkt: str) -> MasterCandidate:
    return MasterCandidate(
        target_id=target_id,
        candidate_id=candidate_id,
        geometry_wkt=wkt,
        crs="EPSG:3857",
        source_refs=[f"source:{candidate_id}"],
    )


def test_master_rejects_locally_selected_product_that_violates_hard_topology():
    factor = ConstraintFactor(
        factor_id="factor:exclusive",
        kind="mutually_exclusive",
        evaluator_key="mutually_exclusive",
        subject_ref="target:a",
        object_ref="target:b",
        hard=True,
    )
    result = coordinate_master(
        [
            _candidate("target:a", "candidate:a", "POLYGON ((0 0, 2 0, 2 2, 0 0))"),
            _candidate("target:b", "candidate:b", "POLYGON ((0 0, 2 0, 2 2, 0 0))"),
        ],
        relation_factors=[factor],
    )

    assert result.status == "bounded_infeasible"
    assert "relation:exclusive:violated" in result.conflict_refs


def test_master_defers_when_hard_topology_has_no_selected_geometry_evidence():
    factor = ConstraintFactor(
        factor_id="factor:contains",
        kind="contains",
        evaluator_key="contains",
        subject_ref="target:a",
        object_ref="target:b",
        hard=True,
    )
    result = coordinate_master(
        [
            MasterCandidate(target_id="target:a", candidate_id="candidate:a"),
            MasterCandidate(target_id="target:b", candidate_id="candidate:b"),
        ],
        relation_factors=[factor],
    )

    assert result.status == "deferred"
    assert "relation:contains:not_evaluable" in result.blocker_refs
