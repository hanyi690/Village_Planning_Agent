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
from datetime import datetime, timezone, timedelta
from uuid import uuid4

import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command
from langchain_core.messages import AIMessage, HumanMessage

from app.agent.bootstrap.graph import (
    END_DIAGNOSTIC,
    apply_human_review_decision,
    create_unified_planning_graph,
    route_after_human_review,
    route_after_parse,
)
from app.agent.l3_plan.gate import evaluate_l3_gate
from app.agent.conversation_router.edges import after_analysis
from app.agent.execute.nodes.common import _checkpoint_safe
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
from app.modules.parsing.compiler.profiles.l3_planning import compile_l3_planning
from app.modules.parsing.compiler.spec_mapper import map_interventions_to_specs
from app.modules.prompts.detailed import get_dimension_prompt


def _pass_gate(stage: str) -> GateDecision:
    return GateDecision(stage=stage, passed=True, feedback_route=None, pending_requests=[])


def _program() -> PlanningProgram:
    return PlanningProgram(
        artifact_id="l3-s1-v1",
        interventions=[PlanningIntervention(intervention_id="i1", name="项目A")],
    )


def _action_program() -> PlanningProgram:
    return PlanningProgram(
        artifact_id="l3-action-v1",
        interventions=[
            PlanningIntervention(
                intervention_id="action-1",
                target_id="action-1",
                name="建立年度运营巡检制度",
                execution_mode="non_spatial",
                expected_output_kind="action",
                category="project",
            )
        ],
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
    ctx = SimpleNamespace(
        bundle=None,
        village_anchors=[],
        kg_session_ref="kg-1",
        kg=None,
        constraint_index=None,
        version=1,
        context_version="v1",
    )
    ctx.snapshot_meta = lambda: {"session_id": "s1", "version": 1}
    return ctx


class _FakeExecuteGraph:
    """Records inputs and stands in for build_execute_agent_graph().

    ``build()`` returns a real compiled StateGraph (a Runnable) so the parent
    graph can mount it as a formal subgraph node; ``received`` is captured via
    the recording child node.
    """

    def __init__(self, changeset: ParcelChangeSet):
        self.received = None
        self.changeset = changeset

    def build(self):
        from langgraph.graph import StateGraph, END, START
        from app.agent.execute.execute_state import ExecuteAgentState

        def child_node(state: ExecuteAgentState):
            self.received = state
            return {
                "parcel_changeset": self.changeset,
                "layout_configs": [],
                "allocated_geojson": {},
                "execution_errors": [],
            }

        builder = StateGraph(ExecuteAgentState)
        builder.add_node("child", child_node)
        builder.add_edge(START, "child")
        builder.add_edge("child", END)
        return builder.compile()


@pytest.fixture
def _post_l3_deps(monkeypatch):
    """Stub heavy I/O; keep the deterministic core running for real."""
    from pathlib import Path
    # Keep replay artifacts isolated per test invocation.  Never delete the
    # shared .run-tmp/s1 tree: another P1 test (or a user's inspection) may
    # legitimately own it, and stale files would make replay nondeterministic.
    run_tmp = Path.cwd() / ".run-tmp" / f"graph-replay-{uuid4().hex}"
    monkeypatch.setenv("BACKEND_RUN_TMP_DIR", str(run_tmp))
    changeset = _changeset()
    fake_graph = _FakeExecuteGraph(changeset)
    from app.services.runtime import PlanningRuntimeService
    execute_graph = fake_graph.build()
    monkeypatch.setattr(PlanningRuntimeService, "_execute_subgraph", execute_graph)
    monkeypatch.setattr(
        "app.agent.execute.execute_agent.build_execute_agent_graph",
        lambda **kwargs: execute_graph,
    )
    monkeypatch.setattr(
        "app.agent.deliver.render_layers.build_render_layers",
        lambda *a, **k: [],
    )
    monkeypatch.setattr(
        "app.modules.spatial_ops.output.export_package.export_gdb_package",
        lambda *a, **k: {"status": "ok", "exported_files": []},
    )
    fake_ctx = _fake_context()
    monkeypatch.setattr(
        "app.agent.bootstrap.post_l3_main_nodes._get_cached_context",
        lambda state: fake_ctx,
    )
    async def _bootstrap_stub(state):
        return {
            "context_version": "1",
            "context_fingerprint": "sha256:test",
            "context_ref": {
                "session_id": state.get("session_id", "s1"),
                "version": "1",
            },
            "bootstrap_context_done": True,
        }

    monkeypatch.setattr(
        "app.agent.bootstrap.graph.bootstrap_context_node",
        _bootstrap_stub,
    )
    async def _skip_step_report(*args, **kwargs):
        # This graph-replay test has no planning_sessions row by design.  The
        # real Session test owns DB-backed StepReport persistence; suppressing
        # it here prevents an orphaned aiosqlite worker from keeping pytest
        # alive after the in-memory graph assertion has completed.
        return None

    monkeypatch.setattr("app.agent.bootstrap.stage_audit._save", _skip_step_report)
    return {"changeset": changeset, "fake_graph": fake_graph}


async def _async_context(*a, **k):
    return _fake_context()


async def _async_parse_stub(*a, **k):
    return _intent_result(), [], _pass_gate("parse")


def _make_state(
    program: PlanningProgram | None = None,
    session_id: str = "s1",
) -> dict:
    state = create_initial_state(session_id, "v1", "data")
    state["session_id"] = session_id
    state["context_version"] = "1"
    state["context_fingerprint"] = "sha256:test"
    state["context_ref"] = {"session_id": session_id, "version": "1"}
    state["bootstrap_context_done"] = True
    from app.agent.bootstrap.artifact_runtime import store_artifact
    selected_program = program or _program()
    program_ref = store_artifact(
        state,
        "planning_program",
        "l3",
        "PlanningProgram",
        selected_program.model_dump(mode="json"),
    )
    state["artifact_refs"] = {"planning_program": program_ref}
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
async def test_real_post_l3_replay_action_only_is_mapless_complete(monkeypatch):
    """Replay real post-L3 stages with a deterministic L3 input and no LLM calls."""
    from pathlib import Path

    from app.agent.execute.execute_agent import build_execute_agent_graph
    from app.modules.context.planning_context import PlanningContext
    from app.modules.kg.builder import PlanningKG
    from app.modules.kg.manager import get_kg_manager
    from app.modules.schema.contracts.delivery_manifest_contracts import DeliveryManifest
    from app.modules.schema.contracts.execution_plan_contracts import ExecutionOutcome
    from app.services.runtime import PlanningRuntimeService
    from app.agent.bootstrap.artifact_runtime import load_artifact

    session_id = f"real-post-l3-{uuid4().hex}"
    run_tmp = Path.cwd() / ".run-tmp" / session_id
    monkeypatch.setenv("BACKEND_RUN_TMP_DIR", str(run_tmp))

    kg = PlanningKG(village_name="deterministic-action")
    manager = get_kg_manager()
    manager.register_session(session_id, kg)
    context = PlanningContext(
        session_id=session_id,
        village_name="deterministic-action",
        bundle=None,
        village_anchors=[],
        kg_session_ref=session_id,
        kg=kg,
        constraint_index=None,
        version=1,
    )

    async def _context_input(*args, **kwargs):
        return context

    async def _bootstrap_input(state):
        return {
            "context_version": "1",
            "context_fingerprint": "sha256:test",
            "context_ref": {"session_id": session_id, "version": "1"},
            "bootstrap_context_done": True,
        }

    async def _skip_db_audit(*args, **kwargs):
        return None

    monkeypatch.setattr(
        "app.services.context.planning_context.build_planning_context",
        _context_input,
    )
    monkeypatch.setattr(
        "app.agent.bootstrap.post_l3_main_nodes._get_cached_context",
        lambda state: context,
    )
    monkeypatch.setattr(
        "app.agent.bootstrap.graph.bootstrap_context_node",
        _bootstrap_input,
    )
    monkeypatch.setattr("app.agent.bootstrap.stage_audit._save", _skip_db_audit)
    monkeypatch.setattr(
        PlanningRuntimeService,
        "_execute_subgraph",
        build_execute_agent_graph(),
    )

    try:
        graph = create_unified_planning_graph(checkpointer=MemorySaver())
        result = await graph.ainvoke(
            _make_state(_action_program(), session_id),
            config={"configurable": {"thread_id": session_id}},
        )

        manifest = load_artifact(result, "delivery_manifest", DeliveryManifest)
        outcome = load_artifact(result, "execution_outcome", ExecutionOutcome)
        assert manifest is not None, result.get("validate_gate")
        assert manifest.delivery_status == "complete", manifest.model_dump(mode="json")
        assert manifest.expected_spatial_output_count == 0
        assert manifest.render_layer_count == 0
        assert manifest.action_results[0].target_id == "action-1"
        assert outcome is not None
        assert outcome.task_results[0].status == "succeeded"
        assert outcome.task_results[0].expected_output_kind == "action"
        assert result["deliver_gate"]["feedback_route"] is None
        assert result["render_artifacts"]["mapless"] is True
    finally:
        manager.remove_session(session_id)


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
        lambda result, **kwargs: _pass_gate("ground"),
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
        lambda manifest, **kwargs: _pass_gate("deliver"),
    )

    graph = create_unified_planning_graph(checkpointer=MemorySaver())
    result = await graph.ainvoke(
        _make_state(),
        config={"configurable": {"thread_id": "s1"}},
    )

    refs = result.get("artifact_refs") or {}
    assert "execution_plan" in refs, "execution_plan ref missing in main graph"
    assert "planned_state" in refs, "planned_state ref missing in main graph"
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
        lambda result, **kwargs: _pass_gate("ground"),
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

    def _deliver_gate(manifest, **kwargs):
        if human_stage == "deliver":
            return GateDecision(
                stage="deliver",
                passed=False,
                feedback_route="END_DIAGNOSTIC",
                pending_requests=[],
            )
        return _pass_gate("deliver")

    monkeypatch.setattr(
        "app.services.context.planning_context.build_planning_context", _async_context)
    monkeypatch.setattr("app.agent.parse.aggregate.compile_program_async", _async_parse_stub)
    monkeypatch.setattr("app.agent.ground.aggregate.ground_aggregate",
                        lambda specs, context: _grounding())
    monkeypatch.setattr("app.agent.ground.gate.evaluate_ground_gate",
                        lambda result, **kwargs: _pass_gate("ground"))
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
    assert "planned_state" in (final.get("artifact_refs") or {})


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
async def test_deliver_blocker_terminates_diagnostic_without_hitl(monkeypatch, _post_l3_deps):
    """A DELIVER blocker terminates diagnostically without an upstream cycle."""
    _stub_full_chain(monkeypatch, human_stage="deliver")
    graph = create_unified_planning_graph(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": "s7"}}
    nodes = []
    async for chunk in graph.astream(
        _make_state(), config=config, stream_mode="updates"
    ):
        nodes.extend(key for key in chunk if key != "__interrupt__")
    final = graph.get_state(config).values

    assert final["delivery_status"] == "diagnostic_only"
    assert final["deliver_gate"]["feedback_route"] == "END_DIAGNOSTIC"
    assert END_DIAGNOSTIC in nodes
    assert "human_review_prepare" not in nodes


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
    assert "human_review_apply" in nodes, "no-action resume must end after applying review"


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
    assert nodes.index("conversation") > nodes.index("human_review_apply"), (
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
    return DeliveryManifest(delivery_status="complete", statutory_complete=True)


def test_execute_checkpoint_boundary_converts_runtime_parcel_namespace():
    """HUMAN resume must not persist runtime-only parcel adapters."""
    value = _checkpoint_safe({"parcel_by_bsm": {
        "441": SimpleNamespace(
            bsm="441",
            geometry={"type": "Point", "coordinates": [116.0, 24.0]},
            dlbm="0701",
        ),
    }})
    assert value["parcel_by_bsm"]["441"] == {
        "bsm": "441",
        "geometry": {"type": "Point", "coordinates": [116.0, 24.0]},
        "dlbm": "0701",
    }


def test_llm_provider_failure_routes_to_human_review():
    """A transient provider error in L1/L2/L3 routes to HUMAN checkpoint."""
    assert after_analysis({
        "phase": "layer1",
        "fatal_error": {
            "stage": "L1",
            "dimension": "location",
            "code": "llm_provider_error",
            "message": "provider rejected request",
        },
        "completed_dimensions": {"layer1": []},
    }) == "human_review"


def test_merge_safe_provider_failure_routes_to_human_review():
    assert after_analysis({
        "phase": "layer3",
        "provider_failures": [{
            "stage": "L3", "dimension": "ecological",
            "code": "llm_stream_timeout", "message": "timeout",
        }],
        "completed_dimensions": {"layer3": ["industry"]},
    }) == "human_review"


def test_parallel_dimension_failure_is_preserved_for_human_route():
    """A successful sibling must not overwrite a provider failure in fan-in."""
    from app.agent.plan_state.state import _preserve_fatal_error

    failure = {"stage": "L2", "dimension": "planning_positioning", "code": "llm_stream_timeout"}
    assert _preserve_fatal_error(None, failure) == failure
    assert _preserve_fatal_error(failure, None) == failure


def test_llm_provider_circuit_breaker_is_session_scoped():
    from app.agent.common.dimension_runtime import (
        provider_failure_open,
        reset_provider_failure,
        trip_provider_failure,
    )

    session_id = f"circuit-{uuid4()}"
    reset_provider_failure(session_id)
    assert not provider_failure_open(session_id)
    trip_provider_failure(session_id)
    assert provider_failure_open(session_id)
    reset_provider_failure(session_id)
    assert not provider_failure_open(session_id)


def test_business_retry_limit_zero_escalates_without_retry():
    """A configured zero limit must not be replaced by the default limit."""
    state = {
        "max_retries": 0,
        "retry_counts": {},
        "parse_gate": {"feedback_route": "REPAIR"},
    }
    assert route_after_parse(state) == END_DIAGNOSTIC
    assert "delivery_status" not in state


def test_select_retry_exhaustion_routes_to_diagnostic_terminal():
    from app.agent.bootstrap.graph import route_after_select

    state = {
        "max_retries": 1,
        "retry_counts": {"select": 1},
        "select_gate": {"feedback_route": "RETRY_GROUND", "pending_requests": []},
        "ground_gate": {"feedback_route": "EXPLORE", "pending_requests": [{"stage": "ground"}]},
    }
    assert route_after_select(state) == END_DIAGNOSTIC
    assert state["select_gate"]["feedback_route"] == "RETRY_GROUND"
    assert "delivery_status" not in state


@pytest.mark.asyncio
async def test_compiled_graph_persists_retry_exhaustion_diagnostic(
    monkeypatch,
    _post_l3_deps,
):
    async def _retrying_parse(*args, **kwargs):
        return (
            _intent_result(),
            [],
            GateDecision(
                stage='parse',
                passed=False,
                feedback_route='REPAIR',
                pending_requests=[
                    {
                        'request_id': 'parse-repair-1',
                        'stage': 'parse',
                        'request_type': 'parse_repair',
                        'context': {'message': 'deterministic parse issue'},
                    }
                ],
            ),
        )

    monkeypatch.setattr(
        'app.agent.parse.aggregate.compile_program_async',
        _retrying_parse,
    )
    checkpointer = MemorySaver()
    graph = create_unified_planning_graph(checkpointer=checkpointer)
    config = {'configurable': {'thread_id': 'retry-exhaustion-checkpoint'}}
    state = _make_state()
    state['max_retries'] = 0

    final = await graph.ainvoke(state, config=config)
    checkpoint = graph.get_state(config).values

    for persisted in (final, checkpoint):
        assert persisted['delivery_status'] == 'diagnostic_only'
        assert persisted['parse_gate']['feedback_route'] == 'END_DIAGNOSTIC'
        assert persisted['diagnostic_terminal'] == {
            'stage': 'parse',
            'issue_fingerprint': '',
            'reason': 'business_retry_exhausted',
            'retry_count': 0,
            'retry_limit': 0,
        }


def test_human_retry_exhaustion_becomes_terminal_failure():
    """HUMAN retry cannot re-enter a failed stage after the cap is reached."""
    import asyncio
    state = {
        "max_retries": 1,
        "retry_counts": {"ground": 1},
        "human_review_items": [{"request_id": "r1"}],
        "paused_stage": "ground",
        "human_review_decisions": {"action": "retry"},
    }
    patch = asyncio.run(apply_human_review_decision(state))
    assert "fatal_error" not in patch
    assert patch["delivery_status"] == "diagnostic_only"
    assert patch["ground_gate"]["feedback_route"] == "END_DIAGNOSTIC"
    assert route_after_human_review({**state, **patch}) == END_DIAGNOSTIC


def test_duplicate_human_resolve_is_rejected(monkeypatch):
    """The same interrupt checkpoint cannot consume two HTTP decisions."""
    import asyncio
    from fastapi import HTTPException
    from app.api.human_review_routes import ResolveRequest, resolve_human_review
    from app.services.runtime import PlanningRuntimeService

    async def state_values(_session_id):
        return {"human_review_resume_consumed": True}

    monkeypatch.setattr(PlanningRuntimeService, "aget_state_values", state_values)
    request = ResolveRequest(decisions={"action": "accept"})
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(resolve_human_review("s1", request))
    assert exc_info.value.status_code == 409


def test_render_endpoint_selects_latest_planned_state_ref():
    from app.api.render_routes import _latest_artifact_ref

    old = SimpleNamespace(stored_at=datetime.now(timezone.utc) - timedelta(minutes=1))
    new = SimpleNamespace(stored_at=datetime.now(timezone.utc))
    assert _latest_artifact_ref([old, new]) is new


def test_stage_report_links_authoritative_artifact_payload():
    from app.services.stage_report import _artifact_payload_link

    link = _artifact_payload_link(
        {"session_id": "s1"},
        {
            "run_id": "s1",
            "module": "execute",
            "artifact_id": "planned-state",
            "revision": "v1",
        },
    )
    assert link == "../artifacts/execute/planned-state/v1/payload.json"


def test_l3_without_instruction_or_spatial_reference_fails_closed():
    fragment = compile_l3_planning(
        dimension_key="industry",
        content="# 产业规划\n- 建设农产品加工项目",
        instruction="",
    )
    assert any(
        issue.code == "missing_instruction_marker"
        for issue in fragment.program_issues
    )
    assert any(
        issue.code == "missing_spatial_instruction"
        for issue in fragment.program_issues
    )
    program = PlanningProgram(interventions=fragment.interventions, program_issues=fragment.program_issues)
    gate = evaluate_l3_gate(program)
    assert gate.feedback_route == "L3"
    specs, diagnostics = map_interventions_to_specs(program.interventions)
    assert len(specs) == 1
    assert specs[0].unresolved_reason == "missing_location_evidence"
    assert diagnostics[0].code == "UNRESOLVED_SPATIAL_REFERENCE"


def test_l3_instruction_table_produces_coarse_spatial_spec():
    fragment = compile_l3_planning(
        dimension_key="industry",
        content="# 产业规划\n建设农产品加工项目",
        instruction=(
            "| 类型 | 名称 | 位置 | 描述 | 规模 |\n"
            "| :--- | :--- | :--- | :--- | :--- |\n"
            "| 项目 | 农产品加工项目 | 村西部 | 加工与仓储 | 1500㎡ |"
        ),
    )
    assert not any(i.code == "missing_instruction_marker" for i in fragment.program_issues)
    specs, diagnostics = map_interventions_to_specs(fragment.interventions)
    assert len(specs) == 1
    assert not diagnostics


def test_spatial_dimension_prompt_requires_source_backed_location():
    prompt = get_dimension_prompt("industry", project_name="测试村")
    assert "当前维度属于空间可执行维度" in prompt
    assert "【INSTRUCTION】" in prompt
