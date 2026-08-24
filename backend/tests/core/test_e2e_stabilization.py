"""Offline regression tests for the e2e stabilization plan (P0/P1).

Each test maps to an acceptance item in docs/design plans:
- unit/parameter ERROR downgrade (P0.2)
- target_projection L3 gate route (P0.5)
- identical-fingerprint VALIDATE replay cap + per-session budget (P0.4)
- empty spatial deferral = plain approve (P0.1)
- blocked VALIDATE compilation auto-defers targets (P0.3)
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.workflow.gate_policy import GATE_ROUTE_POLICY
from app.workflow import root_graph
from app.workflow.stages import validate as validate_stage
from app.domain.program.claim_draft import (
    PlanningClaimDraft,
    PlanningClaimDraftSet,
    claim_set_semantic_errors,
    normalize_claim_draft_set,
)


# ?? P0.2: unit/parameter errors are warnings, not semantic blockers ??????
def test_claim_unknown_units_are_warnings_not_semantic_errors():
    li = "\u91cc"  # ? (unknown length unit)
    raw = PlanningClaimDraftSet(
        dimension_key="test",
        claims=[
            PlanningClaimDraft(
                claim_id="c1",
                statement="s",
                suggested_category="zone",
                suggested_output_kind="polygon",
                polygon_parameters={
                    "materialization_role": "land_use_assignment",
                    "planning_zone": "A",
                    "land_use": "B",
                    "area_range": {"minimum": 1, "maximum": 5, "unit": li},
                },
            ),
            PlanningClaimDraft(
                claim_id="c2",
                statement="s",
                suggested_category="road",
                suggested_output_kind="line",
                road_parameters={"action": "new", "length": {"value": 100, "unit": li}},
            ),
            PlanningClaimDraft(
                claim_id="c3",
                statement="s",
                suggested_category="zone",
                suggested_output_kind="polygon",
                polygon_parameters={
                    "materialization_role": "land_use_assignment",
                    "planning_zone": "A",
                    "land_use": "B",
                    "area_range": {"minimum": 1, "maximum": 5, "unit": "ha"},
                },
            ),
        ],
    )
    cs = normalize_claim_draft_set(raw, dimension_key="test")
    assert not any(d.startswith("ERROR[") for d in cs.diagnostics)
    assert claim_set_semantic_errors(cs) == []
    assert len(cs.claims) == 3


def test_claim_incomplete_area_range_is_warning():
    raw = PlanningClaimDraftSet(
        dimension_key="test",
        claims=[
            PlanningClaimDraft(
                claim_id="c1",
                statement="s",
                suggested_category="zone",
                suggested_output_kind="polygon",
                polygon_parameters={
                    "materialization_role": "land_use_assignment",
                    "planning_zone": "A",
                    "land_use": "B",
                    "area_range": {"minimum": 1, "unit": "ha"},
                },
            ),
        ],
    )
    cs = normalize_claim_draft_set(raw, dimension_key="test")
    assert any("WARNING[incomplete_area_range]" in d for d in cs.diagnostics)
    assert not any(d.startswith("ERROR[") for d in cs.diagnostics)
    assert claim_set_semantic_errors(cs) == []


# ?? P0.5: target_projection L3 gate route is a bounded retry, not HUMAN ??
def test_target_projection_l3_route_retries_target():
    assert "L3" in GATE_ROUTE_POLICY["target_projection"]
    route = root_graph._evaluate_gate_policy(
        {"retry_counts": {"target_projection": 0}},
        "target_projection",
        "L3",
    )
    assert route == "target_projection"


# ?? P0.4: identical-fingerprint VALIDATE replay cap + budget ?????????????
class _FakeGate:
    issue_fingerprint = "abc"


def _validate_state(retry_count=0, budget=0, fingerprint="abc"):
    return {
        "retry_counts": {"validate": retry_count},
        "validation_budget_used": {"validate": budget},
        "repair_impact": {
            "status": "ready",
            "earliest_invalid_stage": "EXECUTE",
            "directive_ids": ["d1"],
        },
        "stage_audit": {"VALIDATE": {"issue_fingerprint": fingerprint}},
    }


def test_validate_first_replay_allowed(monkeypatch):
    monkeypatch.setattr(root_graph, "load_root_gate", lambda state, stage: _FakeGate())
    route = root_graph._retry_or_human(_validate_state(0), "validate", "execute")
    assert route == "execute"


def test_validate_retry_exhaustion_goes_diagnostic(monkeypatch):
    monkeypatch.setattr(root_graph, "load_root_gate", lambda state, stage: _FakeGate())
    route = root_graph._retry_or_human(_validate_state(3), "validate", "execute")
    assert route == root_graph.END_DIAGNOSTIC


def test_validate_session_budget_exhausted(monkeypatch):
    monkeypatch.setattr(root_graph, "load_root_gate", lambda state, stage: _FakeGate())
    state = _validate_state(1, budget=21)
    route = root_graph._retry_or_human(state, "validate", "execute")
    assert route == root_graph.END_DIAGNOSTIC


# ?? P0.1: empty spatial deferral is a plain approve, never a dead state ??
@pytest.mark.asyncio
async def test_empty_spatial_defer_is_plain_approve(monkeypatch):
    state = {
        "session_id": "s1",
        "paused_stage": "select",
        "human_review_items": [{"request_type": "spatial_reference_unresolved"}],
        "human_review_decisions": {
            "action": "approve",
            "defer_unresolved_spatial_references": True,
            "deferred_target_ids": [],
        },
    }
    monkeypatch.setattr(root_graph, "_gate_mutation_patch", lambda *a, **k: {})
    result = await root_graph.apply_human_review_decision(state)
    assert "fatal_error" not in result
    assert result.get("human_review_resume_consumed") is True


# VALIDATE no longer mutates approval state through a compatibility hook.
def test_auto_defer_blocked_targets_builds_ledger_and_passes(monkeypatch):
    compilation = SimpleNamespace(
        unresolved=[SimpleNamespace(target_ids=["t1", "t2"])]
    )
    impact = SimpleNamespace(reason="no deterministic repair policy")
    state = {"session_id": "s1", "artifact_refs": {}}
    working_state = {"artifact_refs": {}}

    persisted = {}

    def fake_persist(ws, stage, schema_id, payload):
        persisted[schema_id] = payload
        return {"ref": schema_id}

    decision = validate_stage._auto_defer_blocked_targets(
        state,
        compilation,
        impact,
        working_state,
        load_ref=lambda *a, **k: None,
        persist=fake_persist,
    )
    assert decision is None
    assert persisted == {}


def test_auto_defer_blocked_targets_none_without_ids():
    compilation = SimpleNamespace(unresolved=[SimpleNamespace(target_ids=[])])
    impact = SimpleNamespace(reason="integrity failure")
    decision = validate_stage._auto_defer_blocked_targets(
        {"session_id": "s1"},
        compilation,
        impact,
        {"artifact_refs": {}},
        load_ref=lambda *a, **k: None,
        persist=lambda *a, **k: None,
    )
    assert decision is None


# ?? P0.1 (root cause of run #6 dead state): GROUND approve must continue ??
def test_approve_ground_routes_to_select_never_end():
    assert root_graph._approve_ground(
        {"human_review_decisions": {"action": "approve"}}, "ground"
    ) == "select"


def test_approve_default_continues_forward_for_known_stages():
    assert root_graph._approve_default({}, "target_projection") == "ground"
    assert root_graph._approve_default({}, "ground") == "select"
    assert root_graph._approve_default({}, "reconcile") == "deliver"


def test_auto_defer_blocked_targets_fails_closed_on_non_target_findings():
    compilation = SimpleNamespace(
        unresolved=[
            SimpleNamespace(target_ids=["t1"]),
            SimpleNamespace(target_ids=[]),
        ]
    )
    impact = SimpleNamespace(reason="mixed findings")
    decision = validate_stage._auto_defer_blocked_targets(
        {"session_id": "s1"},
        compilation,
        impact,
        {"artifact_refs": {}},
        load_ref=lambda *a, **k: None,
        persist=lambda *a, **k: None,
    )
    assert decision is None


# SELECT auto-deferral requires a complete typed gate and interrupt state.
@pytest.mark.asyncio
async def test_select_approve_auto_defers_unplaced_targets(monkeypatch):
    gate = SimpleNamespace(
        pending_requests=[
            SimpleNamespace(
                context={"target_ids": ["unplaced-1", "unplaced-2"]}
            )
        ]
    )

    problem = SimpleNamespace(
        candidate_completeness=SimpleNamespace(
            unresolved_target_ids=("unplaced-1", "unplaced-2"),
        )
    )
    scenario = SimpleNamespace(findings=[])

    def fake_load(state, key, cls=None):
        if key == "scoped_grounding_problem":
            return problem
        if key == "planning_scenario":
            return scenario
        return None

    monkeypatch.setattr(root_graph, "load_root_gate", lambda state, stage: gate)
    monkeypatch.setattr("app.infrastructure.artifacts.runtime.load_artifact", fake_load)
    persisted = {}

    def fake_persist(state, stage, schema_id, payload):
        persisted[schema_id] = payload
        return {"ref": schema_id}

    monkeypatch.setattr(root_graph, "persist_stage_artifact", fake_persist)
    patch = await root_graph._apply_select_auto_deferral({"session_id": "s1"})
    assert patch["human_approval_diagnostic"]["code"] == "SELECT_DEFERRAL_SCOPE_STALE"
    assert persisted == {}


@pytest.mark.asyncio
async def test_select_human_approve_persists_approved_execution_input(monkeypatch):
    from app.contracts.planning.scenario import (
        BackendCertificatePayload,
        PlanningScenario,
        ScenarioSet,
        SolverCertificate,
        derive_backend_selection_digest,
        derive_solver_model_digest,
    )
    from app.contracts.workflow.execution_plan_contracts import ExecutionPlan

    scenario = PlanningScenario(
        scenario_id="scenario:human-approve",
        baseline_ref="baseline:1",
        problem_fingerprint="problem:1",
        status="complete",
    )
    proof = BackendCertificatePayload(
        backend_id="test_backend",
        backend_version="1.0",
        problem_kind="single_choice",
        problem_fingerprint="problem:1",
        input_digest="input:human-approve",
        solver_config={
            "deterministic_seed": 0,
            "search_limit": 0,
            "time_limit_seconds": None,
            "max_scenarios": 8,
            "objective_definitions": [],
            "backend_version": "1.0",
            "replay_settings": {},
        },
        selection_digest=derive_backend_selection_digest({}, []),
        status="feasible",
    )
    scenario_set = ScenarioSet(
        set_id="set:human-approve",
        problem_fingerprint="problem:1",
        scenarios=[scenario],
        feasible_scenario_ids=[scenario.scenario_id],
        recommended_scenario_id=scenario.scenario_id,
        solver_certificate=SolverCertificate(
            problem_fingerprint="problem:1",
            model_digest=derive_solver_model_digest(
                proof,
                deterministic_seed=0,
                search_limit=0,
            ),
            solver_version="test_backend:1.0",
            status="feasible",
            feasible_scenario_count=1,
            problem_kind="single_choice",
            backend_id="test_backend",
            backend_version="1.0",
            backend_certificate=proof,
        ),
    )
    execution_plan = ExecutionPlan(plan_id="plan:human-approve")

    def fake_load(state, key, cls=None):
        if key == "scenario_set":
            return scenario_set
        if key == "planning_scenario":
            return scenario
        if key == "execution_plan":
            return execution_plan
        if key == "approved_execution_input":
            return None
        return None

    persisted = {}

    def fake_persist(state, stage, schema_id, payload):
        persisted[schema_id] = payload
        return {"descriptor_digest": f"ref:{schema_id}"}

    monkeypatch.setattr("app.infrastructure.artifacts.runtime.load_artifact", fake_load)
    monkeypatch.setattr(root_graph, "persist_stage_artifact", fake_persist)
    monkeypatch.setattr(
        root_graph,
        "_gate_mutation_patch",
        lambda *args, **kwargs: {
            "artifact_refs": {
                **dict(kwargs.get("artifact_refs") or {}),
                "select_gate": {"descriptor_digest": "gate-ref"},
            }
        },
    )

    async def no_context(state):
        raise RuntimeError("context unavailable in unit test")

    monkeypatch.setattr("app.workflow.stages.support._require_context", no_context)

    result = await root_graph.apply_human_review_decision({
        "run_id": "run:human-approve",
        "session_id": "session:human-approve",
        "paused_stage": "select",
        "human_review_event_id": "event:human-approve",
        "human_review_items": [{"request_type": "scenario_approval"}],
        "human_review_decisions": {
            "action": "approve",
            "approved_by": "reviewer:1",
        },
        "artifact_refs": {
            "scenario_set": {"descriptor_digest": "set-ref"},
            "planning_scenario": {"descriptor_digest": "scenario-ref"},
            "execution_plan": {"descriptor_digest": "plan-ref"},
        },
    })

    assert result["approved_input_status"] == "human_approved"
    assert "ApprovedExecutionInput" in persisted
    assert persisted["ApprovedExecutionInput"].can_execute is True
    assert result["artifact_refs"]["approved_execution_input"] == {
        "descriptor_digest": "ref:ApprovedExecutionInput"
    }


# EXECUTE never mutates an approval plan to defer unresolved classification.
def test_execute_defers_unclassified_targets(monkeypatch):
    from app.workflow.stages import execute as ex
    from app.contracts.workflow.execution_plan_contracts import (
        ExecutionPlan,
        TargetAssignment,
        WorkerTask,
        WorkerType,
    )

    tasks = [
        WorkerTask(
            task_id=f"parcel:{tid}",
            worker_type=WorkerType.PARCEL_TRANSFORMATION,
            target_id=tid,
            target_type="site_area",
            expected_output_kind="parcel",
            assignment=TargetAssignment(
                target_id=tid, target_type="site_area", status="placed",
                expected_output_kind="parcel",
            ),
        )
        for tid in ("a", "b", "c")
    ]
    plan = ExecutionPlan(plan_id="p", worker_tasks=tasks, deferred_tasks=[])
    diags = [{"target_id": "a"}, {"target_id": "b"}]
    out = ex._defer_unclassified_targets({"artifact_refs": {}}, plan, None, diags)
    assert out is None


# ?? P1.9: HITL approve may dispatch provider_resume_dispatch (allowlist) ??
def test_human_review_apply_may_dispatch_provider_resume():
    from app.workflow.dispatch import DispatchPolicy, DispatchProposal

    policy = DispatchPolicy()
    decision = policy.authorize(
        DispatchProposal(
            allowed_action="advance",
            target_stage="provider_resume_dispatch",
            reason="provider resume after HUMAN approve",
            source_stage="human_review_apply",
        ),
        {},
    )
    assert decision.accepted, decision.diagnostic


# ?? P0.3: validate/reconcile approve with only non-target blockers -> PASS ??
@pytest.mark.asyncio
async def test_validate_approve_non_target_blocker_passes_not_diagnostic(monkeypatch):
    state = {
        "session_id": "s1",
        "paused_stage": "reconcile",
        "human_review_items": [{
            "request_type": "reconcile_retry_l3",
            "context": {"stage": "L3", "non_target_blocker_count": 1},
        }],
        "human_review_decisions": {"action": "approve"},
    }

    def fake_blocking(st, stage):
        return set(), 1

    monkeypatch.setattr(root_graph, "_human_review_blocking_target_ids", fake_blocking)
    gate_patch = {}

    def fake_gate_mutation(state, stage, gate, **kw):
        gate_patch["gate"] = gate
        return {"gate_ref": "g"}

    monkeypatch.setattr(root_graph, "_gate_mutation_patch", fake_gate_mutation)
    monkeypatch.setattr(
        root_graph, "_root_gate_payload",
        lambda state, stage: {"stage": stage, "passed": False, "pending_requests": []},
    )
    result = await root_graph.apply_human_review_decision(state)
    assert "fatal_error" not in result
    assert result.get("approved_non_target_limitation") is True
    assert gate_patch["gate"]["passed"] is True
    assert gate_patch["gate"]["feedback_route"] == "PASS"


def test_provider_resume_dispatch_may_redispatch_layer_workers():
    from app.workflow.routing import authorize_route_result

    for target in ("l1_worker", "l2_worker", "l3_worker"):
        auth = authorize_route_result({}, "provider_resume_dispatch", target)
        assert auth.accepted, (target, auth.diagnostic)


def test_layer_aggregate_may_continue_blocked_provider_resume_dimensions():
    from app.workflow.routing import authorize_route_result

    auth = authorize_route_result({}, "layer_aggregate", "provider_resume_dispatch")
    assert auth.accepted, auth.diagnostic


# ?? SELECT: terrain evidence gap is neutral, not a hard exclusion (exa) ??
def _terrain_evidence(status, valid_fraction, slope_p90):
    from app.contracts.spatial.terrain_evidence import (
        TerrainEvidence,
        TerrainEvidenceProvenance,
        TerrainStatistics,
    )

    elev = TerrainStatistics(
        unit="m", total_cell_count=10,
        valid_cell_count=int(10 * valid_fraction),
        valid_fraction=valid_fraction,
        minimum=100, maximum=300, mean=200, median=200,
        p10=120, p90=200, standard_deviation=10,
    )
    slope = TerrainStatistics(
        unit="deg", total_cell_count=10,
        valid_cell_count=int(10 * valid_fraction),
        valid_fraction=valid_fraction,
        mean=slope_p90 * 0.6, median=slope_p90 * 0.7,
        p90=slope_p90, maximum=slope_p90 * 1.1,
    )
    provenance = TerrainEvidenceProvenance(
        source_path="dem.tif", source_origin="catalog", source_sha256="sha256:" + "a" * 64,
        raster_crs="EPSG:4326", geometry_crs="EPSG:4326", geometry_sha256="sha256:" + "b" * 64,
        raster_transform=(1, 0, 0, 0, 1, 0), raster_nodata=-9999, raster_band=1,
        window=(0, 0, 10, 10),
        horizontal_scale_method="projected_axis_units",
        horizontal_pixel_size_m=(1.0, 1.0),
        cache_key="c1", cache_hit=False,
    )
    return TerrainEvidence(
        evidence_id="e1", subject_id="s1", status=status,
        elevation=elev, slope=slope, relief_m=50.0,
        diagnostics=("no_valid_cells",), provenance=provenance,
    )


def test_terrain_evidence_gap_is_neutral_not_hard_exclusion():
    from app.domain.suitability.terrain import assess_terrain_suitability
    from app.domain.suitability.policy import load_suitability_policy

    pol = load_suitability_policy()
    # DEM read returned no valid cells: neutral score, still feasible.
    a = assess_terrain_suitability(_terrain_evidence("no_valid_cells", 0.0, 0.0), pol.terrain)
    assert a.hard_feasible is True, a
    assert a.score == 0.5
    # Confirmed steep slope beyond hard maximum: still hard infeasible.
    a2 = assess_terrain_suitability(_terrain_evidence("ready", 1.0, 40.0), pol.terrain)
    assert a2.hard_feasible is False, a2
    assert "terrain_slope_exceeds_hard_maximum" in a2.reasons


def test_suitability_policy_allows_terrain_report_only():
    from app.domain.suitability.policy import load_suitability_policy

    pol = load_suitability_policy()
    assert pol.factors.terrain.on_unavailable == "report_only"
    assert pol.factors.terrain.required is True
