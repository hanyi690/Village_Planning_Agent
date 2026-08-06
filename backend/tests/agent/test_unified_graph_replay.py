"""Main-graph post-L3 replay integration tests (Task 8).

Proves the P0 repair stack on the REAL unified planning graph:
  - ``create_unified_planning_graph`` drives PARSE -> GROUND -> SELECT ->
    EXECUTE -> VALIDATE -> RECONCILE -> DELIVER with a MemorySaver
    checkpointer.
  - T1: ``planned_state`` (a post-L3 EXECUTE output channel) survives the
    main-graph state (no longer filtered by LangGraph).
  - T2: ``execution_plan`` is built in SELECT and flows into EXECUTE.
  - HITL: the main-graph ``human_review`` node pauses via ``interrupt()`` and
    resumes on the SAME compiled graph via ``Command(resume=...)``.

Heavy I/O is stubbed (LLM, context bundle, EXECUTE worker graph, export
package, render layers). The deterministic aggregates (build_execution_plan,
changeset_to_planned_state, _load_planning_program, validate/reconcile/deliver
gate routing) run for real.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command
from langchain_core.messages import AIMessage, HumanMessage

from app.agent.bootstrap.graph import create_unified_planning_graph
from app.agent.plan_state.state import create_initial_state
from app.modules.schema.contracts.l3_contracts import PlanningIntervention, PlanningProgram
from app.modules.schema.contracts.parse_contracts import ProjectTarget, SpatialPlanningIntent
from app.modules.schema.contracts.parse_result_contracts import CompilationStatus, IntentCompilationResult
from app.modules.schema.contracts.grounding_contracts import GroundingResult
from app.modules.schema.contracts.selection_contracts import SiteSelectionDecision
from app.modules.schema.contracts.parcel_change_contracts import (
    ClassificationRef,
    ParcelChange,
    ParcelChangeSet,
)
from app.modules.schema.contracts.workflow_contracts import GateDecision


def _pass_gate(stage: str) -> GateDecision:
    return GateDecision(stage=stage, passed=True, feedback_route=None, pending_requests=[])


def _program() -> PlanningProgram:
    return PlanningProgram(
        artifact_id="l3-s1-v1",
        interventions=[PlanningIntervention(intervention_id="i1", name="项目A")],
    )


def _intent_result() -> IntentCompilationResult:
    typed = SpatialPlanningIntent(
        village_name="金田村",
        project_targets=[ProjectTarget(project_id="p1", name="项目A", category="公共设施")],
    )
    return IntentCompilationResult(
        typed_intent=typed,
        program_ref="l3-s1-v1",
        compilation_status=CompilationStatus.VALIDATED,
        spatial_reference_specs=[],
    )


def _grounding() -> GroundingResult:
    return GroundingResult(candidates=[], unresolved=[])


def _decision() -> SiteSelectionDecision:
    return SiteSelectionDecision(selected_combination=["P1"])


def _changeset() -> ParcelChangeSet:
    return ParcelChangeSet(
        changes=[
            ParcelChange(
                bsm="P1",
                action="reclassify",
                after_classification=ClassificationRef(
                    system="gb",
                    code="0701",
                    canonical_name="村庄建设用地",
                    source="derived",
                ),
                after_geometry_wkt="POLYGON((0 0,1 0,1 1,0 1,0 0))",
            )
        ],
        area_conservation_verified=True,
        geometry_validity_verified=True,
    )


def _fake_context() -> SimpleNamespace:
    return SimpleNamespace(
        bundle=None,
        village_anchors=[],
        kg_session_ref="kg-1",
        kg=None,
        constraint_index=None,
        context_version="v1",
    )


class _FakeExecuteGraph:
    """Stands in for build_execute_agent_graph(); records the input state."""

    def __init__(self, changeset: ParcelChangeSet):
        self.received = None
        self.changeset = changeset

    async def ainvoke(self, exec_state, config=None):
        self.received = exec_state
        return {
            "parcel_changeset": self.changeset,
            "layout_configs": [],
            "allocated_geojson": {},
            "execution_errors": [],
        }


@pytest.fixture
def _post_l3_deps(monkeypatch):
    """Stub heavy I/O; keep the deterministic core running for real."""
    changeset = _changeset()
    fake_graph = _FakeExecuteGraph(changeset)
    monkeypatch.setattr(
        "app.agent.execute.execute_agent.build_execute_agent_graph",
        lambda: fake_graph,
    )
    monkeypatch.setattr(
        "app.agent.deliver.render_layers.build_render_layers",
        lambda *a, **k: [],
    )
    monkeypatch.setattr(
        "app.modules.spatial_ops.output.export_package.export_gdb_package",
        lambda *a, **k: {"status": "ok", "exported_files": []},
    )
    return {"changeset": changeset, "fake_graph": fake_graph}


async def _async_context(*a, **k):
    return _fake_context()


async def _async_parse_stub(*a, **k):
    return _intent_result(), [], _pass_gate("parse")


def _make_state() -> dict:
    state = create_initial_state("s1", "v1", "data")
    state["session_id"] = "s1"
    state["planning_program"] = _program()
    state["messages"] = [
        AIMessage(
            content="",
            tool_calls=[
                {"name": "gis_analysis", "args": {}, "id": "t1", "type": "tool_call"}
            ],
        )
    ]
    return state


@pytest.mark.asyncio
async def test_post_l3_chain_runs_end_to_end(monkeypatch, _post_l3_deps):
    """The real main graph runs PARSE..DELIVER; T1/T2 channels survive."""
    monkeypatch.setattr(
        "app.services.context.planning_context.build_planning_context",
        _async_context,
    )
    monkeypatch.setattr(
        "app.agent.parse.aggregate.compile_program_async",
        _async_parse_stub,
    )
    monkeypatch.setattr(
        "app.agent.ground.aggregate.ground_aggregate",
        lambda specs, context: _grounding(),
    )
    monkeypatch.setattr(
        "app.agent.ground.gate.evaluate_ground_gate",
        lambda result: _pass_gate("ground"),
    )
    monkeypatch.setattr(
        "app.agent.select.aggregate.select_aggregate",
        lambda grounding, intent, context: (_decision(), []),
    )
    monkeypatch.setattr(
        "app.agent.select.gate.evaluate_select_gate",
        lambda decision, target_count: _pass_gate("select"),
    )
    monkeypatch.setattr(
        "app.agent.validate.aggregate.validate_aggregate",
        lambda *a, **k: _pass_validate_report(),
    )
    monkeypatch.setattr(
        "app.agent.validate.gate.evaluate_validate_gate",
        lambda report: _pass_gate("validate"),
    )
    monkeypatch.setattr(
        "app.agent.reconcile.aggregate.reconcile_aggregate",
        lambda *a, **k: _pass_reconcile_report(),
    )
    monkeypatch.setattr(
        "app.agent.reconcile.gate.evaluate_reconcile_gate",
        lambda report: _pass_gate("reconcile"),
    )
    monkeypatch.setattr(
        "app.agent.deliver.aggregate.deliver_aggregate",
        lambda *a, **k: _pass_manifest(),
    )
    monkeypatch.setattr(
        "app.agent.deliver.gate.evaluate_deliver_gate",
        lambda manifest: _pass_gate("deliver"),
    )

    graph = create_unified_planning_graph(checkpointer=MemorySaver())
    result = await graph.ainvoke(
        _make_state(),
        config={"configurable": {"thread_id": "s1"}},
    )

    # T2: SELECT built an ExecutionPlan and it survived the main-graph state
    assert result.get("execution_plan") is not None, "execution_plan dropped in main graph"
    # T1: EXECUTE's planned_state survived (was filtered before Task 1)
    assert result.get("planned_state") is not None, "planned_state dropped in main graph"
    planned = result["planned_state"]
    assert getattr(planned, "parcels", None) is not None or isinstance(planned, dict)
    # The EXECUTE node consumed the ExecutionPlan
    assert _post_l3_deps["fake_graph"].received is not None
    assert _post_l3_deps["fake_graph"].received.execution_plan is not None
    # Full gate chain reached DELIVER
    deliver_route = _gate_route(result.get("deliver_gate"))
    assert deliver_route in {"PASS", "HUMAN"}


@pytest.mark.asyncio
async def test_hitl_interrupt_and_resume_same_graph(monkeypatch, _post_l3_deps):
    """A HUMAN gate pauses at main-graph human_review; Command(resume=...) recovers."""
    monkeypatch.setattr(
        "app.services.context.planning_context.build_planning_context",
        _async_context,
    )
    monkeypatch.setattr(
        "app.agent.parse.aggregate.compile_program_async",
        _async_parse_stub,
    )
    monkeypatch.setattr(
        "app.agent.ground.aggregate.ground_aggregate",
        lambda specs, context: _grounding(),
    )
    monkeypatch.setattr(
        "app.agent.ground.gate.evaluate_ground_gate",
        lambda result: _pass_gate("ground"),
    )
    # SELECT gate routes HUMAN -> route_after_select sends to human_review
    monkeypatch.setattr(
        "app.agent.select.aggregate.select_aggregate",
        lambda grounding, intent, context: (_decision(), []),
    )
    monkeypatch.setattr(
        "app.agent.select.gate.evaluate_select_gate",
        lambda decision, target_count: GateDecision(
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
        ),
    )

    graph = create_unified_planning_graph(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": "s2"}}
    result = await graph.ainvoke(_make_state(), config=config)

    interrupts = result.get("__interrupt__") or []
    payloads = [
        getattr(i, "value", i) if not isinstance(i, dict) else i
        for i in interrupts
    ]
    items = []
    for p in payloads:
        if isinstance(p, dict):
            items = p.get("human_review_items") or []
            if items:
                break
    assert items, "main-graph human_review should surface items on HUMAN gate"
    assert items[0]["request_id"] == "pr-select-human-0"

    resumed = await graph.ainvoke(
        Command(resume={"action": "approve"}),
        config=config,
    )
    assert resumed.get("human_review_decisions") == {"action": "approve"}


def _human_gate(stage: str) -> GateDecision:
    return GateDecision(
        stage=stage,
        passed=False,
        feedback_route="HUMAN",
        pending_requests=[
            {
                "request_id": f"pr-{stage}-human-0",
                "stage": stage,
                "request_type": "select_human",
                "context": {"message": "manual review needed"},
            }
        ],
    )


def _stub_full_chain(monkeypatch, human_stage=None):
    """Stub the full post-L3 chain; the named stage's gate routes HUMAN."""
    def _select_gate(decision, target_count):
        return _human_gate("select") if human_stage == "select" else _pass_gate("select")

    def _deliver_gate(manifest):
        return _human_gate("deliver") if human_stage == "deliver" else _pass_gate("deliver")

    monkeypatch.setattr(
        "app.services.context.planning_context.build_planning_context", _async_context)
    monkeypatch.setattr("app.agent.parse.aggregate.compile_program_async", _async_parse_stub)
    monkeypatch.setattr("app.agent.ground.aggregate.ground_aggregate",
                        lambda specs, context: _grounding())
    monkeypatch.setattr("app.agent.ground.gate.evaluate_ground_gate",
                        lambda result: _pass_gate("ground"))
    monkeypatch.setattr("app.agent.select.aggregate.select_aggregate",
                        lambda grounding, intent, context: (_decision(), []))
    monkeypatch.setattr("app.agent.select.gate.evaluate_select_gate", _select_gate)
    monkeypatch.setattr("app.agent.validate.aggregate.validate_aggregate",
                        lambda *a, **k: _pass_validate_report())
    monkeypatch.setattr("app.agent.validate.gate.evaluate_validate_gate",
                        lambda report: _pass_gate("validate"))
    monkeypatch.setattr("app.agent.reconcile.aggregate.reconcile_aggregate",
                        lambda *a, **k: _pass_reconcile_report())
    monkeypatch.setattr("app.agent.reconcile.gate.evaluate_reconcile_gate",
                        lambda report: _pass_gate("reconcile"))
    monkeypatch.setattr("app.agent.deliver.aggregate.deliver_aggregate",
                        lambda *a, **k: _pass_manifest())
    monkeypatch.setattr("app.agent.deliver.gate.evaluate_deliver_gate", _deliver_gate)


async def _resume_and_capture(graph, config, resume):
    """Resume an interrupted graph; return (final_state_values, node_names)."""
    nodes = []
    async for chunk in graph.astream(Command(resume=resume), config=config,
                                     stream_mode="updates"):
        for key in chunk:
            if key != "__interrupt__":
                nodes.append(key)
    final = graph.get_state(config).values
    return final, nodes


@pytest.mark.asyncio
async def test_hitl_interrupt_payload_carries_paused_stage(monkeypatch, _post_l3_deps):
    """The interrupt payload records which stage paused (select)."""
    _stub_full_chain(monkeypatch, human_stage="select")
    graph = create_unified_planning_graph(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": "s3"}}
    result = await graph.ainvoke(_make_state(), config=config)

    interrupts = result.get("__interrupt__") or []
    payloads = [
        getattr(i, "value", i) if not isinstance(i, dict) else i
        for i in interrupts
    ]
    payload = next(
        (p for p in payloads if isinstance(p, dict) and p.get("human_review_items")),
        None,
    )
    assert payload is not None, "human_review should interrupt with a payload"
    assert payload["paused_stage"] == "select"


@pytest.mark.asyncio
async def test_hitl_resume_records_paused_stage(monkeypatch, _post_l3_deps):
    """After resume, paused_stage is persisted in the graph state."""
    _stub_full_chain(monkeypatch, human_stage="select")
    graph = create_unified_planning_graph(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": "s4"}}
    await graph.ainvoke(_make_state(), config=config)
    final, _ = await _resume_and_capture(graph, config, {"action": "approve"})
    assert final["paused_stage"] == "select"


@pytest.mark.asyncio
async def test_hitl_approve_forwards_to_next_stage(monkeypatch, _post_l3_deps):
    """Approve at select forwards to execute and force-passes select_gate."""
    _stub_full_chain(monkeypatch, human_stage="select")
    graph = create_unified_planning_graph(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": "s5"}}
    await graph.ainvoke(_make_state(), config=config)
    final, nodes = await _resume_and_capture(graph, config, {"action": "approve"})

    assert "execute" in nodes, "approve at select must forward to execute"
    assert final["select_gate"]["feedback_route"] is None
    assert final.get("planned_state") is not None


@pytest.mark.asyncio
async def test_hitl_reject_routes_to_conversation(monkeypatch, _post_l3_deps):
    """Reject at select routes to conversation and surfaces the feedback."""
    called = {}

    async def _fake_llm(value):
        called["conversation_llm"] = True
        return AIMessage(content="收到，我调整方案")

    monkeypatch.setattr(
        "app.agent.conversation_router.node._get_llm_with_tools",
        lambda: _fake_llm,
    )
    _stub_full_chain(monkeypatch, human_stage="select")
    graph = create_unified_planning_graph(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": "s6"}}
    await graph.ainvoke(_make_state(), config=config)
    final, nodes = await _resume_and_capture(
        graph, config, {"action": "reject", "feedback": "换个方案"}
    )

    assert "conversation" in nodes, "reject must route to conversation"
    assert called.get("conversation_llm") is True
    assert any(
        getattr(m, "content", None) == "换个方案" for m in final["messages"]
    ), "reject feedback must be appended as a message"


@pytest.mark.asyncio
async def test_hitl_approve_deliver_routes_to_end(monkeypatch, _post_l3_deps):
    """Approve at deliver force-passes deliver_gate and terminates at END."""
    _stub_full_chain(monkeypatch, human_stage="deliver")
    graph = create_unified_planning_graph(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": "s7"}}
    await graph.ainvoke(_make_state(), config=config)
    final, nodes = await _resume_and_capture(graph, config, {"action": "approve"})

    assert final["paused_stage"] == "deliver"
    assert final["deliver_gate"]["feedback_route"] is None
    assert nodes == ["human_review"], "approve at deliver must end immediately"


@pytest.mark.asyncio
async def test_hitl_no_action_routes_to_end(monkeypatch, _post_l3_deps):
    """A resume without an action decision terminates at END without side-effects."""
    _stub_full_chain(monkeypatch, human_stage="select")
    graph = create_unified_planning_graph(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": "s8"}}
    await graph.ainvoke(_make_state(), config=config)
    final, nodes = await _resume_and_capture(graph, config, {"note": "continue"})

    assert final["human_review_decisions"] == {"note": "continue"}
    assert final["select_gate"]["feedback_route"] == "HUMAN"
    assert nodes == ["human_review"], "no-action resume must end immediately"


@pytest.mark.asyncio
async def test_hitl_full_lifecycle_approve_completes(monkeypatch, _post_l3_deps):
    """Approve at select drives execute..deliver to a completed delivery (not END at human_review)."""
    _stub_full_chain(monkeypatch, human_stage="select")
    graph = create_unified_planning_graph(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": "s9"}}
    state = _make_state()
    state["phase"] = "completed"
    result = await graph.ainvoke(state, config=config)

    payloads = [
        getattr(i, "value", i) if not isinstance(i, dict) else i
        for i in (result.get("__interrupt__") or [])
    ]
    payload = next(
        (p for p in payloads if isinstance(p, dict) and p.get("human_review_items")),
        None,
    )
    assert payload is not None, "select HUMAN gate must interrupt"
    assert payload["paused_stage"] == "select"
    assert payload["human_review_items"]

    final, nodes = await _resume_and_capture(graph, config, {"action": "approve"})

    assert "execute" in nodes, "approve at select must forward to execute"
    assert "validate" in nodes, "chain must continue through validate"
    assert "reconcile" in nodes, "chain must continue through reconcile"
    assert "deliver" in nodes, "chain must continue through deliver"
    assert nodes[-1] == "deliver", "approve must terminate at deliver -> END"
    assert final["select_gate"]["feedback_route"] in (None, "PASS"), (
        "select gate must be force-passed after approve"
    )
    assert final["deliver_gate"]["feedback_route"] in (None, "PASS"), (
        "deliver gate must pass to complete the delivery"
    )
    assert final["phase"] == "completed"


@pytest.mark.asyncio
async def test_hitl_full_lifecycle_reject_to_conversation(monkeypatch, _post_l3_deps):
    """Reject at select routes to conversation and surfaces the feedback as a HumanMessage."""
    async def _fake_llm(value):
        return AIMessage(content="收到，我调整方案")

    monkeypatch.setattr(
        "app.agent.conversation_router.node._get_llm_with_tools",
        lambda: _fake_llm,
    )
    _stub_full_chain(monkeypatch, human_stage="select")
    graph = create_unified_planning_graph(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": "s10"}}
    state = _make_state()
    state["phase"] = "completed"
    result = await graph.ainvoke(state, config=config)

    payloads = [
        getattr(i, "value", i) if not isinstance(i, dict) else i
        for i in (result.get("__interrupt__") or [])
    ]
    assert any(
        isinstance(p, dict) and p.get("paused_stage") == "select"
        for p in payloads
    ), "select HUMAN gate must interrupt"

    final, nodes = await _resume_and_capture(
        graph, config, {"action": "reject", "feedback": "换地块"}
    )

    assert "conversation" in nodes, "reject must route to conversation"
    assert nodes.index("conversation") > nodes.index("human_review"), (
        "conversation must run after human_review"
    )
    assert any(
        isinstance(m, HumanMessage) and "换地块" in (m.content or "")
        for m in final["messages"]
    ), "reject feedback must surface as a HumanMessage"


def _gate_route(gate) -> str:
    if gate is None:
        return "PASS"
    route = getattr(gate, "feedback_route", None)
    if route is None and isinstance(gate, dict):
        route = gate.get("feedback_route")
    return route or "PASS"


def _pass_validate_report():
    from app.modules.schema.contracts.validation_report_contracts import ValidationReport
    return ValidationReport(checks=[], overall_passed=True)


def _pass_reconcile_report():
    from app.modules.schema.contracts.reconciliation_contracts import ReconciliationReport
    return ReconciliationReport(inconsistencies=[])


def _pass_manifest():
    from app.modules.schema.contracts.delivery_manifest_contracts import DeliveryManifest
    return DeliveryManifest(statutory_complete=True)
