from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.contracts.planning.constraint_factor import ConstraintFactor
from app.contracts.planning.relation_parameters import AccessParameters, ServiceParameters
from app.contracts.planning.solver_readiness import SolverReadiness
from app.contracts.spatial.candidate_geometry import CandidateGeometry
from app.contracts.spatial.grounded_problem import (
    GroundedCandidateDomain,
    GroundedPlanningProblem,
    GroundedTargetDomain,
)
from app.domain.allocation.solver_portfolio import (
    SolverBackendRegistry,
    build_solver_problem_view,
    default_solver_registry,
)
from app.domain.allocation.solver_readiness import build_solver_readiness


def _problem(*, factor: ConstraintFactor | None = None) -> GroundedPlanningProblem:
    return GroundedPlanningProblem(
        target_domains=[GroundedTargetDomain(
            target_id="parcel-target",
            target_kind="site_area",
            expected_output_kind="polygon",
            candidate_site_refs=["candidate-1"],
            evidence_refs=["evidence:target"],
            status="resolved",
        )],
        candidate_domains=[GroundedCandidateDomain(
            target_id="parcel-target",
            candidate_ids=["candidate-1"],
            candidate_geometry_refs=["candidate-1"],
            selection_mode="choose_one",
            status="resolved",
        )],
        candidate_geometries=[CandidateGeometry(
            candidate_id="candidate-1",
            target_id="parcel-target",
            kind="polygon",
            role="execution_geometry",
            materialization_role="site_footprint",
            wkt="POLYGON ((0 0, 1 0, 1 1, 0 0))",
            source_ref="source:candidate-1",
            evidence_refs=["evidence:candidate-1"],
            identity_confidence=0.9,
            geometry_confidence=0.9,
            hard_constraint_status="passed",
            availability_status="fully_available",
            source_bsms=["bsm:1"],
            source_area_ha=2,
            eligible_area_ha=2,
            planning_area_ha=1,
        )],
        constraint_factors=[factor] if factor is not None else [],
    )


def test_ready_parcel_only_problem_has_advisory_optional_inputs() -> None:
    readiness = build_solver_readiness(_problem())

    assert isinstance(readiness, SolverReadiness)
    assert readiness.ready is True
    assert readiness.status == "ready"
    assert readiness.candidate.status == "ready"
    assert readiness.backend.backend_id == "deterministic_choice"
    assert readiness.demand.status == "pending"
    assert readiness.task_graph.status == "pending"
    assert readiness.blocker_refs == []
    assert readiness.fingerprint


@pytest.mark.parametrize(
    ("factor", "context", "expected_ref"),
    [
        (
            ConstraintFactor(
                factor_id="factor:access",
                kind="provide_access",
                evaluator_key="access_via",
                subject_ref="parcel-target",
                hard=True,
                parameters=AccessParameters(
                    network_ref="network:road",
                    max_travel_time_min=20,
                ),
            ),
            SimpleNamespace(networks={}, demands={}),
            "network:network:road",
        ),
        (
            ConstraintFactor(
                factor_id="factor:service",
                kind="serve",
                evaluator_key="serve",
                subject_ref="parcel-target",
                hard=True,
                parameters=ServiceParameters(
                    demand_ref="demand:clinic",
                    facility_type="clinic",
                    max_travel_time_min=20,
                    min_coverage_ratio=0.8,
                    capacity=10,
                    capacity_unit="people",
                    network_ref="network:road",
                ),
            ),
            SimpleNamespace(networks={"network:road": object()}, demands={}),
            "demand:demand:clinic",
        ),
    ],
)
def test_hard_demand_or_network_gap_blocks_preflight(factor, context, expected_ref) -> None:
    readiness = build_solver_readiness(_problem(factor=factor), context=context)

    assert readiness.ready is False
    assert readiness.status == "blocked"
    assert expected_ref in readiness.blocker_refs


@pytest.mark.parametrize(
    ("factor", "context", "dimension", "expected_refs"),
    [
        (
            ConstraintFactor(
                factor_id="factor:soft-access",
                kind="provide_access",
                evaluator_key="access_via",
                subject_ref="parcel-target",
                hard=False,
                parameters=AccessParameters(
                    network_ref="network:road",
                    max_travel_time_min=20,
                ),
            ),
            SimpleNamespace(networks={}, demands={}),
            "network",
            {"network:network:road"},
        ),
        (
            ConstraintFactor(
                factor_id="factor:soft-service",
                kind="serve",
                evaluator_key="serve",
                subject_ref="parcel-target",
                hard=False,
                parameters=ServiceParameters(
                    demand_ref="demand:clinic",
                    facility_type="clinic",
                    max_travel_time_min=20,
                    min_coverage_ratio=0.8,
                    capacity=10,
                    capacity_unit="people",
                    network_ref="network:road",
                ),
            ),
            SimpleNamespace(networks={}, demands={}),
            "demand",
            {"demand:demand:clinic", "network:network:road"},
        ),
    ],
)
def test_soft_demand_or_network_gap_is_advisory_and_backend_resolves(
    factor,
    context,
    dimension,
    expected_refs,
) -> None:
    problem = _problem(factor=factor)
    readiness = build_solver_readiness(problem, context=context)

    assert readiness.ready is True
    assert readiness.status == "ready"
    assert readiness.blocker_refs == []
    assert expected_refs.isdisjoint(readiness.blocker_refs)
    dimension_readiness = getattr(readiness, dimension)
    assert dimension_readiness.status == "pending"
    assert all(reason.severity == "advisory" for reason in dimension_readiness.reasons)
    assert expected_refs <= {
        reason.ref
        for reason in readiness.advisories
        if reason.code in {"missing:demand", "missing:network"}
    }

    view = build_solver_problem_view(problem, evaluator_context=context)
    assert view.input_complete is True
    resolution = default_solver_registry().resolve(problem, view)
    assert resolution.backend is not None


def test_soft_unknown_relation_evaluator_is_typed_advisory() -> None:
    factor = ConstraintFactor(
        factor_id="factor:soft-unknown",
        kind="near",
        evaluator_key="unknown_relation",
        subject_ref="parcel-target",
        hard=False,
    )

    readiness = build_solver_readiness(_problem(factor=factor))

    assert readiness.ready is True
    assert readiness.relation.status == "pending"
    reason = next(
        item
        for item in readiness.relation.reasons
        if item.code == "missing:relation_evaluator"
    )
    assert reason.severity == "advisory"
    assert reason.ref == "relation-evaluator:unknown_relation"
    assert reason in readiness.advisories


def test_solver_subproblem_plan_binds_readiness_lineage() -> None:
    from app.domain.allocation.subproblem_compiler import compile_solver_subproblems

    problem = _problem()
    readiness = build_solver_readiness(problem)
    plan = compile_solver_subproblems(problem, readiness=readiness)

    assert plan.readiness_status == "ready"
    assert plan.readiness_fingerprint == readiness.fingerprint
    assert plan.readiness_blocker_refs == []


def test_subproblem_optimizer_passes_readiness_to_duplicate_compile(monkeypatch) -> None:
    from app.domain.allocation import subproblem_optimizer
    from app.domain.relations.service import RelationEvaluationContext

    problem = _problem()
    readiness = build_solver_readiness(problem)
    original_compile = subproblem_optimizer.compile_solver_subproblems
    seen: list[object] = []

    def capture_compile(problem, *, readiness=None):
        seen.append(readiness)
        return original_compile(problem, readiness=readiness)

    monkeypatch.setattr(
        subproblem_optimizer,
        "compile_solver_subproblems",
        capture_compile,
    )
    subproblem_optimizer.optimize_solver_subproblems(
        problem,
        set_id="readiness-lineage",
        evaluator_context=RelationEvaluationContext(scenario_id="readiness-lineage"),
        readiness=readiness,
    )

    assert seen == [readiness]


def test_default_hard_satisfied_relation_without_evidence_blocks():
    factor = ConstraintFactor(
        factor_id="relation:no-evidence",
        kind="near",
        subject_ref="parcel-target",
        hard=True,
        evaluator_key="near",
    )
    from app.contracts.planning.constraint_factor import RelationSatisfaction

    problem = _problem(factor=factor).model_copy(update={
        "relation_satisfaction": [RelationSatisfaction(
            relation_id=factor.factor_id,
            factor_ids=[factor.factor_id],
            subject_ref="parcel-target",
            status="satisfied",
            evidence_refs=[],
        )],
    })
    readiness = build_solver_readiness(problem)
    assert readiness.ready is False
    assert readiness.status == "blocked"
    assert any("relation" in item for item in readiness.blocker_refs)


def test_same_physical_project_two_targets_share_one_solver_boundary():
    from app.domain.allocation.subproblem_compiler import compile_solver_subproblems

    base = _problem()
    target = base.target_domains[0].model_copy(update={"target_id": "target-2"})
    domain = base.candidate_domains[0].model_copy(update={
        "target_id": "target-2",
        "candidate_ids": ["candidate-2"],
        "candidate_geometry_refs": ["candidate-2"],
    })
    second = base.candidate_geometries[0].model_copy(update={
        "candidate_id": "candidate-2",
        "target_id": "target-2",
        "physical_project_ref": "physical-project:shared",
    })
    first = base.candidate_geometries[0].model_copy(update={
        "physical_project_ref": "physical-project:shared",
    })
    problem = base.model_copy(update={
        "target_domains": [base.target_domains[0].model_copy(update={"target_id": "parcel-target"}), target],
        "candidate_domains": [base.candidate_domains[0], domain],
        "candidate_geometries": [first, second],
    })
    plan = compile_solver_subproblems(problem)
    project_units = [
        item for item in plan.subproblems
        if item.physical_project_ref == "physical-project:shared"
    ]
    assert len(project_units) == 1
    assert set(project_units[0].target_refs) == {"parcel-target", "target-2"}
    assert project_units[0].candidate_ids_by_target == {
        "parcel-target": ("candidate-1",),
        "target-2": ("candidate-2",),
    }


def test_missing_backend_blocks_without_solver_fallback() -> None:
    readiness = build_solver_readiness(
        _problem(),
        solver_registry=SolverBackendRegistry([]),
    )

    assert readiness.ready is False
    assert readiness.backend.status == "blocked"
    assert "solver-kind:single_choice" in readiness.blocker_refs


def test_old_candidate_fields_are_schema_invalid_and_missing_fields_are_pending() -> None:
    with pytest.raises(ValidationError):
        CandidateGeometry.model_validate({
            "candidate_id": "legacy",
            "target_id": "parcel-target",
            "confidence": 0.9,
        })

    pending = CandidateGeometry(
        candidate_id="pending",
        target_id="parcel-target",
        kind="polygon",
        role="execution_geometry",
        wkt="POLYGON ((0 0, 1 0, 1 1, 0 0))",
    )
    assert pending.schema_status == "pending"
    assert pending.grounding_confidence_trusted is False


@pytest.mark.asyncio
async def test_select_preflight_short_circuits_suitability_and_optimizer(monkeypatch) -> None:
    from app.workflow.stages import select as select_stage

    factor = ConstraintFactor(
        factor_id="factor:access",
        kind="provide_access",
        evaluator_key="access_via",
        subject_ref="parcel-target",
        hard=True,
        parameters=AccessParameters(
            network_ref="network:road",
            max_travel_time_min=20,
        ),
    )
    problem = _problem(factor=factor)
    grounding = SimpleNamespace(problem=problem, candidates=[], unresolved=[])
    intent = SimpleNamespace(
        typed_intent=SimpleNamespace(
            site_area_targets=[],
            zone_targets=[],
            facilities=[],
            development_axes=[],
            road_targets=[],
            linear_targets=[],
        ),
        claims=[],
    )
    context = SimpleNamespace(
        version="context-v1",
        data_snapshot=SimpleNamespace(snapshot_id="snapshot-1", digest="digest-1"),
        networks={},
        demands={},
        snapshot_meta=lambda: {"snapshot": "snapshot-1"},
    )
    persisted: list[str] = []
    captured: dict[str, object] = {}

    async def fake_context(_state):
        return context

    def fake_load(_state, key, _cls):
        if key == "grounding_result":
            return grounding
        if key == "target_projection":
            return intent
        return None

    def fake_persist(_state, _stage, schema_id, _payload):
        persisted.append(schema_id)
        return {"digest": f"digest:{schema_id}"}

    def fake_completion(_state, _stage, *, output_refs, gate, **_kwargs):
        captured["output_refs"] = output_refs
        captured["gate"] = gate
        return {"artifact_refs": output_refs, "select_gate": gate}

    def fail_expensive(*_args, **_kwargs):
        raise AssertionError("expensive SELECT path was called before readiness passed")

    monkeypatch.setattr(select_stage, "_require_context", fake_context)
    monkeypatch.setattr(select_stage, "_load_ref_artifact", fake_load)
    monkeypatch.setattr(select_stage, "persist_stage_artifact", fake_persist)
    monkeypatch.setattr(select_stage, "stage_completion_patch", fake_completion)
    monkeypatch.setattr(select_stage, "build_suitability_surface", fail_expensive)

    patch = await select_stage.select_node({
        "run_id": "run-readiness",
        "session_id": "run-readiness",
        "branch_id": "main",
        "artifact_refs": {},
        "retry_counts": {},
        "context_version": "context-v1",
        "context_ref": {},
    })

    assert "SolverReadiness" in persisted
    assert "SuitabilitySurface" not in persisted
    assert "ScenarioSet" not in persisted
    gate = captured["gate"]
    assert gate.feedback_route == "HUMAN"
    assert any(
        item.startswith("solver_readiness:")
        for item in gate.pending_requests[0].context["reasons"]
    )
    assert "solver_readiness" in patch["artifact_refs"]
