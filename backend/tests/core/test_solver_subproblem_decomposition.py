from app.contracts.planning.constraint_factor import ConstraintFactor
from app.contracts.spatial.candidate_geometry import CandidateGeometry
from app.contracts.spatial.grounded_problem import (
    GroundedCandidateDomain,
    GroundedPlanningProblem,
    GroundedTargetDomain,
    ParcelResource,
    ParcelResourcePool,
)
from app.domain.allocation.subproblem_compiler import compile_solver_subproblems
from app.domain.allocation.subproblem_optimizer import optimize_solver_subproblems
from app.domain.relations.service import RelationEvaluationContext


def _geometry(candidate_id: str, target_id: str, *, kind: str = "point", bsm: str = "") -> CandidateGeometry:
    return CandidateGeometry(
        candidate_id=candidate_id,
        target_id=target_id,
        kind=kind,
        role="execution_geometry",
        materialization_role="site_footprint" if bsm else "",
        wkt="POINT (0 0)" if kind == "point" else "LINESTRING (0 0, 1 1)" if kind == "line" else "POLYGON ((0 0, 1 0, 1 1, 0 0))",
        crs="EPSG:3857",
        source_ref=f"source:{candidate_id}",
        evidence_refs=[f"evidence:{candidate_id}"],
        identity_confidence=0.9,
        geometry_confidence=0.9,
        hard_constraint_status="passed",
        source_bsms=[bsm] if bsm else [],
        source_area_ha=10 if bsm else None,
        eligible_area_ha=5 if bsm else None,
        planning_area_ha=5 if bsm else None,
        availability_status="fully_available" if bsm else "unknown",
        suitability_components={"suitability": 0.5},
    )


def _target(target_id: str, target_kind: str, candidate_ids: list[str]) -> tuple[GroundedTargetDomain, GroundedCandidateDomain]:
    return (
        GroundedTargetDomain(
            target_id=target_id,
            target_kind=target_kind,
            expected_output_kind="polygon" if target_kind in {"site_area", "zone"} else "point",
            candidate_site_refs=candidate_ids,
            geometry_roles=["execution_geometry"],
            evidence_refs=[f"evidence:target:{target_id}"],
            status="resolved",
        ),
        GroundedCandidateDomain(
            target_id=target_id,
            candidate_ids=candidate_ids,
            candidate_geometry_refs=candidate_ids,
            selection_mode="choose_one",
            status="resolved",
        ),
    )


def _mixed_problem(*, include_topology: bool = True, include_network_ref: bool = True) -> GroundedPlanningProblem:
    facility_target, facility_domain = _target("facility-1", "facility", ["facility-candidate"])
    zone_target, zone_domain = _target("zone-1", "site_area", ["zone-candidate"])
    road_target, road_domain = _target("road-1", "road", ["road-candidate"])
    factors = []
    if include_topology:
        factors.append(
            ConstraintFactor(
                kind="part_of",
                subject_ref="facility-1",
                object_ref="zone-1",
                object_ref_kind="target",
                hard=True,
            )
        )
    return GroundedPlanningProblem(
        target_domains=[facility_target, zone_target, road_target],
        candidate_domains=[facility_domain, zone_domain, road_domain],
        candidate_geometries=[
            _geometry("facility-candidate", "facility-1"),
            _geometry("zone-candidate", "zone-1", kind="polygon", bsm="bsm:zone-1"),
            _geometry("road-candidate", "road-1", kind="line"),
        ],
        constraint_factors=factors,
        network_refs=["network:road"] if include_network_ref else [],
        parcel_resource_pool=ParcelResourcePool(
            pool_id="pool:zone",
            resources=[
                ParcelResource(
                    resource_id="resource:zone",
                    bsm="bsm:zone-1",
                    geometry_ref="geometry:zone-1",
                    source_area_ha=10,
                    eligible_area_ha=5,
                    availability_status="fully_available",
                    candidate_ids=["zone-candidate"],
                )
            ],
        ),
    )


def test_compiler_routes_mixed_targets_deterministically() -> None:
    problem = _mixed_problem()
    plan = compile_solver_subproblems(problem)
    reversed_problem = GroundedPlanningProblem(
        **problem.model_dump(exclude={"fingerprint", "candidate_completeness"}),
    )
    reversed_problem.target_domains.reverse()
    reversed_problem.candidate_domains.reverse()
    reversed_problem.candidate_geometries.reverse()
    reversed_problem.constraint_factors.reverse()
    reversed_plan = compile_solver_subproblems(reversed_problem)

    assert plan.fingerprint == reversed_plan.fingerprint
    by_id = {item.subproblem_id: item for item in plan.subproblems}
    assert by_id["target:facility-1"].problem_kind == "single_choice"
    assert by_id["target:zone-1"].problem_kind == "parcel_assignment"
    assert by_id["target:road-1"].problem_kind == "network_path"
    assert by_id["relation:" + next(
        factor.factor_id for factor in problem.constraint_factors
    )].problem_kind == "topology_layout"


def test_topology_relation_does_not_override_target_solver_kind() -> None:
    plan = compile_solver_subproblems(_mixed_problem())
    target_kinds = {
        item.subproblem_id: item.problem_kind
        for item in plan.subproblems
        if item.subproblem_id.startswith("target:")
    }
    assert target_kinds["target:facility-1"] == "single_choice"
    assert target_kinds["target:zone-1"] == "parcel_assignment"
    assert any(item.problem_kind == "topology_layout" for item in plan.subproblems)


def test_topology_block_preserves_target_alternatives_as_provisional() -> None:
    mixed = _mixed_problem()
    payload = mixed.model_dump(exclude={"fingerprint", "candidate_completeness"})
    payload["target_domains"] = [
        item for item in payload["target_domains"] if item["target_id"] != "road-1"
    ]
    payload["candidate_domains"] = [
        item for item in payload["candidate_domains"] if item["target_id"] != "road-1"
    ]
    payload["candidate_geometries"] = [
        item for item in payload["candidate_geometries"] if item["target_id"] != "road-1"
    ]
    payload["network_refs"] = []
    problem = GroundedPlanningProblem(**payload)
    result = optimize_solver_subproblems(
        problem,
        set_id="topology-block",
        evaluator_context=RelationEvaluationContext(scenario_id="topology-block"),
    )

    assert result.feasible_scenario_ids == []
    assert result.recommended is None
    assert result.scenarios
    assert result.scenarios[0].status == "partial"
    assert {item.target_id for item in result.scenarios[0].target_selections} == {
        "facility-1",
        "zone-1",
    }
    assert any(
        finding.code == "TOPOLOGY_SUBPROBLEM_BLOCKED"
        for finding in result.scenarios[0].findings
    )


def test_missing_network_input_blocks_composition_fail_closed() -> None:
    payload = _mixed_problem(
        include_topology=False,
        include_network_ref=False,
    ).model_dump(exclude={"fingerprint", "candidate_completeness"})
    payload["constraint_factors"] = [
        ConstraintFactor(
            kind="provide_access",
            subject_ref="road-1",
            evaluator_key="network_path",
        ).model_dump(mode="python")
    ]
    problem = GroundedPlanningProblem(**payload)
    plan = compile_solver_subproblems(problem)
    road = next(item for item in plan.subproblems if item.subproblem_id == "target:road-1")
    assert road.status == "blocked"
    assert "missing:network_ref" in road.required_input_refs

    result = optimize_solver_subproblems(
        problem,
        set_id="blocked-composition",
        evaluator_context=RelationEvaluationContext(scenario_id="blocked-composition"),
    )
    assert result.feasible_scenario_ids == []
    assert result.recommended is None
    assert result.solver_certificate.status == "unknown"
    assert result.infeasibility_explanations


def test_ready_target_subproblems_merge_deterministically() -> None:
    first_target, first_domain = _target("facility-a", "facility", ["a-1", "a-2"])
    second_target, second_domain = _target("facility-b", "facility", ["b-1", "b-2"])
    problem = GroundedPlanningProblem(
        target_domains=[first_target, second_target],
        candidate_domains=[first_domain, second_domain],
        candidate_geometries=[
            _geometry("a-1", "facility-a"),
            _geometry("a-2", "facility-a"),
            _geometry("b-1", "facility-b"),
            _geometry("b-2", "facility-b"),
        ],
    )
    context = RelationEvaluationContext(scenario_id="merged")
    first = optimize_solver_subproblems(
        problem,
        set_id="merged",
        evaluator_context=context,
    )
    second = optimize_solver_subproblems(
        problem,
        set_id="merged",
        evaluator_context=context,
    )

    assert first.fingerprint == second.fingerprint
    assert first.solver_certificate.backend_id == "deterministic_subproblem_merge"
    assert first.recommended is not None
    assert {item.target_id for item in first.recommended.target_selections} == {
        "facility-a",
        "facility-b",
    }


def test_parent_product_honors_max_scenarios_materialization_bound() -> None:
    first_target, first_domain = _target("facility-a", "facility", ["a-1", "a-2"])
    second_target, second_domain = _target("facility-b", "facility", ["b-1", "b-2"])
    problem = GroundedPlanningProblem(
        target_domains=[first_target, second_target],
        candidate_domains=[first_domain, second_domain],
        candidate_geometries=[
            _geometry("a-1", "facility-a"),
            _geometry("a-2", "facility-a"),
            _geometry("b-1", "facility-b"),
            _geometry("b-2", "facility-b"),
        ],
    )

    result = optimize_solver_subproblems(
        problem,
        set_id="bounded-merge",
        evaluator_context=RelationEvaluationContext(scenario_id="bounded-merge"),
        max_scenarios=1,
    )

    assert len(result.scenarios) == 1
    assert result.solver_certificate.status == "bounded"
    assert "SUBPROBLEM_PRODUCT_BOUND" in result.solver_certificate.termination_reason


def test_shared_parcel_resource_is_solved_as_one_formal_subproblem() -> None:
    first_target, first_domain = _target("zone-a", "site_area", ["zone-a-candidate"])
    second_target, second_domain = _target("zone-b", "site_area", ["zone-b-candidate"])
    problem = GroundedPlanningProblem(
        target_domains=[first_target, second_target],
        candidate_domains=[first_domain, second_domain],
        candidate_geometries=[
            _geometry("zone-a-candidate", "zone-a", kind="polygon", bsm="bsm:zone-1"),
            _geometry("zone-b-candidate", "zone-b", kind="polygon", bsm="bsm:zone-1"),
        ],
        shared_resource_refs=["pool:zone"],
        parcel_resource_pool=ParcelResourcePool(
            pool_id="pool:zone",
            resources=[
                ParcelResource(
                    resource_id="resource:zone",
                    bsm="bsm:zone-1",
                    geometry_ref="geometry:zone",
                    source_area_ha=10,
                    eligible_area_ha=5,
                    availability_status="fully_available",
                    candidate_ids=["zone-a-candidate", "zone-b-candidate"],
                )
            ],
        ),
    )

    result = optimize_solver_subproblems(
        problem,
        set_id="shared-resource-conflict",
        evaluator_context=RelationEvaluationContext(scenario_id="shared-resource-conflict"),
    )

    assert result.feasible_scenario_ids == []
    assert result.recommended is None
    assert result.solver_certificate.status == "infeasible"
    assert "SUBPROBLEM_INFEASIBLE" in result.infeasibility_explanations
    plan = compile_solver_subproblems(problem)
    assert [item.subproblem_id for item in plan.subproblems] == [
        next(item.subproblem_id for item in plan.subproblems if item.problem_kind == "parcel_assignment")
    ]
    grouped = plan.subproblems[0]
    assert grouped.target_refs == ("zone-a", "zone-b")
    assert "shared_resource_coordinator:joint_parcel_assignment" in grouped.diagnostics


def test_disjoint_parcel_resources_remain_formally_composable() -> None:
    first_target, first_domain = _target("zone-a", "site_area", ["zone-a-candidate"])
    second_target, second_domain = _target("zone-b", "site_area", ["zone-b-candidate"])
    problem = GroundedPlanningProblem(
        target_domains=[first_target, second_target],
        candidate_domains=[first_domain, second_domain],
        candidate_geometries=[
            _geometry("zone-a-candidate", "zone-a", kind="polygon", bsm="bsm:a"),
            _geometry("zone-b-candidate", "zone-b", kind="polygon", bsm="bsm:b"),
        ],
        shared_resource_refs=["bsm:a", "bsm:b"],
        parcel_resource_pool=ParcelResourcePool(
            pool_id="pool:zones",
            resources=[
                ParcelResource(
                    resource_id="resource:a",
                    bsm="bsm:a",
                    geometry_ref="geometry:a",
                    source_area_ha=10,
                    eligible_area_ha=5,
                    availability_status="fully_available",
                    candidate_ids=["zone-a-candidate"],
                ),
                ParcelResource(
                    resource_id="resource:b",
                    bsm="bsm:b",
                    geometry_ref="geometry:b",
                    source_area_ha=10,
                    eligible_area_ha=5,
                    availability_status="fully_available",
                    candidate_ids=["zone-b-candidate"],
                ),
            ],
        ),
    )

    result = optimize_solver_subproblems(
        problem,
        set_id="disjoint-resources",
        evaluator_context=RelationEvaluationContext(scenario_id="disjoint-resources"),
    )

    assert result.recommended is not None
    assert result.solver_certificate.status == "feasible"
