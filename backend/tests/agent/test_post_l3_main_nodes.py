import pytest

from app.agent.bootstrap import post_l3_main_nodes as M


@pytest.mark.asyncio
async def test_select_node_writes_execution_plan(monkeypatch):
    from app.modules.schema.contracts.parse_contracts import SpatialPlanningIntent, ProjectTarget
    from app.modules.schema.contracts.parse_result_contracts import IntentCompilationResult
    from app.modules.schema.contracts.grounding_contracts import GroundingResult

    plan_intent = SpatialPlanningIntent(
        project_targets=[ProjectTarget(project_id="p1", name="t1")]
    )
    intent = IntentCompilationResult(typed_intent=plan_intent, raw_intent={})

    monkeypatch.setattr(M, "_get_cached_context", lambda s: None)
    monkeypatch.setattr(M, "_persist_artifact", lambda *a, **k: None)

    def fake_load(state, key, cls):
        return {"intent_compilation": intent,
                "grounding_result": GroundingResult(candidates=[])}.get(key)
    monkeypatch.setattr(M, "_load_ref_artifact", fake_load)

    from app.agent.select import aggregate as sel_agg
    monkeypatch.setattr(sel_agg, "select_aggregate",
        lambda g, i, c: (object(), []))
    from app.agent.select import gate as sel_gate
    monkeypatch.setattr(sel_gate, "evaluate_select_gate",
        lambda d, target_count: object())

    state = {"upstream_gates": [], "retry_counts": {}}
    out = await M.select_node(state)
    assert "artifact_refs" in out, "select_node must write artifact_refs"
    assert "execution_plan" in out["artifact_refs"]


async def None_async(s):
    return None


@pytest.mark.asyncio
async def test_reconcile_node_loads_program_from_ref(monkeypatch):
    calls = {}

    def fake_reconcile(program, specs, grounding, decision, changeset,
                       planned_state, intent, run_id=""):
        calls["program"] = program
        return object()

    def fake_load(state):
        return object()

    monkeypatch.setattr(M, "_get_cached_context", lambda s: None)
    monkeypatch.setattr(M, "_load_planning_program", fake_load)
    monkeypatch.setattr(M, "_persist_artifact", lambda *a, **k: {})

    from app.agent.reconcile import aggregate as ragg
    from app.agent.reconcile import gate as rgate
    monkeypatch.setattr(ragg, "reconcile_aggregate", fake_reconcile)
    monkeypatch.setattr(rgate, "evaluate_reconcile_gate", lambda r: object())

    state = {
        "planning_program": None,
        "l3_program_ref": {"artifact_id": "x"},
        "specs": [],
        "grounding_result": None,
        "site_selection": None,
        "parcel_changeset": None,
        "planned_state": None,
        "intent": None,
        "upstream_gates": [],
        "retry_counts": {},
        "session_id": "s1",
    }

    await M.reconcile_node(state)
    assert calls["program"] is not None, "reconcile must use _load_planning_program"


@pytest.mark.asyncio
async def test_reconcile_node_fail_closed_when_program_missing(monkeypatch):
    monkeypatch.setattr(M, "_load_planning_program", lambda s: None)
    monkeypatch.setattr(M, "_get_cached_context", lambda s: None)
    monkeypatch.setattr(M, "_persist_artifact", lambda *a, **k: {})

    state = {
        "planning_program": None,
        "l3_program_ref": {"artifact_id": "x"},
        "specs": [],
        "grounding_result": None,
        "site_selection": None,
        "parcel_changeset": None,
        "planned_state": None,
        "intent": None,
        "upstream_gates": [],
        "retry_counts": {},
        "session_id": "s1",
    }

    out = await M.reconcile_node(state)
    assert out["reconcile_gate"]["feedback_route"] == "RETRY_L3"


@pytest.mark.asyncio
async def test_validate_node_passes_typed_intent(monkeypatch):
    from app.modules.schema.contracts.parse_contracts import SpatialPlanningIntent
    from app.modules.schema.contracts.parse_result_contracts import IntentCompilationResult
    from app.modules.schema.contracts.validation_report_contracts import ValidationReport

    plan_intent = SpatialPlanningIntent(project_targets=[])
    intent = IntentCompilationResult(typed_intent=plan_intent, raw_intent={})

    captured = {}

    def fake_validate_aggregate(*args, **kwargs):
        captured["intent"] = args[3]
        return ValidationReport(checks=[], overall_passed=True)

    monkeypatch.setattr(M, "_get_cached_context", lambda s: None)
    monkeypatch.setattr(M, "_persist_artifact", lambda *a, **k: {})

    def fake_load(state, key, cls):
        return {"intent_compilation": intent}.get(key)
    monkeypatch.setattr(M, "_load_ref_artifact", fake_load)

    import app.agent.validate.aggregate as vag
    monkeypatch.setattr(vag, "validate_aggregate", fake_validate_aggregate)

    state = {
        "layout_configs": [],
        "upstream_gates": [],
        "session_id": "s1",
    }
    await M.validate_node(state)
    assert isinstance(captured["intent"], SpatialPlanningIntent), (
        "validate_aggregate must receive the unwrapped typed intent"
    )


@pytest.mark.asyncio
async def test_ground_node_calls_retrieve_evidence_on_explore_retry(monkeypatch):
    from app.agent.ground import aggregate as gagg
    from app.agent.ground import gate as ggate
    from app.modules.schema.contracts.grounding_contracts import (
        GroundingResult,
        SpatialQueryEvidence,
    )

    called = {"evidence": False, "requests": None}
    evidence_row = SpatialQueryEvidence(
        query_type="retry:evidence_requests",
        query_params={"requests": [{"type": "road_access"}]},
        result_count=1,
        result_refs=["road_access_ref"],
    )

    async def fake_retrieve(ctx, reqs):
        called["evidence"] = True
        called["requests"] = reqs
        return [evidence_row]

    captured = {}

    def fake_ground(specs, ctx):
        captured["result"] = GroundingResult(candidates=[], spatial_query_evidence=[])
        return captured["result"]

    monkeypatch.setattr(M, "_get_cached_context", lambda s: None)
    monkeypatch.setattr(gagg, "retrieve_evidence", fake_retrieve)
    monkeypatch.setattr(gagg, "ground_aggregate", fake_ground)
    monkeypatch.setattr(ggate, "evaluate_ground_gate", lambda r: {"feedback_route": "PASS"})
    monkeypatch.setattr(M, "_persist_artifact", lambda *a, **k: {})

    state = {
        "ground_gate": {"feedback_route": "EXPLORE",
                        "evidence_requests": [{"type": "road_access"}]},
        "specs": [],
        "upstream_gates": [],
        "retry_counts": {},
    }
    out = await M.ground_node(state)
    assert called["evidence"] is True, "ground_node must call retrieve_evidence on EXPLORE retry"
    assert called["requests"] == [{"type": "road_access"}]
    dumped = captured["result"].model_dump()
    assert len(dumped["spatial_query_evidence"]) == 1
    assert dumped["spatial_query_evidence"][0]["query_type"] == "retry:evidence_requests"


@pytest.mark.asyncio
async def test_pre_execute_node_rebuilds_plan_when_missing(monkeypatch):
    from app.modules.schema.contracts.parse_contracts import SpatialPlanningIntent, ProjectTarget
    from app.modules.schema.contracts.parse_result_contracts import IntentCompilationResult
    from app.modules.schema.contracts.selection_contracts import SiteSelectionDecision

    class FakeContext:
        bundle = None
        village_anchors = []
        kg_session_ref = ""
        kg = None
        version = "v1"

        def snapshot_meta(self):
            return {"session_id": "s1", "version": "v1"}

    monkeypatch.setattr(M, "_get_cached_context", lambda s: FakeContext())
    monkeypatch.setattr(M, "_persist_artifact", lambda *a, **k: {})

    plan_intent = SpatialPlanningIntent(
        project_targets=[ProjectTarget(project_id="p1", name="t1")]
    )
    intent = IntentCompilationResult(typed_intent=plan_intent)

    def fake_load(state, key, cls):
        return {"intent_compilation": intent,
                "site_selection": SiteSelectionDecision(),
                "execution_plan": None}.get(key)
    monkeypatch.setattr(M, "_load_ref_artifact", fake_load)

    state = {
        "land_design_briefs": [],
        "session_id": "s1",
        "config": {"village_name": "v1"},
        "messages": [],
    }
    out = await M.pre_execute_node(state)
    assert out.get("execution_plan") is not None, (
        "pre_execute_node must rebuild execution_plan when it is missing"
    )
    assert out.get("intent") is plan_intent
    assert "village_name" in out


@pytest.mark.asyncio
async def test_post_execute_node_persists_outputs(monkeypatch):
    class FakeContext:
        bundle = None
        village_anchors = []
        kg_session_ref = ""
        kg = None

    monkeypatch.setattr(M, "_get_cached_context", lambda s: FakeContext())
    captured = {}

    def fake_persist(state, module, artifact_type, payload):
        captured[artifact_type] = payload
        return {"module": module, "type": artifact_type}

    monkeypatch.setattr(M, "_persist_artifact", fake_persist)
    monkeypatch.setattr(
        "app.agent.execute.planned_state_builder.changeset_to_planned_state",
        lambda changeset, intent: {"planned": True},
    )

    state = {
        "session_id": "s1",
        "parcel_changeset": {"changes": []},
        "layout_configs": [{"a": 1}],
        "execution_errors": [{"code": "x"}],
        "allocated_geojson": {"type": "FeatureCollection", "features": []},
    }
    out = await M.post_execute_node(state)
    assert captured.get("ParcelChangeSet") is not None
    assert captured.get("PlannedState") is not None
    assert captured.get("AllocatedGeoJSON") is not None
    assert out.get("layout_configs") == [{"a": 1}]
    assert out.get("execution_errors") == [{"code": "x"}]
    assert out.get("artifact_refs", {}).get("parcel_changeset") is not None
@pytest.mark.asyncio
async def test_collect_human_items_from_dict_gate():
    from app.modules.schema.contracts.workflow_contracts import GateDecision

    gate = GateDecision(
        stage="select",
        passed=False,
        feedback_route="HUMAN",
        pending_requests=[
            {
                "request_id": "pr-select-human-0",
                "stage": "select",
                "request_type": "select_human",
                "context": {"message": "manual review needed"},
            }
        ],
    )
    dumped = gate.model_dump()
    stage, items = M.collect_human_review_items({"select_gate": dumped})
    assert stage == "select"
    assert items, "collect_human_review_items must surface items from a dumped (dict) HUMAN gate"
    assert items[0]["request_id"] == "pr-select-human-0"


def test_collect_human_items_returns_stage_from_dict_gate():
    from app.modules.schema.contracts.workflow_contracts import GateDecision

    gate = GateDecision(
        stage="select",
        passed=False,
        feedback_route="HUMAN",
        pending_requests=[
            {
                "request_id": "pr-select-human-0",
                "stage": "select",
                "request_type": "select_human",
                "context": {"message": "manual review needed"},
            }
        ],
    )
    dumped = gate.model_dump()
    result = M.collect_human_review_items({"select_gate": dumped})
    assert result == ("select", [dumped["pending_requests"][0]])


def test_collect_human_items_returns_none_when_no_human_gate():
    stage, items = M.collect_human_review_items(
        {"select_gate": {"feedback_route": "PASS", "pending_requests": []}}
    )
    assert stage is None
    assert items == []


def test_pass_gate_construction():
    gate = M._pass_gate("select")
    assert gate.passed is True
    assert gate.feedback_route is None
