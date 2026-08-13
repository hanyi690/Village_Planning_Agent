from __future__ import annotations

from app.contracts.artifacts.classification_ref import (
    ClassificationDecision,
    ClassificationSystem,
)
from app.contracts.spatial.global_zone_allocation_contracts import (
    GlobalZoneAllocationProblem,
    ParcelConstraint,
    ZoneCandidateSet,
    ZoneOverlayTargetRef,
    ZoneParcelCandidate,
    ZoneParcelFact,
)
from app.contracts.workflow.parse_contracts import ZoneTarget
from app.spatial.allocation.global_zone_parcel_allocator import (
    DeterministicGlobalZoneParcelAllocator,
)


def _decision(target_id: str) -> ClassificationDecision:
    return ClassificationDecision(
        target_id=target_id,
        code_system=ClassificationSystem.GBT21010,
        candidate_codes=["1207"],
        selected_code="1207",
        evidence_refs=[f"claim:{target_id}"],
        status="resolved",
    )


def _target(
    target_id: str,
    *,
    area_ha: float,
    candidates: list[str],
) -> ZoneTarget:
    return ZoneTarget(
        target_id=target_id,
        zone_id=f"zone-{target_id}",
        land_use=f"land-use-{target_id}",
        area_ha=area_ha,
        candidate_bsms=candidates,
        classification_decision=_decision(target_id),
        claim_refs=[f"claim:{target_id}"],
        source_instruction_id=f"instruction:{target_id}",
        source_report_key=f"report:{target_id}",
    )


def _parcel(
    bsm: str,
    area_ha: float,
    *,
    constraints: list[ParcelConstraint] | None = None,
) -> ZoneParcelFact:
    return ZoneParcelFact(
        bsm=bsm,
        area_ha=area_ha,
        geometry_ref=f"bundle://parcel/{bsm}",
        provenance_refs=[f"bundle:parcel:{bsm}"],
        constraints=constraints or [],
    )


def _candidate(bsm: str, score: float) -> ZoneParcelCandidate:
    return ZoneParcelCandidate(
        bsm=bsm,
        suitability_score=score,
        score_breakdown={"composite": score},
        provenance_refs=[f"suitability:{bsm}"],
    )


def _allocator() -> DeterministicGlobalZoneParcelAllocator:
    return DeterministicGlobalZoneParcelAllocator()


def test_global_allocator_resolves_cross_target_conflicts_without_duplicate_bsm():
    problem = GlobalZoneAllocationProblem(
        targets=[
            _target("A", area_ha=1.0, candidates=["P1", "P2"]),
            _target("B", area_ha=1.0, candidates=["P1", "P2"]),
        ],
        candidate_sets=[
            ZoneCandidateSet(
                target_id="A",
                candidates=[_candidate("P1", 0.90), _candidate("P2", 0.10)],
            ),
            ZoneCandidateSet(
                target_id="B",
                candidates=[_candidate("P1", 0.80), _candidate("P2", 0.95)],
            ),
        ],
        parcels=[_parcel("P1", 1.0), _parcel("P2", 1.0)],
    )

    result = _allocator().allocate(problem)

    assert result.status == "OPTIMAL"
    assert result.complete is True
    assert [(row.target_id, row.bsm) for row in result.assignments] == [
        ("A", "P1"),
        ("B", "P2"),
    ]
    assert len({row.bsm for row in result.assignments}) == len(result.assignments)
    assert any(item.code == "CANDIDATE_OWNERSHIP_CONFLICT" for item in result.diagnostics)


def test_hard_constraints_are_fail_closed_and_area_shortfall_is_reported():
    target = _target("A", area_ha=1.0, candidates=["P1", "P2"])
    problem = GlobalZoneAllocationProblem(
        targets=[target],
        candidate_sets=[
            ZoneCandidateSet(
                target_id="A",
                candidates=[_candidate("P1", 1.0), _candidate("P2", 0.8)],
            )
        ],
        parcels=[
            _parcel(
                "P1",
                1.0,
                constraints=[
                    ParcelConstraint(
                        code="constraint-001",
                        blocks_land_use_assignment=True,
                        provenance_refs=["constraint-layer:001"],
                    )
                ],
            ),
            _parcel("P2", 0.4),
        ],
    )

    result = _allocator().allocate(problem)

    assert result.status == "PARTIAL"
    assert result.complete is False
    assert [row.bsm for row in result.assignments] == ["P2"]
    balance = result.area_balances[0]
    assert balance.requested_area_ha == 1.0
    assert balance.assigned_area_ha == 0.4
    assert balance.shortfall_area_ha == 0.6
    assert any(
        item.code == "PARCEL_CONSTRAINT_BLOCKED" and item.bsm == "P1"
        for item in result.diagnostics
    )
    assert any(
        item.code == "ZONE_AREA_SHORTFALL" and item.target_id == "A"
        for item in result.diagnostics
    )


def test_overlay_targets_pass_through_without_entering_exclusive_assignments():
    problem = GlobalZoneAllocationProblem(
        targets=[_target("A", area_ha=1.0, candidates=["P1"])],
        candidate_sets=[
            ZoneCandidateSet(target_id="A", candidates=[_candidate("P1", 0.9)])
        ],
        parcels=[_parcel("P1", 1.0)],
        overlay_targets=[
            ZoneOverlayTargetRef(
                target_id="overlay-1",
                materialization_role="protection_overlay",
                candidate_bsms=["P1"],
                provenance_refs=["claim:overlay-1"],
            ),
            ZoneOverlayTargetRef(
                target_id="overlay-2",
                materialization_role="restoration_overlay",
                candidate_bsms=["P1"],
                provenance_refs=["claim:overlay-2"],
            ),
        ],
    )

    result = _allocator().allocate(problem)

    assert [(row.target_id, row.bsm) for row in result.assignments] == [("A", "P1")]
    assert [row.target_id for row in result.overlay_targets] == ["overlay-1", "overlay-2"]
    assert all(row.materialization_role == "land_use_assignment" for row in result.assignments)


def test_assignment_lineage_preserves_target_candidate_and_parcel_provenance():
    target = _target("A", area_ha=1.0, candidates=["P1"])
    problem = GlobalZoneAllocationProblem(
        targets=[target],
        candidate_sets=[
            ZoneCandidateSet(target_id="A", candidates=[_candidate("P1", 0.9)])
        ],
        parcels=[_parcel("P1", 1.0)],
    )

    assignment = _allocator().allocate(problem).assignments[0]

    assert assignment.classification_system == "gbt21010"
    assert assignment.classification_code == "1207"
    assert assignment.lineage.target_id == "A"
    assert assignment.lineage.source_instruction_id == "instruction:A"
    assert assignment.lineage.source_report_key == "report:A"
    assert assignment.lineage.claim_refs == ["claim:A"]
    assert assignment.lineage.candidate_provenance_refs == ["suitability:P1"]
    assert assignment.lineage.parcel_provenance_refs == ["bundle:parcel:P1"]
    assert assignment.lineage.geometry_ref == "bundle://parcel/P1"
    assert assignment.lineage.lineage_id


def test_allocator_is_deterministic_across_input_order():
    targets = [
        _target("A", area_ha=1.0, candidates=["P1", "P2"]),
        _target("B", area_ha=1.0, candidates=["P1", "P2"]),
    ]
    candidate_sets = [
        ZoneCandidateSet(
            target_id="A",
            candidates=[_candidate("P1", 0.5), _candidate("P2", 0.5)],
        ),
        ZoneCandidateSet(
            target_id="B",
            candidates=[_candidate("P1", 0.5), _candidate("P2", 0.5)],
        ),
    ]
    parcels = [_parcel("P1", 1.0), _parcel("P2", 1.0)]

    first = _allocator().allocate(
        GlobalZoneAllocationProblem(
            targets=targets,
            candidate_sets=candidate_sets,
            parcels=parcels,
        )
    )
    second = _allocator().allocate(
        GlobalZoneAllocationProblem(
            targets=list(reversed(targets)),
            candidate_sets=list(reversed(candidate_sets)),
            parcels=list(reversed(parcels)),
        )
    )

    assert [(row.target_id, row.bsm) for row in first.assignments] == [
        (row.target_id, row.bsm) for row in second.assignments
    ]
    assert first.objective_value == second.objective_value


def test_missing_candidate_parcel_fact_never_creates_an_assignment():
    problem = GlobalZoneAllocationProblem(
        targets=[_target("A", area_ha=1.0, candidates=["P404"])],
        candidate_sets=[
            ZoneCandidateSet(target_id="A", candidates=[_candidate("P404", 1.0)])
        ],
        parcels=[],
    )

    result = _allocator().allocate(problem)

    assert result.status == "MODEL_INVALID"
    assert result.assignments == []
    assert result.area_balances[0].shortfall_area_ha == 1.0
    assert any(
        item.code == "PARCEL_FACT_MISSING" and item.bsm == "P404"
        for item in result.diagnostics
    )


def test_unresolved_classification_is_not_materialized_as_authoritative_land_use():
    target = _target("A", area_ha=1.0, candidates=["P1"])
    target = target.model_copy(update={"classification_decision": None})
    problem = GlobalZoneAllocationProblem(
        targets=[target],
        candidate_sets=[
            ZoneCandidateSet(target_id="A", candidates=[_candidate("P1", 0.9)])
        ],
        parcels=[_parcel("P1", 1.0)],
    )

    result = _allocator().allocate(problem)

    assert result.status == "MODEL_INVALID"
    assert result.assignments == []
    assert any(
        item.code == "TARGET_CLASSIFICATION_UNRESOLVED" and item.target_id == "A"
        for item in result.diagnostics
    )


def test_one_infeasible_zone_does_not_steal_or_hide_another_zone_assignment():
    blocked = ParcelConstraint(
        code="constraint-B",
        blocks_land_use_assignment=True,
        blocked_target_ids=["B"],
        provenance_refs=["constraint-layer:B"],
    )
    problem = GlobalZoneAllocationProblem(
        targets=[
            _target("A", area_ha=1.0, candidates=["P1"]),
            _target("B", area_ha=1.0, candidates=["P2"]),
        ],
        candidate_sets=[
            ZoneCandidateSet(target_id="A", candidates=[_candidate("P1", 0.9)]),
            ZoneCandidateSet(target_id="B", candidates=[_candidate("P2", 0.9)]),
        ],
        parcels=[_parcel("P1", 1.0), _parcel("P2", 1.0, constraints=[blocked])],
    )

    result = _allocator().allocate(problem)

    assert result.status == "PARTIAL"
    assert [(row.target_id, row.bsm) for row in result.assignments] == [("A", "P1")]
    assert {row.target_id: row.shortfall_area_ha for row in result.area_balances} == {
        "A": 0.0,
        "B": 1.0,
    }
    assert any(
        item.code == "ZONE_NO_FEASIBLE_CANDIDATE" and item.target_id == "B"
        for item in result.diagnostics
    )


def test_candidate_outside_grounded_target_set_is_never_used_as_pool_fallback():
    problem = GlobalZoneAllocationProblem(
        targets=[_target("A", area_ha=1.0, candidates=["P1"])],
        candidate_sets=[
            ZoneCandidateSet(target_id="A", candidates=[_candidate("P2", 1.0)])
        ],
        parcels=[_parcel("P1", 1.0), _parcel("P2", 1.0)],
    )

    result = _allocator().allocate(problem)

    assert result.status == "MODEL_INVALID"
    assert result.assignments == []
    assert any(
        item.code == "CANDIDATE_NOT_GROUNDED" and item.bsm == "P2"
        for item in result.diagnostics
    )
