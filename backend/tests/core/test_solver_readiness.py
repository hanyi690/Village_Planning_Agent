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
from app.domain.allocation.solver_portfolio import SolverBackendRegistry
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
