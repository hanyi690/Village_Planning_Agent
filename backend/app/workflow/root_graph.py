"""Main planning graph factory. Migrated from agent/graph.py per docs/architecture/agent-graph.md §5."""

from typing import Dict, Any, List, Literal, Optional
from langgraph.graph import StateGraph, END, START
from langchain_core.messages import HumanMessage

from app.workflow.layers.phase_machine import PlanningPhase, get_layer_dimensions
from app.domain.assessment.analysis_node import analyze_dimension, DIMENSION_NAMES
from app.workflow.plan_state.completion_node import layer_completion_check
from app.workflow.layers.layer_aggregate_node import layer_aggregate_node
from app.workflow.layers.layer_router import (
    l1_worker_node,
    l2_worker_node,
    l3_worker_node,
    advance_phase_node,
    revision_dispatch_node,
)
from app.application.interrupts import collect_human_review_items
from app.workflow.stages.target_projection import target_projection_node as _target_projection_stage
from app.workflow.stages.ground import ground_node as _ground_stage
from app.workflow.stages.select import select_node as _select_stage
from app.workflow.stages.execute import execute_node as _execute_stage
from app.workflow.stages.validate import validate_node as _validate_stage
from app.workflow.stages.reconcile import reconcile_node as _reconcile_stage
from app.workflow.stages.deliver import deliver_node as _deliver_stage
from app.workflow.stage_audit import audited_stage
from app.workflow.runtime_adapter import adapt_node, materialize_workflow_state
from app.workflow.routing import authorize_route_result
from app.workflow.terminal import diagnostic_terminal, terminal_patch
from app.workflow.state import (
    GATE_LOAD_FAILED,
    GATE_STAGES,
    WorkflowState,
    load_root_gate,
    root_gate_route,
)
from app.workflow.stages.support import (
    STAGE_FORWARD_TARGET as _STAGE_FORWARD_TARGET,
    _dump,
    _pass_gate,
)
from app.workflow.stage_adapter import persist_gate_decision, persist_stage_artifact
from app.workflow.layers.context_bootstrap import bootstrap_context_node
from app.contracts.events import SSEEventType
from app.contracts.workflow.human_interrupt_contracts import (
    HumanInterruptChannel,
    build_human_interrupt,
    normalize_human_decision,
    stable_human_interrupt_id,
)

from app.infrastructure.logging import get_logger
logger = get_logger(__name__)

END_DIAGNOSTIC = "end_diagnostic"
target_projection_node = audited_stage("TARGET_PROJECTION")(_target_projection_stage)
ground_node = audited_stage("GROUND")(_ground_stage)
select_node = audited_stage("SELECT")(_select_stage)
execute_node = audited_stage("EXECUTE")(_execute_stage)
validate_node = audited_stage("VALIDATE")(_validate_stage)
reconcile_node = audited_stage("RECONCILE")(_reconcile_stage)
deliver_node = audited_stage("DELIVER")(_deliver_stage)


def _dispatch_route(source_stage: str, route, state: Dict[str, Any]):
    """Authorize a legacy route result before LangGraph sees the jump."""
    local_state = materialize_workflow_state(state)
    result = route(local_state)
    authorization = authorize_route_result(state, source_stage, result)
    if authorization.accepted:
        return result
    diagnostic = authorization.diagnostic
    if diagnostic is None:
        return END_DIAGNOSTIC
    state.update(terminal_patch(diagnostic_terminal(diagnostic)))
    return END_DIAGNOSTIC


def _dispatch_fixed(source_stage: str, target_stage: str, state: Dict[str, Any]) -> str:
    """Authorize a fixed edge without changing its existing graph shape."""
    return _dispatch_route(source_stage, lambda _state: target_stage, state)


def _authorized_advance_phase(state: Dict[str, Any]):
    """Keep legacy phase advancement, but audit every resulting Command."""
    from langgraph.types import Command

    command = advance_phase_node(state)
    authorization = _authorize_command(state, "advance_phase", command)
    if authorization is None:
        return command
    return authorization


def _authorized_revision_dispatch(state: Dict[str, Any]):
    """Keep revision Send batching behind the same dispatch policy."""
    command = revision_dispatch_node(state)
    authorization = _authorize_command(state, "revision_dispatch", command)
    if authorization is None:
        return command
    return authorization


def _authorize_command(state: Dict[str, Any], source_stage: str, command):
    """Return a terminal Command when a legacy Command contains an invalid jump."""
    from langgraph.types import Command

    goto = command.goto
    targets = goto if isinstance(goto, list) else [goto]
    authorization = authorize_route_result(state, source_stage, targets)
    if authorization.accepted:
        return None
    diagnostic = authorization.diagnostic
    if diagnostic is None:
        return command
    update = dict(command.update or {})
    update.update(terminal_patch(diagnostic_terminal(diagnostic)))
    return Command(update=update, goto=END_DIAGNOSTIC)


async def execute_tools_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Load tool/model registrations only when a tool stage is executed."""
    from app.workflow.tools.execute_node import execute_tools_node as _execute_tools_node
    return await _execute_tools_node(state)


# TimeoutPolicy + error_handler for node-level fault tolerance (LangGraph v1.2)
try:
    from langgraph.types import RetryPolicy
    _HAS_RETRY_POLICY = True
    _TRANSIENT_RETRY_POLICY = RetryPolicy(
        max_attempts=3,
        retry_on=(TimeoutError, OSError, ConnectionError),
    )
except ImportError:
    _HAS_RETRY_POLICY = False
    _TRANSIENT_RETRY_POLICY = None


async def analyze_dimension_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """维度分析节点"""
    return await analyze_dimension(state)


async def _audited_dimension_worker(worker, state: Dict[str, Any]) -> Dict[str, Any]:
    """Preserve provider failures as a merge-safe parallel event channel."""
    patch = await worker(state)
    if isinstance(patch, dict) and isinstance(patch.get("fatal_error"), dict):
        patch = dict(patch)
        patch["provider_failures"] = [dict(patch["fatal_error"])]
    return patch


async def audited_l1_worker(state: Dict[str, Any]) -> Dict[str, Any]:
    return await _audited_dimension_worker(l1_worker_node, state)


async def audited_l2_worker(state: Dict[str, Any]) -> Dict[str, Any]:
    return await _audited_dimension_worker(l2_worker_node, state)


async def audited_l3_worker(state: Dict[str, Any]) -> Dict[str, Any]:
    return await _audited_dimension_worker(l3_worker_node, state)


# ── Wave M: post-L3 gate routers over the materialized stage view ──────


_BUSINESS_RETRY_ROUTES = {
    "target_projection": {"REPAIR", "REVISE"},
    "ground": {"EXPLORE"},
    "select": {"RETRY_GROUND"},
    "validate": {"RETRY_EXECUTE", "RETRY_SELECT", "RETRY_GROUND", "RETRY_TARGET_PROJECTION"},
    "reconcile": {"RETRY_EXECUTE"},
    "deliver": {"RETRY_VALIDATE"},
}


def _retry_limit(state: Dict[str, Any]) -> int:
    configured = state.get("max_retries")
    return 3 if configured is None else max(0, int(configured))


def _exhausted_retry_stage(state: Dict[str, Any]) -> str | None:
    """Find the downstream-most retry gate whose persisted budget is spent."""
    counts = state.get("retry_counts") or {}
    limit = _retry_limit(state)
    for stage in ("deliver", "reconcile", "validate", "select", "ground", "target_projection"):
        route = root_gate_route(state, stage)
        if route in _BUSINESS_RETRY_ROUTES[stage] and int(counts.get(stage, 0)) >= limit:
            return stage
    return None


def _retry_exhaustion_patch(state: Dict[str, Any]) -> Dict[str, Any]:
    """Build the explicit state update persisted by the diagnostic node."""
    stage = _exhausted_retry_stage(state)
    if stage is None:
        return {}
    try:
        gate = _dump(load_root_gate(state, stage))
    except Exception:
        gate = {
            "stage": stage,
            "passed": False,
            "feedback_route": "END_DIAGNOSTIC",
            "diagnostic_code": "ROOT_GATE_ARTIFACT_UNAVAILABLE",
        }
    gate["feedback_route"] = "END_DIAGNOSTIC"
    gate.setdefault("diagnostic_code", f"{stage.upper()}_RETRY_EXHAUSTED")
    gate_patch = _gate_mutation_patch(state, stage, gate)
    current = int((state.get("retry_counts") or {}).get(stage, 0))
    limit = _retry_limit(state)
    return {
        **gate_patch,
        "paused_stage": stage,
        "delivery_status": "diagnostic_only",
        "diagnostic_terminal": {
            "stage": stage,
            "issue_fingerprint": str(gate.get("issue_fingerprint") or ""),
            "reason": "business_retry_exhausted",
            "retry_count": current,
            "retry_limit": limit,
        },
    }


def _retry_or_human(state: Dict[str, Any], stage: str, retry_target: str) -> str:
    """Pick retry_target or diagnostic termination based on the retry cap."""
    counts = dict(state.get("retry_counts") or {})
    current = counts.get(stage, 0)
    max_retries = _retry_limit(state)
    if stage == "validate":
        try:
            gate = load_root_gate(state, "validate")
        except Exception:
            return END_DIAGNOSTIC
        current_fingerprint = gate.issue_fingerprint
        previous = (state.get("stage_audit") or {}).get("VALIDATE", {})
        previous_fingerprint = str(previous.get("issue_fingerprint") or "")
        if current_fingerprint and current_fingerprint == previous_fingerprint:
            logger.warning(
                "[main] VALIDATE repeated issue fingerprint %s -> HUMAN",
                current_fingerprint,
            )
            return "human_review"
    if current >= max_retries:
        logger.warning("[main] %s retry exceeded %d rounds -> diagnostic", stage, max_retries)
        return END_DIAGNOSTIC
    logger.info("[main] %s retry %d/%d -> %s", stage, current + 1, max_retries, retry_target)
    return retry_target


def route_after_target_projection(state: Dict[str, Any]) -> str:
    route = root_gate_route(state, "target_projection")
    if route == GATE_LOAD_FAILED:
        return END_DIAGNOSTIC
    if route == "PASS":
        return "ground"
    if route in ("REPAIR", "REVISE"):
        return _retry_or_human(state, "target_projection", "target_projection")
    return "human_review"


def route_after_ground(state: Dict[str, Any]) -> str:
    route = root_gate_route(state, "ground")
    if route == GATE_LOAD_FAILED:
        return END_DIAGNOSTIC
    if route == "PASS":
        return "select"
    if route == "EXPLORE":
        return _retry_or_human(state, "ground", "ground")
    return "human_review"


def route_after_select(state: Dict[str, Any]) -> str:
    route = root_gate_route(state, "select")
    if route == GATE_LOAD_FAILED:
        return END_DIAGNOSTIC
    if route == "PASS":
        return "execute"
    if route == "RETRY_GROUND":
        return _retry_or_human(state, "select", "ground")
    return "human_review"


def route_after_execute(state: Dict[str, Any]) -> str:
    if isinstance(state.get("fatal_error"), dict):
        return END_DIAGNOSTIC
    return "validate"


def route_after_validate(state: Dict[str, Any]) -> str:
    route = root_gate_route(state, "validate")
    if route == GATE_LOAD_FAILED:
        return END_DIAGNOSTIC
    if route == "PASS":
        return "reconcile"
    if route == "END_DIAGNOSTIC":
        return "reconcile"
    if route in ("RETRY_EXECUTE", "RETRY_SELECT", "RETRY_GROUND", "RETRY_TARGET_PROJECTION"):
        stage_map = {
            "RETRY_EXECUTE": "validate",
            "RETRY_SELECT": "validate",
            "RETRY_GROUND": "validate",
            "RETRY_TARGET_PROJECTION": "validate",
        }
        return _retry_or_human(state, stage_map.get(route, "validate"), route[6:].lower())
    if route == "RETRY_L3":
        return "human_review"
    return "human_review"


def route_after_reconcile(state: Dict[str, Any]) -> str:
    route = root_gate_route(state, "reconcile")
    if route == GATE_LOAD_FAILED:
        return END_DIAGNOSTIC
    if route == "PASS":
        return "deliver"
    if route == "END_DIAGNOSTIC":
        return "deliver"
    if route == "RETRY_EXECUTE":
        return _retry_or_human(state, "reconcile", "execute")
    if route == "RETRY_L3":
        return "human_review"
    return "human_review"


def route_after_deliver(state: Dict[str, Any]) -> str:
    route = root_gate_route(state, "deliver")
    if route == GATE_LOAD_FAILED:
        return END_DIAGNOSTIC
    if route == "PASS":
        return END
    return END_DIAGNOSTIC


def _root_gate_payload(state: Dict[str, Any], stage: str) -> Dict[str, Any]:
    """Return a serialized, typed root gate; never fall back to inline data."""

    return _dump(load_root_gate(state, stage))


def _gate_mutation_patch(
    state: Dict[str, Any],
    stage: str,
    gate: Any,
    *,
    artifact_refs: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """Persist a root gate mutation as a new CAS gate artifact.

    Every mutation gets a new immutable descriptor and publishes both the
    named stage ref and the generic ``gate_ref`` in the same graph patch.
    """

    normalized_stage = str(stage or "").strip().lower()
    serialized = _dump(gate)
    if normalized_stage not in GATE_STAGES:
        raise ValueError(f"unsupported root gate mutation stage: {stage}")

    refs = {
        **dict(state.get("artifact_refs") or {}),
        **dict(artifact_refs or {}),
    }
    gate_ref = persist_gate_decision(
        state,
        normalized_stage,
        serialized,
        output_refs=refs,
    )
    gate_ref_data = gate_ref.model_dump(mode="json")
    return {
        f"{normalized_stage}_gate": serialized,
        "artifact_refs": {
            **refs,
            f"{normalized_stage}_gate": gate_ref_data,
        },
        "gate_ref": gate_ref_data,
    }


def _remaining_unresolved_target_ids(state: Dict[str, Any]) -> list[str]:
    """Return unresolved target IDs still represented by the blocking gate."""
    remaining = state.get("remaining_target_ids") or []
    target_ids = [str(target_id) for target_id in remaining if str(target_id)] if isinstance(remaining, list) else []
    try:
        gate = load_root_gate(state, "ground")
    except Exception:
        return target_ids
    pending = gate.pending_requests
    for request in pending or []:
        context = request.get("context") if isinstance(request, dict) else getattr(request, "context", {})
        if not isinstance(context, dict):
            continue
        ids = context.get("remaining_target_ids") or []
        target_ids.extend(str(target_id) for target_id in ids if str(target_id))
    return list(dict.fromkeys(target_ids))


def route_after_human_review(state: Dict[str, Any]) -> str:
    """Route post-HITL resume: approve forwards, reject goes to conversation."""
    paused_stage = _normalize_paused_stage(state.get("paused_stage"))
    if paused_stage in {
        "target_projection", "ground", "select", "validate", "reconcile", "deliver",
    } and root_gate_route(state, paused_stage) == GATE_LOAD_FAILED:
        return END_DIAGNOSTIC
    if state.get("delivery_status") == "diagnostic_only":
        decisions = state.get("human_review_decisions") or {}
        action = decisions.get("action") if isinstance(decisions, dict) else None
        if action in ("accept", "approve") and paused_stage in {"validate", "reconcile"}:
            return END_DIAGNOSTIC
        if paused_stage == "validate":
            return "reconcile"
        if paused_stage == "reconcile":
            return "deliver"
        return END_DIAGNOSTIC
    if state.get("fatal_error"):
        return END
    decisions = state.get("human_review_decisions") or {}
    action = decisions.get("action") if isinstance(decisions, dict) else None
    if action in ("accept", "approve"):
        if state.get("classification_revision"):
            return "target_projection"
        if paused_stage in {"validate", "reconcile"}:
            if state.get("delivery_status") == "diagnostic_only":
                return END_DIAGNOSTIC
            if state.get("structural_deferral_revision"):
                return "execute"
            return END_DIAGNOSTIC
        # Approving a layer gate means continue processing.  Unresolved
        # spatial facts must remain unresolved and be handled by projection/GROUND;
        # they must not send an approved L3 checkpoint back to HUMAN.
        if paused_stage in {"l1", "l2", "l3"}:
            target = _STAGE_FORWARD_TARGET.get(paused_stage)
            if target:
                return END if target == "__end__" else target
        if (
            paused_stage == "select"
            and isinstance(decisions, dict)
            and decisions.get("defer_unresolved_spatial_references") is True
        ):
            return "execute" if state.get("human_deferred_select_revision") else "human_review"
        if paused_stage == "select":
            # Approval is an explicit human override of the SELECT gate. The
            # decision has already been recorded in the checkpoint; do not
            # re-enter HUMAN solely because stale unresolved-target metadata
            # survived the gate revision.
            return "execute"
        if _remaining_unresolved_target_ids(state):
            return "human_review"
        if (
            paused_stage == "ground"
            and isinstance(decisions, dict)
            and decisions.get("defer_unresolved_spatial_references") is True
        ):
            if root_gate_route(state, "ground") == "PASS":
                return "select"
            return "human_review"
        return END
    if action == "retry":
        if state.get("is_revision") and state.get("revision_target_dimensions"):
            return "revision_dispatch"
        retry_stage = paused_stage if paused_stage else "target_projection"
        if retry_stage in {"validate", "reconcile"}:
            try:
                gate = load_root_gate(state, retry_stage)
            except Exception:
                return END_DIAGNOSTIC
            progress_made = gate.progress_made
            inputs_changed = gate.inputs_changed
            if progress_made is False or inputs_changed is False:
                return END_DIAGNOSTIC
        configured_limit = state.get("max_retries")
        max_retries = 3 if configured_limit is None else max(0, int(configured_limit))
        current = int((state.get("retry_counts") or {}).get(retry_stage, 0))
        if current >= max_retries:
            return END_DIAGNOSTIC
        return retry_stage
    if action == "reject":
        return "conversation"
    return END


def _normalize_paused_stage(value: Any) -> str | None:
    """Normalize layer aliases before applying a HUMAN decision."""
    stage = str(value or "").strip().lower()
    if stage.startswith("layer") and stage[5:].isdigit():
        return f"l{stage[5:]}"
    return stage or None


def _diagnostic_manifest_patch(
    state: Dict[str, Any],
    terminal: Dict[str, Any],
) -> Dict[str, Any]:
    """Persist the terminal diagnostic as the authoritative delivery artifact."""
    if not state.get("session_id"):
        return {}
    try:
        from app.infrastructure.artifacts.runtime import load_artifact
        from app.domain.delivery.aggregate import (
            build_traceability_from_coverage,
            mark_manifest_diagnostic,
        )
        from app.contracts.artifacts.deferral_contracts import DeferralLedger
        from app.contracts.artifacts.delivery_manifest_contracts import DeliveryManifest
        from app.contracts.workflow.execution_plan_contracts import ExecutionResult
        from app.contracts.artifacts.reconciliation_contracts import ReconciliationReport

        ledger = load_artifact(state, "deferral_ledger", DeferralLedger)
        outcome = load_artifact(state, "execution_result", ExecutionResult)
        reconciliation = load_artifact(
            state, "reconciliation_report", ReconciliationReport
        )
        existing = load_artifact(state, "delivery_manifest", DeliveryManifest)
        entries = list(getattr(ledger, "entries", None) or [])
        deferral_summary = {
            "count": len(entries),
            "target_ids": [entry.target_id for entry in entries],
            "actions": [entry.decision.action for entry in entries],
        }
        manifest = mark_manifest_diagnostic(
            existing,
            ledger=ledger,
            execution_result=outcome,
            reconciliation_report=reconciliation,
            terminal=terminal,
            deferral_summary=deferral_summary,
        )
        ref = persist_stage_artifact(
            state,
            "end_diagnostic",
            "DeliveryManifest",
            manifest,
        )
        return {
            "artifact_refs": {"delivery_manifest": ref},
            "deferral_summary": deferral_summary,
        }
    except Exception as exc:
        logger.warning("[main:end_diagnostic] manifest persistence failed: %s", exc)
        return {}


async def end_diagnostic_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Terminate a structurally blocked run without cycling upstream."""
    exhaustion_patch = _retry_exhaustion_patch(state)
    stage = str(
        exhaustion_patch.get("paused_stage")
        or state.get("paused_stage")
        or "post_l3"
    )
    try:
        gate = _dump(load_root_gate(state, stage))
    except Exception:
        gate = {}
    terminal = dict(
        exhaustion_patch.get("diagnostic_terminal")
        or state.get("diagnostic_terminal")
        or {}
    )
    terminal.setdefault("stage", stage)
    terminal.setdefault(
        "issue_fingerprint",
        gate.get("issue_fingerprint", "")
        if isinstance(gate, dict)
        else getattr(gate, "issue_fingerprint", ""),
    )
    terminal.setdefault("reason", "remaining_non_deferred_structural_blockers")
    return {
        **exhaustion_patch,
        "delivery_status": "diagnostic_only",
        "diagnostic_terminal": terminal,
        **_diagnostic_manifest_patch(state, terminal),
    }


def create_unified_planning_graph(checkpointer=None) -> StateGraph:
    """创建统一规划图 - 纯函数，每次返回新图。

    缓存责任由调用方承担（`PlanningRuntimeService._graph` 单例）。
    Wave M2: explore_node removed (EXPLORE is now gate-driven horizontal service).
    Wave M: post-L3 链拆为主图独立节点 (projection/ground/select/execute/validate/
    reconcile/deliver/human_review），L3 gate PASS 后经 advance_phase 自动进入
    target projection，不再依赖 gis_agent 黑盒节点。
    """
    from app.workflow.conversation import after_conversation, after_analysis, conversation_node

    logger.info("[图构建] 构建规划图")
    builder = StateGraph(WorkflowState)

    builder.add_node("conversation", adapt_node(conversation_node))
    if _HAS_RETRY_POLICY:
        builder.add_node("execute_tools", adapt_node(execute_tools_node), retry_policy=_TRANSIENT_RETRY_POLICY)
    else:
        builder.add_node("execute_tools", adapt_node(execute_tools_node))
    builder.add_node("l1_worker", adapt_node(audited_l1_worker, worker=True))
    builder.add_node("l2_worker", adapt_node(audited_l2_worker, worker=True))
    builder.add_node("l3_worker", adapt_node(audited_l3_worker, worker=True))
    builder.add_node("advance_phase", adapt_node(_authorized_advance_phase))
    builder.add_node("revision_dispatch", adapt_node(_authorized_revision_dispatch))
    # Dynamic Send workers form one map super-step.  The completion barrier
    # must run once only after every pending worker branch has finished;
    # otherwise several completion/aggregate tasks can survive in the same
    # checkpoint and race the post-L3 chain.
    builder.add_node("layer_completion_check", adapt_node(layer_completion_check, worker=True), defer=True)
    builder.add_node("layer_aggregate", adapt_node(layer_aggregate_node, worker=True))
    builder.add_node("bootstrap_context", adapt_node(bootstrap_context_node))
    # ── Wave M: post-L3 主图独立节点 ──
    builder.add_node("target_projection", adapt_node(target_projection_node))
    builder.add_node("ground", adapt_node(ground_node))
    builder.add_node("select", adapt_node(select_node))
    builder.add_node("execute", adapt_node(execute_node))
    builder.add_node("validate", adapt_node(validate_node))
    builder.add_node("reconcile", adapt_node(reconcile_node))
    builder.add_node("deliver", adapt_node(deliver_node))
    builder.add_node("human_review_prepare", adapt_node(prepare_human_review))
    builder.add_node("human_review_publish", adapt_node(publish_human_review_pause))
    builder.add_node("human_review_wait", adapt_node(await_human_review))
    builder.add_node("human_review_apply", adapt_node(apply_human_review_decision))
    builder.add_node(END_DIAGNOSTIC, adapt_node(end_diagnostic_node))

    # Build the authoritative data context before any model or dimension
    # worker runs.  Raw documents stay in the data layer; the checkpoint only
    # carries the resulting context/artifact references.
    builder.add_edge(START, "bootstrap_context")
    builder.add_conditional_edges("conversation", lambda state: _dispatch_route("conversation", after_conversation, state),
        {"execute_tools": "execute_tools", "target_projection": "target_projection",
         "l1_worker": "l1_worker", "l2_worker": "l2_worker", "l3_worker": "l3_worker",
         END: END})
    builder.add_conditional_edges("execute_tools", lambda state: _dispatch_fixed("execute_tools", "conversation", state),
        {"conversation": "conversation", END_DIAGNOSTIC: END_DIAGNOSTIC})
    builder.add_conditional_edges("bootstrap_context", lambda state: _dispatch_fixed("bootstrap_context", "conversation", state),
        {"conversation": "conversation", END_DIAGNOSTIC: END_DIAGNOSTIC})
    builder.add_conditional_edges("l1_worker", lambda state: _dispatch_fixed("l1_worker", "layer_completion_check", state),
        {"layer_completion_check": "layer_completion_check", END_DIAGNOSTIC: END_DIAGNOSTIC})
    builder.add_conditional_edges("l2_worker", lambda state: _dispatch_fixed("l2_worker", "layer_completion_check", state),
        {"layer_completion_check": "layer_completion_check", END_DIAGNOSTIC: END_DIAGNOSTIC})
    builder.add_conditional_edges("l3_worker", lambda state: _dispatch_fixed("l3_worker", "layer_completion_check", state),
        {"layer_completion_check": "layer_completion_check", END_DIAGNOSTIC: END_DIAGNOSTIC})
    builder.add_conditional_edges("layer_completion_check", lambda state: _dispatch_fixed("layer_completion_check", "layer_aggregate", state),
        {"layer_aggregate": "layer_aggregate", END_DIAGNOSTIC: END_DIAGNOSTIC})
    builder.add_conditional_edges("layer_aggregate", lambda state: _dispatch_route("layer_aggregate", after_analysis, state),
        {"advance_phase": "advance_phase", "target_projection": "target_projection", "conversation": "conversation",
         "l1_worker": "l1_worker", "l2_worker": "l2_worker", "l3_worker": "l3_worker",
         "human_review": "human_review_prepare",
         END: END})
    # ── Wave M: post-L3 主图链条件边 ──
    builder.add_conditional_edges("target_projection", lambda state: _dispatch_route("target_projection", route_after_target_projection, state),
        {"ground": "ground", "target_projection": "target_projection", "human_review": "human_review_prepare",
         END_DIAGNOSTIC: END_DIAGNOSTIC})
    builder.add_conditional_edges("ground", lambda state: _dispatch_route("ground", route_after_ground, state),
        {"select": "select", "ground": "ground", "human_review": "human_review_prepare",
         END_DIAGNOSTIC: END_DIAGNOSTIC})
    builder.add_conditional_edges("select", lambda state: _dispatch_route("select", route_after_select, state),
        {"execute": "execute", "ground": "ground", "human_review": "human_review_prepare",
         END_DIAGNOSTIC: END_DIAGNOSTIC})
    builder.add_conditional_edges("execute", lambda state: _dispatch_route("execute", route_after_execute, state),
        {"validate": "validate", END_DIAGNOSTIC: END_DIAGNOSTIC})
    builder.add_conditional_edges("validate", lambda state: _dispatch_route("validate", route_after_validate, state),
        {"reconcile": "reconcile", "execute": "execute", "select": "select",
         "ground": "ground", "target_projection": "target_projection", "human_review": "human_review_prepare",
         END_DIAGNOSTIC: END_DIAGNOSTIC})
    builder.add_conditional_edges("reconcile", lambda state: _dispatch_route("reconcile", route_after_reconcile, state),
        {"deliver": "deliver", "execute": "execute", "human_review": "human_review_prepare",
         END_DIAGNOSTIC: END_DIAGNOSTIC})
    builder.add_conditional_edges("deliver", lambda state: _dispatch_route("deliver", route_after_deliver, state),
        {END: END, END_DIAGNOSTIC: END_DIAGNOSTIC})
    builder.add_conditional_edges("human_review_prepare", lambda state: _dispatch_fixed("human_review_prepare", "human_review_publish", state),
        {"human_review_publish": "human_review_publish", END_DIAGNOSTIC: END_DIAGNOSTIC})
    builder.add_conditional_edges("human_review_publish", lambda state: _dispatch_fixed("human_review_publish", "human_review_wait", state),
        {"human_review_wait": "human_review_wait", END_DIAGNOSTIC: END_DIAGNOSTIC})
    builder.add_conditional_edges("human_review_wait", lambda state: _dispatch_fixed("human_review_wait", "human_review_apply", state),
        {"human_review_apply": "human_review_apply", END_DIAGNOSTIC: END_DIAGNOSTIC})
    builder.add_conditional_edges("human_review_apply", lambda state: _dispatch_route("human_review_apply", route_after_human_review, state),
        {"advance_phase": "advance_phase",
         "revision_dispatch": "revision_dispatch",
         "l1_worker": "l1_worker", "l2_worker": "l2_worker", "l3_worker": "l3_worker",
         "target_projection": "target_projection", "ground": "ground", "select": "select",
         "execute": "execute", "validate": "validate", "reconcile": "reconcile",
         "deliver": "deliver", "conversation": "conversation",
         "human_review": "human_review_prepare",
         END_DIAGNOSTIC: END_DIAGNOSTIC, END: END})
    builder.add_edge(END_DIAGNOSTIC, END)

    return builder.compile(checkpointer=checkpointer)


async def prepare_human_review(state: Dict[str, Any]) -> Dict[str, Any]:
    """Pure HITL preparation; no external side effects."""
    paused_stage, items = collect_human_review_items(state)
    # Routing functions are intentionally pure and cannot persist a gate
    # mutation while selecting ``human_review``.  When a layer contract or
    # retry budget routes directly from ``after_analysis`` to HUMAN, promote
    # that decision here before building the interrupt payload.  Otherwise
    # the graph would reach the HUMAN branch with an L3 gate still labelled
    # ``L3`` and collect no review items, silently ending instead of pausing.
    gate_patch = {}
    if not items or paused_stage == "post_l3":
        for gate_stage in (
            # Scan downstream stages first; stale upstream EXPLORE gates are
            # retained for audit but must not steal a later HUMAN pause.
            "deliver", "reconcile", "validate", "select", "ground",
            "target_projection",
            "l3", "l2", "l1",
        ):
            try:
                gate_model = load_root_gate(state, gate_stage)
            except Exception:
                continue
            gate = gate_model.model_dump(mode="json")
            pending = list(gate.get("pending_requests") or [])
            route = gate.get("feedback_route")
            if pending and route not in {None, "PASS", "HUMAN"}:
                paused_stage = gate_stage
                items = pending
                if gate_stage in {"l1", "l2", "l3"}:
                    human_gate = dict(gate)
                    human_gate["feedback_route"] = "HUMAN"
                    human_gate.setdefault("diagnostic_code", "BUSINESS_GATE_REVIEW_REQUIRED")
                    gate_patch.update(_gate_mutation_patch(state, gate_stage, human_gate))
                break
    if not items:
        # Layer gates can legitimately route HUMAN with only a structured
        # decision (for example an empty L2 strategy) and no pending request.
        # Do not let that branch fall through to await_human_review with an
        # empty item list: the graph would terminate while the session still
        # reports the previous layer.  Synthesize one actionable review item
        # so the operator can explicitly approve or revise the gate.
        for gate_stage in ("l3", "l2", "l1"):
            try:
                gate = _root_gate_payload(state, gate_stage)
            except Exception:
                continue
            if not isinstance(gate, dict) or gate.get("feedback_route") != "HUMAN":
                continue
            paused_stage = gate_stage
            items = [{
                "request_id": f"{paused_stage}-gate-review",
                "stage": paused_stage,
                "request_type": "gate_review",
                "context": {
                    "message": gate.get("diagnostic_code") or "Gate requires explicit human review",
                    "evidence_requests": list(gate.get("evidence_requests") or []),
                },
            }]
            break
    if not items:
        for gate_stage in ("deliver", "reconcile", "validate", "select", "ground", "target_projection"):
            try:
                gate = load_root_gate(state, gate_stage)
            except Exception:
                continue
            if gate.feedback_route != "HUMAN":
                continue
            paused_stage = gate_stage
            items = [
                {
                    "request_id": f"{gate_stage}-gate-review",
                    "stage": gate_stage,
                    "request_type": "gate_review",
                    "context": {
                        "message": gate.route_reason or "Gate requires explicit human review",
                        "evidence_requests": list(gate.evidence_requests),
                    },
                }
            ]
            break
    if not items:
        # A layer can reach this branch when dependency scheduling has no
        # ready node but the layer is still incomplete. Do not let that
        # structural deadlock disappear as an unexplained END; expose the
        # exact missing dimensions for human review.
        phase = str(state.get("phase") or "")
        if phase in {"layer1", "layer2", "layer3"}:
            from app.config.loader import list_dimensions

            expected = {d.key for d in list_dimensions(int(phase[-1]))}
            completed = set(
                (state.get("completed_dimensions") or {}).get(phase, [])
            )
            missing = sorted(expected - completed)
            if missing:
                paused_stage = phase
                items = [{
                    "request_id": f"{phase}-dependency-deadlock",
                    "stage": phase,
                    "request_type": "dependency_deadlock_review",
                    "context": {
                        "message": "当前层仍未完成且没有可派发的依赖就绪维度。",
                        "completed_dimensions": sorted(completed),
                        "missing_dimensions": missing,
                    },
                }]
                gate_patch.update(_gate_mutation_patch(state, f"l{phase[-1]}", {
                    "stage": f"l{phase[-1]}",
                    "passed": False,
                    "feedback_route": "HUMAN",
                    "diagnostic_code": "LAYER_DEPENDENCY_DEADLOCK",
                    "pending_requests": items,
                }))

    if not items:
        failures = state.get("provider_failures") or []
        failure = failures[0] if failures and isinstance(failures[0], dict) else None
        if failure:
            paused_stage = str(failure.get("stage") or state.get("phase") or "layer3").lower()
            if paused_stage.startswith("layer"):
                paused_stage = paused_stage.replace("layer", "l")
            items = [{
                "request_id": f"{paused_stage}-provider-failure",
                "stage": paused_stage,
                "request_type": "transient_llm_failure",
                "context": dict(failure),
            }]
            gate_patch["fatal_error"] = dict(failure)
    generation = int(state.get("human_review_generation") or 0)
    if state.get("human_review_resume_consumed") and state.get("human_review_event_id"):
        generation += 1
    event_id = stable_human_interrupt_id(
        str(state.get("session_id") or ""),
        HumanInterruptChannel.POST_L3_REVIEW,
        paused_stage=paused_stage,
        items=items,
        retry_counts=state.get("retry_counts"),
        generation=generation,
    )
    human_interrupt = build_human_interrupt(
        event_id=event_id,
        channel=HumanInterruptChannel.POST_L3_REVIEW,
        items=items,
        paused_stage=paused_stage,
        error_feedback=dict(state.get("error_feedback") or {}),
    )
    return {
        **gate_patch,
        "human_interrupt": human_interrupt,
        "human_review_items": items,
        "paused_stage": paused_stage,
        "human_review_event_id": event_id,
        "human_review_generation": generation,
        "human_review_pause_published": False,
        "human_review_resume_consumed": False,
    }


async def publish_human_review_pause(state: Dict[str, Any]) -> Dict[str, Any]:
    """Idempotently publish the pause notification."""
    interrupt_payload = state.get("human_interrupt") or {}
    items = interrupt_payload.get("items") or state.get("human_review_items") or []
    if not items or state.get("human_review_pause_published"):
        return {"human_review_pause_published": True}
    session_id = state.get("session_id")
    if session_id:
        try:
            from app.infrastructure.events import event_hub as sse_manager
            await sse_manager.publish(session_id, {
                "type": SSEEventType.HUMAN_REVIEW_PAUSED,
                "event_id": interrupt_payload.get("event_id") or state.get("human_review_event_id"),
                "channel": interrupt_payload.get("channel", HumanInterruptChannel.POST_L3_REVIEW.value),
                "reason": interrupt_payload.get("reason", "human_review_required"),
                "items": items,
                "paused_stage": interrupt_payload.get("paused_stage") or state.get("paused_stage"),
                "item_count": len(items),
            })
        except Exception as exc:
            logger.warning("[main:human_review] SSE publish failed: %s", exc)
            return {"human_review_pause_published": False}
    return {"human_review_pause_published": True}


async def await_human_review(state: Dict[str, Any]) -> Dict[str, Any]:
    """The only node containing interrupt(); it has no pre-interrupt effects."""
    from langgraph.types import interrupt
    interrupt_payload = state.get("human_interrupt") or {}
    items = interrupt_payload.get("items") or state.get("human_review_items") or []
    paused_stage = interrupt_payload.get("paused_stage") or state.get("paused_stage")
    if not items:
        return {"human_review_decisions": {}}
    if not interrupt_payload:
        interrupt_payload = build_human_interrupt(
            event_id=str(state.get("human_review_event_id") or "unknown-human-interrupt"),
            channel=HumanInterruptChannel.POST_L3_REVIEW,
            items=items,
            paused_stage=paused_stage,
            error_feedback=dict(state.get("error_feedback") or {}),
        )
    decisions = interrupt(interrupt_payload)
    return {"human_review_decisions": normalize_human_decision(decisions)}


def _revision_waves(dimensions: List[str]) -> Dict[int, List[str]]:
    """Topologically order explicitly rejected dimensions within one layer."""
    from app.config import get_dimension_config

    remaining = set(dimensions)
    completed: set[str] = set()
    waves: Dict[int, List[str]] = {}
    wave = 0
    while remaining:
        ready = sorted(
            dimension
            for dimension in remaining
            if not (set(getattr(get_dimension_config(dimension), "depends_on", []) or []) & remaining)
        )
        if not ready:
            ready = sorted(remaining)
        waves[wave] = ready
        remaining.difference_update(ready)
        completed.update(ready)
        wave += 1
    return waves


def _revision_feedback(items: List[Dict[str, Any]], supplied: str) -> str:
    findings = []
    for item in items:
        context = item.get("context") if isinstance(item, dict) else {}
        if not isinstance(context, dict):
            continue
        message = str(context.get("message") or "").strip()
        detail = str(context.get("detail") or "").strip()
        if message:
            findings.append(f"{message}：{detail}" if detail else message)
    requirements = (
        "只输出可实施的规划项目，不得把现状描述、数据缺失说明或分析结论当作干预项目；"
        "最终回答必须包含字面量【INSTRUCTION】及固定列规划表，所有空间项目必须填写有证据支持的位置。"
    )
    return "\n".join(part for part in [supplied.strip(), *dict.fromkeys(findings), requirements] if part)


async def apply_human_review_decision(state: Dict[str, Any]) -> Dict[str, Any]:
    """Apply an already-resumed decision, creating a new gate revision."""
    items = state.get("human_review_items") or []
    paused_stage = _normalize_paused_stage(state.get("paused_stage"))
    decisions = state.get("human_review_decisions") or {}
    if not items:
        return {"human_interrupt": None, "human_review_items": [], "paused_stage": None}
    result = {
        "human_review_items": items,
        "paused_stage": paused_stage,
        "human_review_decisions": decisions,
        "human_review_resume_consumed": True,
        "human_interrupt": None,
    }
    action = decisions.get("action") if isinstance(decisions, dict) else None
    classification_payload = (
        decisions.get("classification_decisions")
        if isinstance(decisions, dict)
        else None
    )
    if action in ("accept", "approve") and classification_payload is not None:
        classification_patch = await _apply_classification_revision(state, decisions)
        result.update(classification_patch)
        if classification_patch.get("fatal_error"):
            result["delivery_status"] = "diagnostic_only"
            return result
        return result

    if (
        action in ("accept", "approve")
        and paused_stage == "l3"
        and any(
            str(item.get("request_type") or "") == "classification_decision_required"
            for item in items
            if isinstance(item, dict)
        )
    ):
        result.update({
            "fatal_error": {
                "stage": "l3",
                "code": "CLASSIFICATION_DECISIONS_REQUIRED",
                "message": "Approve cannot bypass unresolved spatial classification decisions.",
            },
            "delivery_status": "diagnostic_only",
        })
        return result
    deferral_patch = {}
    deferred_target_ids: list[str] = []
    if action in ("accept", "approve") and paused_stage in {"validate", "reconcile"}:
        raw_ids = decisions.get("deferred_target_ids") if isinstance(decisions, dict) else None
        deferred_target_ids = list(dict.fromkeys(
            str(target_id).strip()
            for target_id in (raw_ids or [])
            if str(target_id).strip()
        ))
        if deferred_target_ids:
            result.update(await _apply_structural_target_deferrals(
                state,
                decisions,
                deferred_target_ids,
                paused_stage,
            ))
            return result
        gate = _root_gate_payload(state, paused_stage)
        gate.update({
            "stage": paused_stage,
            "passed": False,
            "feedback_route": "END_DIAGNOSTIC",
            "route_reason": "human_accept_cannot_override_structural_failure",
        })
        result.update({
            **_gate_mutation_patch(state, paused_stage, gate),
            "delivery_status": "diagnostic_only",
            "structural_deferral_revision": False,
            "diagnostic_terminal": {
                "stage": paused_stage,
                "issue_fingerprint": str(gate.get("issue_fingerprint") or ""),
                "reason": "remaining_non_deferred_structural_blockers",
            },
        })
        return result
    if (
        action in ("accept", "approve")
        and paused_stage in {"ground", "select"}
        and isinstance(decisions, dict)
        and decisions.get("defer_unresolved_spatial_references") is True
    ):
        raw_ids = decisions.get("deferred_target_ids")
        if not isinstance(raw_ids, list) or not raw_ids:
            result["fatal_error"] = {
                "stage": paused_stage,
                "code": "HUMAN_DEFER_TARGET_IDS_REQUIRED",
                "message": "Explicit deferred_target_ids are required for spatial deferral.",
            }
            return result
        deferred_target_ids = list(dict.fromkeys(
            str(target_id).strip() for target_id in raw_ids if str(target_id).strip()
        ))
        if not deferred_target_ids:
            result["fatal_error"] = {
                "stage": paused_stage,
                "code": "HUMAN_DEFER_TARGET_IDS_REQUIRED",
                "message": "Explicit deferred_target_ids are required for spatial deferral.",
            }
            return result
        if paused_stage == "select":
            # SELECT can be blocked even when GROUND produced a candidate:
            # the candidate may lack usable geometry/anchor or fail the
            # target-level assignment contract.  Such a target is a SELECT
            # deferral, not a GROUND unresolved reference.  Requiring it to
            # appear in GroundingResult.unresolved incorrectly rejects valid
            # human decisions (and was the source of the 3-target mismatch
            # in the real MiniMax run).
            deferral_patch = await _record_select_target_deferrals(
                state, decisions, deferred_target_ids
            )
        else:
            deferral_patch = await _record_target_deferrals(
                state, decisions, deferred_target_ids
            )
        if deferral_patch.get("fatal_error"):
            return {**result, **deferral_patch}
        remaining_target_ids = deferral_patch.get("remaining_target_ids") or []
        if remaining_target_ids:
            result_artifact_refs = {
                **dict(state.get("artifact_refs") or {}),
                **dict(deferral_patch.get("artifact_refs") or {}),
            }
            ground_gate = _root_gate_payload(state, "ground")
            ground_gate.update({
                "stage": "ground",
                "passed": False,
                "feedback_route": "HUMAN",
                "diagnostic_code": "HUMAN_DEFER_SPATIAL_REMAINING",
                "pending_requests": [{
                    "request_id": "pr-ground-defer-remaining",
                    "stage": "ground",
                    "request_type": "spatial_reference_unresolved",
                    "context": {"remaining_target_ids": remaining_target_ids},
                }],
            })
            result.update({
                **_gate_mutation_patch(
                    state,
                    "ground",
                    ground_gate,
                    artifact_refs=result_artifact_refs,
                ),
                "human_deferred_targets": deferred_target_ids,
                "human_deferred_select_revision": False,
                "remaining_target_ids": remaining_target_ids,
            })
            if paused_stage == "select":
                select_gate = _root_gate_payload(state, "select")
                select_gate.update({
                    "stage": "select",
                    "passed": False,
                    "feedback_route": "HUMAN",
                    "diagnostic_code": "HUMAN_DEFER_SPATIAL_REMAINING",
                    "pending_requests": list(ground_gate["pending_requests"]),
                })
                result.update(
                    _gate_mutation_patch(
                        state,
                        "select",
                        select_gate,
                        artifact_refs=result.get("artifact_refs") or result_artifact_refs,
                    )
                )
            return result
    if action in ("accept", "approve") and paused_stage in {"l1", "l2", "l3"}:
        gate = _root_gate_payload(state, paused_stage)
        gate.update({
            "stage": paused_stage,
            "passed": True,
            "feedback_route": "PASS",
            "route_reason": "human_approved_layer_gate",
            "pending_requests": [],
        })
        result.update(_gate_mutation_patch(state, paused_stage, gate))
        result["post_l3_status"] = "auto_continue" if paused_stage == "l3" else ""
        return result
    if action == "retry" and paused_stage:
        configured_limit = state.get("max_retries")
        max_retries = 3 if configured_limit is None else max(0, int(configured_limit))
        current = int((state.get("retry_counts") or {}).get(paused_stage, 0))
        if paused_stage == "l3":
            dimensions = [
                str(dimension).strip()
                for dimension in (decisions.get("dimensions") or [])
                if str(dimension).strip()
            ] if isinstance(decisions, dict) else []
            if not dimensions:
                dimensions = list(dict.fromkeys(
                    str((item.get("context") or {}).get("dimension_key") or "").strip()
                    for item in items
                    if isinstance(item, dict)
                    and str((item.get("context") or {}).get("dimension_key") or "").strip()
                ))
            if not dimensions:
                result["fatal_error"] = {
                    "stage": "l3",
                    "code": "L3_REVISION_DIMENSIONS_REQUIRED",
                    "message": "L3 retry requires explicit rejected dimensions.",
                }
                return result
            counts = dict(state.get("retry_counts") or {})
            exhausted = [
                dimension
                for dimension in dimensions
                if int(counts.get(f"l3:{dimension}", 0)) >= max_retries
            ]
            if exhausted:
                result.update({
                    "delivery_status": "diagnostic_only",
                    "diagnostic_terminal": {
                        "stage": "l3",
                        "reason": "dimension_retry_exhausted",
                        "dimensions": exhausted,
                        "retry_limit": max_retries,
                    },
                })
                return result
            for dimension in dimensions:
                key = f"l3:{dimension}"
                counts[key] = int(counts.get(key, 0)) + 1
            result.update({
                "need_revision": True,
                "is_revision": True,
                "revision_target_dimensions": dimensions,
                "revision_impact_tree": _revision_waves(dimensions),
                "revision_completed_dims": {},
                "revision_feedback": _revision_feedback(
                    items,
                    str(decisions.get("feedback") or "") if isinstance(decisions, dict) else "",
                ),
                "retry_counts": counts,
                # The stale l3_gate CAS ref is left in place; the retry's
                # aggregate re-persists a fresh gate that overwrites it.
                "human_review_items": [],
                "paused_stage": None,
                "layer_just_completed": None,
                "fatal_error": None,
            })
            return result
        if paused_stage in {"ground", "select"} and _select_or_ground_inputs_unchanged(
            state, paused_stage
        ):
            # Retrying a stage whose inputs are byte-identical to the previous
            # attempt cannot make progress: GROUND would re-produce the same
            # candidates and SELECT would re-mark the same targets unplaced.
            # Escalate back to HUMAN and surface the deferral requirement
            # instead of looping the operator back into the same dead end.
            gate = _root_gate_payload(state, paused_stage)
            gate.update({
                "stage": paused_stage,
                "passed": False,
                "feedback_route": "HUMAN",
                "diagnostic_code": "HUMAN_RETRY_NO_PROGRESS",
                "pending_requests": list(gate.get("pending_requests") or []),
            })
            result.update({
                **_gate_mutation_patch(state, paused_stage, gate),
                "human_retry_no_progress": True,
            })
        elif current >= max_retries:
            gate = _root_gate_payload(state, paused_stage)
            gate.update({
                "stage": paused_stage,
                "passed": False,
                "feedback_route": "END_DIAGNOSTIC",
                "diagnostic_code": "BUSINESS_RETRY_EXHAUSTED",
            })
            result.update({
                **_gate_mutation_patch(state, paused_stage, gate),
                "delivery_status": "diagnostic_only",
                "diagnostic_terminal": {
                    "stage": paused_stage,
                    "reason": "business_retry_exhausted",
                    "retry_count": current,
                    "retry_limit": max_retries,
                },
            })
        elif (
            paused_stage in {"l1", "l2", "l3"}
            and isinstance(state.get("fatal_error"), dict)
            and state["fatal_error"].get("code") in {
                "llm_stream_timeout",
                "llm_timeout",
                "llm_provider_error",
                "llm_provider_circuit_open",
            }
        ):
            dimension = str(state["fatal_error"].get("dimension") or "")
            attempts = int((state.get("dimension_retry_counts") or {}).get(dimension, 0))
            limit = max(0, int(state.get("dimension_retry_limit", 1)))
            if attempts <= limit:
                # The retry action is an explicit operator decision.  Clear
                # only this infrastructure failure; the worker will create
                # a fresh attempt and increment the same dimension counter
                # if it fails again.
                result["fatal_error"] = None
            else:
                result["fatal_error"] = {
                    **state["fatal_error"],
                    "code": "LLM_DIMENSION_RETRY_EXHAUSTED",
                    "message": f"dimension {dimension} retry limit exhausted ({attempts}/{limit})",
                }
    if action in ("accept", "approve") and paused_stage:
        if (
            paused_stage == "l3"
            and isinstance(state.get("fatal_error"), dict)
            and state["fatal_error"].get("code") in {
                "llm_stream_timeout", "llm_timeout", "llm_provider_error",
                "llm_provider_circuit_open",
            }
        ):
            dimension = str(state["fatal_error"].get("dimension") or "")
            attempts = int((state.get("dimension_retry_counts") or {}).get(dimension, 0))
            limit = max(0, int(state.get("dimension_retry_limit", 1)))
            if attempts <= limit:
                result["fatal_error"] = None
            else:
                result["fatal_error"] = {
                    **state["fatal_error"],
                    "code": "LLM_DIMENSION_RETRY_EXHAUSTED",
                    "message": f"dimension {dimension} retry limit exhausted ({attempts}/{limit})",
                }
        result.update(
            _gate_mutation_patch(
                state,
                paused_stage,
                _pass_gate(paused_stage),
            )
        )
        if isinstance(state.get("provider_failures"), list) and state.get("provider_failures"):
            result["provider_failures"] = []
        if (
            paused_stage in {"ground", "select"}
            and isinstance(decisions, dict)
            and decisions.get("defer_unresolved_spatial_references") is True
        ):
            # A human may explicitly defer targets for which the uploaded GIS
            # has no authoritative geometry.  This is not a candidate
            # fallback: create a new SELECT artifact revision that records the
            # deferred target ids, then let EXECUTE consume only the proven
            # selections.  The old failed artifact remains immutable.
            if paused_stage == "select":
                result.update(
                    await _apply_deferred_select_review(state, deferred_target_ids)
                )
            else:
                # GROUND can pause before SELECT has emitted its typed
                # decision. Preserve the stage boundary and let SELECT build
                # its own artifact from the persisted GroundingResult.
                ground_gate = _root_gate_payload(state, "ground")
                ground_gate.update({
                    "stage": "ground",
                    "passed": True,
                    "feedback_route": "PASS",
                    "diagnostic_code": "HUMAN_DEFERRED_UNRESOLVED_SPATIAL",
                    "pending_requests": [],
                })
                result.update(
                    _gate_mutation_patch(state, "ground", ground_gate)
                )
                result.update({
                    "human_deferred_targets": deferred_target_ids,
                    "human_deferred_select_revision": False,
                })
            if deferral_patch.get("artifact_refs"):
                result["artifact_refs"] = {
                    **(result.get("artifact_refs") or {}),
                    **deferral_patch["artifact_refs"],
                }
            for key, value in deferral_patch.items():
                if key != "artifact_refs":
                    result[key] = value
    elif action == "reject":
        feedback = decisions.get("feedback") if isinstance(decisions, dict) else None
        result["messages"] = [HumanMessage(content=feedback or "方案已拒绝，请调整后重新规划")]
    return result


def _select_or_ground_inputs_unchanged(state: Dict[str, Any], stage: str) -> bool:
    """Whether a retry of ``stage`` (ground/select) would reuse identical inputs.

    Uses the gate's persisted ``inputs_changed`` fingerprint (set by
    ``gate_progress_metadata``).  When the previous run already reported
    unchanged inputs, re-running the stage cannot change its outcome.
    """
    try:
        gate = _root_gate_payload(state, stage)
    except Exception:
        return True
    if gate.get("inputs_changed") is False:
        return True
    return False


def _human_review_blocking_target_ids(
    state: Dict[str, Any], stage: str
) -> tuple[set[str], int]:
    """Read the active HUMAN evidence, regardless of which gate stored it.

    A gate may normalize ``pending_requests`` to an empty list before the
    interrupt is persisted.  The interrupt item is then the authoritative
    evidence for the target-level decision shown to the operator.
    """
    try:
        gate = load_root_gate(state, stage)
        pending = list(gate.pending_requests or [])
    except Exception:
        pending = []
    items = state.get("human_review_items") or []
    target_ids: set[str] = set()
    non_target_blocker_count = 0
    for request in [*pending, *items]:
        context = (
            request.get("context")
            if isinstance(request, dict)
            else getattr(request, "context", {})
        ) or {}
        if not isinstance(context, dict):
            non_target_blocker_count += 1
            continue
        request_target_ids = context.get("target_ids")
        if isinstance(request_target_ids, list):
            target_ids.update(
                str(target_id) for target_id in request_target_ids if str(target_id)
            )
        elif request_target_ids is None:
            non_target_blocker_count += 1
        non_target_blocker_count += int(context.get("non_target_blocker_count") or 0)
    return target_ids, non_target_blocker_count


async def _apply_classification_revision(
    state: Dict[str, Any],
    decisions: Dict[str, Any],
) -> Dict[str, Any]:
    """Persist an explicit classification revision and restart spatial stages."""
    from app.domain.program.classification import revise_program_with_decisions
    from app.infrastructure.artifacts.runtime import load_artifact
    from app.contracts.domain.l3_contracts import PlanningProgram

    raw = decisions.get("classification_decisions")
    program = load_artifact(state, "planning_program", PlanningProgram)
    if program is None:
        return {
            "fatal_error": {
                "stage": "l3",
                "code": "CLASSIFICATION_PROGRAM_MISSING",
                "message": "Classification revision requires the canonical PlanningProgram artifact.",
            }
        }
    try:
        revised, target_ids = revise_program_with_decisions(program, raw)
    except (TypeError, ValueError) as exc:
        return {
            "fatal_error": {
                "stage": "l3",
                "code": "CLASSIFICATION_DECISION_INVALID",
                "message": str(exc),
            }
        }

    ref = persist_stage_artifact(
        state,
        "human_review",
        "PlanningProgram",
        revised,
    )
    gate_patch = _gate_mutation_patch(state, "l3", _pass_gate("l3"))
    return {
        **gate_patch,
        "artifact_refs": {
            **dict(gate_patch.get("artifact_refs") or {}),
            "planning_program": ref,
        },
        "classification_revision": True,
        "classification_decision_targets": target_ids,
    }


async def _apply_structural_target_deferrals(
    state: Dict[str, Any],
    decisions: Dict[str, Any],
    target_ids: list[str],
    stage: str,
) -> Dict[str, Any]:
    """Persist target deferrals and a new immutable execution-plan revision."""
    from app.domain.allocation.select_service import revise_site_selection_deferral
    from app.domain.delivery.deferral_ledger import append_ledger, build_target_deferrals
    from app.domain.materialization.plan_builder import defer_plan_tasks
    from app.infrastructure.artifacts.runtime import load_artifact
    from app.contracts.artifacts.deferral_contracts import DeferralLedger
    from app.contracts.workflow.execution_plan_contracts import (
        ExecutionResult,
        ExecutionPlan,
    )
    from app.contracts.domain.selection_contracts import SiteSelectionDecision

    plan = load_artifact(state, "execution_plan", ExecutionPlan)
    outcome = load_artifact(state, "execution_result", ExecutionResult)
    if plan is None or outcome is None:
        return {
            "fatal_error": {
                "stage": stage,
                "code": "HUMAN_DEFER_EXECUTION_ARTIFACT_MISSING",
                "message": "Structural deferral requires ExecutionPlan and ExecutionResult.",
            }
        }

    active_ids = {
        str(task.target_id) for task in plan.worker_tasks if str(task.target_id)
    }
    try:
        gate = _root_gate_payload(state, stage)
    except Exception:
        return {
            "fatal_error": {
                "stage": stage,
                "code": "ROOT_GATE_ARTIFACT_UNAVAILABLE",
                "message": f"Cannot apply HUMAN deferral without the {stage}_gate artifact.",
            }
        }
    gate_ids, non_target_blocker_count = _human_review_blocking_target_ids(state, stage)
    deferrable_ids = active_ids & gate_ids
    unknown = sorted(set(target_ids) - deferrable_ids)
    if unknown:
        return {
            "fatal_error": {
                "stage": stage,
                "code": "HUMAN_DEFER_TARGET_NOT_BLOCKING",
                "message": "Only currently blocking target IDs may be deferred: " + ", ".join(unknown),
            }
        }

    review_id = str(state.get("human_review_event_id") or "human-review")
    refs = state.get("artifact_refs") or {}
    report_key = "validation_report" if stage == "validate" else "reconciliation_report"
    source_refs = tuple(
        f"artifact:{key}:{(refs.get(key) or {}).get('descriptor_digest', key)}"
        for key in ("execution_result", report_key)
    )
    existing_ledger = load_artifact(state, "deferral_ledger", DeferralLedger)
    new_entries = build_target_deferrals(
        target_ids,
        reason=f"{stage}_structural_failure",
        source_refs=source_refs,
        review_id=review_id,
        decided_by=str(decisions.get("decided_by") or ""),
        rationale=str(decisions.get("feedback") or ""),
    )
    ledger = append_ledger(existing_ledger, new_entries)

    deferred_set = set(target_ids)
    revised_plan = defer_plan_tasks(plan, target_ids, review_id=review_id)
    artifact_refs = {
        "deferral_ledger": persist_stage_artifact(
            state, "human_review", "DeferralLedger", ledger
        ),
    }

    selection = load_artifact(state, "site_selection", SiteSelectionDecision)
    if selection is not None:
        revised_selection = revise_site_selection_deferral(selection, target_ids)
        artifact_refs["site_selection"] = persist_stage_artifact(
            state, "human_review", "SiteSelectionDecision", revised_selection
        )
    artifact_refs["execution_plan"] = persist_stage_artifact(
        state, "human_review", "ExecutionPlan", revised_plan
    )

    remaining = sorted(gate_ids - deferred_set)
    structurally_blocked = bool(remaining or non_target_blocker_count)
    revised_gate = dict(gate) if isinstance(gate, dict) else _dump(gate)
    revised_gate.update({
        "stage": stage,
        "passed": False,
        "feedback_route": "END_DIAGNOSTIC" if structurally_blocked else "RETRY_EXECUTE",
        "route_reason": (
            "remaining_non_deferred_structural_blockers"
            if structurally_blocked else "human_target_deferral_plan_revision"
        ),
        "pending_requests": [],
    })
    gate_patch = _gate_mutation_patch(
        state,
        stage,
        revised_gate,
        artifact_refs=artifact_refs,
    )
    patch: Dict[str, Any] = {
        **gate_patch,
        "human_deferred_targets": target_ids,
        "deferral_summary": {
            "count": len(ledger.entries),
            "target_ids": [entry.target_id for entry in ledger.entries],
            "actions": [entry.decision.action for entry in ledger.entries],
        },
        "structural_deferral_revision": not structurally_blocked,
        "remaining_target_ids": remaining,
    }
    if structurally_blocked:
        patch.update({
            "delivery_status": "diagnostic_only",
            "diagnostic_terminal": {
                "stage": stage,
                "issue_fingerprint": str(revised_gate.get("issue_fingerprint") or ""),
                "reason": "remaining_non_deferred_structural_blockers",
                "target_ids": remaining,
                "non_target_blocker_count": non_target_blocker_count,
            },
        })
    return patch


async def _record_target_deferrals(
    state: Dict[str, Any],
    decisions: Dict[str, Any],
    target_ids: list[str],
) -> Dict[str, Any]:
    """Persist an immutable ledger only for explicitly unresolved targets."""
    from app.domain.delivery.deferral_ledger import append_ledger, build_target_deferrals
    from app.infrastructure.artifacts.runtime import load_artifact
    from app.contracts.artifacts.deferral_contracts import DeferralLedger
    from app.contracts.spatial.grounding_contracts import GroundingResult

    grounding = load_artifact(state, "grounding_result", GroundingResult)
    if grounding is None:
        return {
            "fatal_error": {
                "stage": "ground",
                "code": "HUMAN_DEFER_GROUNDING_ARTIFACT_MISSING",
                "message": "Cannot defer targets without the typed GroundingResult.",
            }
        }
    unresolved_ids = {
        str(issue.related_artifact_id)
        for issue in grounding.unresolved
        if issue.related_artifact_id
    }
    unknown_ids = [target_id for target_id in target_ids if target_id not in unresolved_ids]
    if unknown_ids:
        return {
            "fatal_error": {
                "stage": "ground",
                "code": "HUMAN_DEFER_TARGET_NOT_UNRESOLVED",
                "message": "Only currently unresolved target IDs may be deferred: " + ", ".join(unknown_ids),
            }
        }
    spec_ids_by_target = {
        str(evidence.target_id): str(evidence.spec_id)
        for evidence in grounding.spatial_query_evidence
        if evidence.target_id and evidence.spec_id
    }
    missing_spec_ids = [
        target_id for target_id in target_ids if target_id not in spec_ids_by_target
    ]
    if missing_spec_ids:
        return {
            "fatal_error": {
                "stage": "ground",
                "code": "HUMAN_DEFER_SPEC_LINK_MISSING",
                "message": "Cannot defer targets without linked GROUND spec IDs: " + ", ".join(missing_spec_ids),
            }
        }
    grounding_ref = (state.get("artifact_refs") or {}).get("grounding_result") or {}
    grounding_id = str(grounding_ref.get("artifact_id") or "grounding_result")
    new_entries = build_target_deferrals(
        target_ids,
        reason="spatial_reference_unresolved",
        source_refs=lambda target_id: (
            f"artifact:grounding_result:{grounding_id}",
            f"spec:{spec_ids_by_target[target_id]}",
        ),
        review_id=str(state.get("human_review_event_id") or "human-review"),
        decided_by=str(decisions.get("decided_by") or ""),
        rationale=str(decisions.get("feedback") or ""),
    )
    ledger = append_ledger(None, new_entries)
    ref = persist_stage_artifact(
        state, "human_review", "DeferralLedger", ledger
    )
    remaining = sorted(unresolved_ids - set(target_ids))
    ground_gate_patch = {
        "stage": "ground",
        "passed": False,
        "feedback_route": "HUMAN",
        "pending_requests": [{
            "request_id": "pr-ground-deferred-remaining",
            "stage": "ground",
            "request_type": "spatial_reference_unresolved",
            "context": {"remaining_target_ids": remaining},
        }] if remaining else [],
        "deferred_target_ids": sorted(set(target_ids)),
        "route_reason": (
            "human_deferred_remaining_unresolved"
            if remaining else "human_deferred_all_unresolved"
        ),
    }
    if not remaining:
        ground_gate_patch.update({
            "passed": True,
            "feedback_route": "PASS",
        })
    gate_patch = _gate_mutation_patch(
        state,
        "ground",
        ground_gate_patch,
        artifact_refs={"deferral_ledger": ref},
    )
    return {
        **gate_patch,
        "human_deferred_targets": target_ids,
        "deferral_summary": {
            "count": len(ledger.entries),
            "target_ids": [entry.target_id for entry in ledger.entries],
            "actions": [entry.decision.action for entry in ledger.entries],
        },
        "remaining_target_ids": remaining,
    }


async def _record_select_target_deferrals(
    state: Dict[str, Any],
    decisions: Dict[str, Any],
    target_ids: list[str],
) -> Dict[str, Any]:
    """Record explicit SELECT-level deferrals in the immutable ledger."""
    from app.domain.delivery.deferral_ledger import append_ledger, build_target_deferrals
    from app.infrastructure.artifacts.runtime import load_artifact
    from app.contracts.artifacts.deferral_contracts import DeferralLedger

    try:
        gate = _root_gate_payload(state, "select")
    except Exception:
        return {
            "fatal_error": {
                "stage": "select",
                "code": "ROOT_GATE_ARTIFACT_UNAVAILABLE",
                "message": "Cannot apply SELECT deferral without the select_gate artifact.",
            }
        }
    pending = gate.get("pending_requests", [])
    allowed: set[str] = set()
    for request in pending:
        context = request.get("context", {}) if isinstance(request, dict) else {}
        allowed.update(str(item) for item in (context.get("target_ids") or []) if str(item))
    # When the select gate carries no pending requests (e.g. the pause was
    # routed from a ground-level unresolved reference), fall back to the
    # ground deferral path which validates against GroundingResult.unresolved.
    if not allowed:
        return await _record_target_deferrals(state, decisions, target_ids)
    unknown = sorted(set(target_ids) - allowed)
    if unknown:
        return {
            "fatal_error": {
                "stage": "select",
                "code": "HUMAN_DEFER_TARGET_NOT_SELECT_BLOCKING",
                "message": "Only currently blocking SELECT target IDs may be deferred: " + ", ".join(unknown),
            }
        }

    refs = state.get("artifact_refs") or {}
    existing = load_artifact(state, "deferral_ledger", DeferralLedger)
    new_entries = build_target_deferrals(
        target_ids,
        reason="selection_no_candidate",
        source_refs=lambda target_id: (
            f"artifact:site_selection:{(refs.get('site_selection') or {}).get('descriptor_digest', 'site_selection')}",
            f"artifact:grounding_result:{(refs.get('grounding_result') or {}).get('descriptor_digest', 'grounding_result')}",
        ),
        review_id=str(state.get("human_review_event_id") or "human-review"),
        decided_by=str(decisions.get("decided_by") or ""),
        rationale=str(decisions.get("feedback") or ""),
    )
    ledger = append_ledger(existing, new_entries)
    ref = persist_stage_artifact(state, "human_review", "DeferralLedger", ledger)
    remaining = sorted(allowed - set(target_ids))
    return {
        "artifact_refs": {"deferral_ledger": ref},
        "human_deferred_targets": target_ids,
        "remaining_target_ids": remaining,
        "deferral_summary": {
            "count": len(ledger.entries),
            "target_ids": [entry.target_id for entry in ledger.entries],
            "actions": [entry.decision.action for entry in ledger.entries],
        },
    }


async def _apply_deferred_select_review(
    state: Dict[str, Any], deferred: list[str]
) -> Dict[str, Any]:
    """Create a traceable SELECT revision for explicit human deferrals."""
    from app.domain.allocation.select_service import revise_site_selection_deferral
    from app.infrastructure.artifacts.runtime import load_artifact
    from app.contracts.workflow.execution_plan_contracts import ExecutionPlan
    from app.contracts.workflow.parse_result_contracts import IntentCompilationResult
    from app.contracts.domain.selection_contracts import SiteSelectionDecision

    decision = load_artifact(state, "site_selection", SiteSelectionDecision)
    intent_result = load_artifact(state, "target_projection", IntentCompilationResult)
    if decision is None or intent_result is None:
        return {
            "fatal_error": {
                "stage": "select",
                "code": "HUMAN_DEFER_SELECTION_ARTIFACT_MISSING",
                "message": "Cannot create a deferred SELECT revision without the original typed artifacts.",
            }
        }

    if not deferred:
        return {
            "human_deferred_targets": [],
            "human_deferred_select_revision": False,
        }

    revised = revise_site_selection_deferral(
        decision, deferred, review_status="human_approved"
    )
    select_ref = persist_stage_artifact(
        state,
        "human_review",
        "SiteSelectionDecision",
        revised,
    )

    # EXECUTE consumes the canonical site_selection ref; the plan has no
    # embedded selection snapshot to drift from that ref.
    plan = load_artifact(state, "execution_plan", ExecutionPlan)
    refs = {"site_selection": select_ref}
    if plan is not None:
        plan_revision = plan.model_copy(deep=True)
        refs["execution_plan"] = persist_stage_artifact(
            state, "human_review", "ExecutionPlan", plan_revision
        )

    gate = _pass_gate("select").model_dump(mode="json")
    gate.update({
        "feedback_route": "PASS",
        "diagnostic_code": "HUMAN_DEFERRED_UNRESOLVED_SPATIAL",
        "pending_requests": [],
    })
    return {
        **_gate_mutation_patch(state, "select", gate, artifact_refs=refs),
        "human_deferred_targets": deferred,
        "human_deferred_select_revision": True,
    }


__all__ = [
    "WorkflowState", "PlanningPhase",
    "create_unified_planning_graph",
]
