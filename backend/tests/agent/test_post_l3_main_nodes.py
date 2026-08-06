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

    async def fake_ctx(s):
        return None
    monkeypatch.setattr(M, "_resolve_context", fake_ctx)
    monkeypatch.setattr(M, "_persist_artifact", lambda *a, **k: None)

    from app.agent.select import aggregate as sel_agg
    monkeypatch.setattr(sel_agg, "select_aggregate",
        lambda g, i, c: (object(), []))
    from app.agent.select import gate as sel_gate
    monkeypatch.setattr(sel_gate, "evaluate_select_gate",
        lambda d, target_count: object())

    state = {"intent": intent, "grounding_result": GroundingResult(candidates=[]),
             "upstream_gates": [], "retry_counts": {}}
    out = await M.select_node(state)
    assert "execution_plan" in out, "select_node must write execution_plan"
    assert out["execution_plan"] is not None


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

    monkeypatch.setattr(M, "_resolve_context", lambda s: None_async(s))
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
    assert out["reconciliation_report"] is not None


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

    monkeypatch.setattr(M, "_resolve_context", lambda s: None_async(s))
    monkeypatch.setattr(M, "_persist_artifact", lambda *a, **k: {})

    import app.agent.validate.aggregate as vag
    monkeypatch.setattr(vag, "validate_aggregate", fake_validate_aggregate)

    state = {
        "intent": intent,
        "planned_state": None,
        "parcel_changeset": None,
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

    async def fake_ctx(s):
        return None

    monkeypatch.setattr(M, "_resolve_context", fake_ctx)
    monkeypatch.setattr(gagg, "retrieve_evidence", fake_retrieve)
    monkeypatch.setattr(gagg, "ground_aggregate",
        lambda specs, ctx: GroundingResult(candidates=[], spatial_query_evidence=[]))
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
    dumped = out["grounding_result"]
    assert len(dumped["spatial_query_evidence"]) == 1
    assert dumped["spatial_query_evidence"][0]["query_type"] == "retry:evidence_requests"


@pytest.mark.asyncio
async def test_execute_node_rebuilds_plan_when_missing(monkeypatch):
    from app.agent.execute import execute_agent as eagg
    from app.modules.schema.contracts.parse_contracts import SpatialPlanningIntent, ProjectTarget
    from app.modules.schema.contracts.parse_result_contracts import IntentCompilationResult
    from app.modules.schema.contracts.selection_contracts import SiteSelectionDecision

    class FakeContext:
        bundle = None
        village_anchors = []
        kg_session_ref = ""
        kg = None

    class FakeExecuteGraph:
        def __init__(self):
            self.captured_state = None

        async def ainvoke(self, state, config=None):
            self.captured_state = state
            return {
                "parcel_changeset": None,
                "layout_configs": [],
                "allocated_geojson": {},
                "execution_errors": [],
            }

    fake_graph = FakeExecuteGraph()

    async def fake_ctx(s):
        return FakeContext()

    monkeypatch.setattr(M, "_resolve_context", fake_ctx)
    monkeypatch.setattr(eagg, "build_execute_agent_graph", lambda: fake_graph)
    monkeypatch.setattr(M, "_persist_artifact", lambda *a, **k: {})

    plan_intent = SpatialPlanningIntent(
        project_targets=[ProjectTarget(project_id="p1", name="t1")]
    )
    intent = IntentCompilationResult(typed_intent=plan_intent)
    state = {
        "intent": intent,
        "site_selection": SiteSelectionDecision(),
        "land_design_briefs": [],
        "execution_plan": None,
        "session_id": "s1",
        "config": {"village_name": "v1"},
        "messages": [],
    }
    out = await M.execute_node(state)
    assert fake_graph.captured_state is not None, "execute_node must invoke the execute graph"
    assert fake_graph.captured_state.execution_plan is not None, (
        "execute_node must rebuild execution_plan when it is missing"
    )
    assert out["planned_state"] is None
    assert "parcel_changeset" in out
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
