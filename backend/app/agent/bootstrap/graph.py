"""Main planning graph factory. Migrated from agent/graph.py per docs/architecture/agent-graph.md §5."""

import hashlib
from typing import Dict, Any, List, Literal, Optional
from langgraph.graph import StateGraph, END, START
from langchain_core.messages import HumanMessage

from app.agent.plan_state.state import AgentState, create_initial_state
from app.agent.bootstrap.phase_machine import PlanningPhase, get_layer_dimensions
from app.agent.l1_observe import analyze_dimension, DIMENSION_NAMES
from app.agent.plan_state import layer_completion_check
from app.agent.bootstrap.layer_aggregate_node import layer_aggregate_node
from app.agent.bootstrap.layer_router import (
    l1_worker_node,
    l2_worker_node,
    l3_worker_node,
    advance_phase_node,
)
from app.agent.bootstrap import post_l3_main_nodes
from app.agent.bootstrap.post_l3_main_nodes import _STAGE_FORWARD_TARGET, _pass_gate, _dump
from app.agent.bootstrap.context_bootstrap import bootstrap_context_node
from app.core.events import SSEEventType

from app.utils.logger import get_logger
logger = get_logger(__name__)


async def execute_tools_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Load tool/model registrations only when a tool stage is executed."""
    from app.agent.tools import execute_tools_node as _execute_tools_node
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


# ── Wave M: post-L3 gate routers (pure functions over AgentState) ──────


def _retry_or_human(state: Dict[str, Any], stage: str, retry_target: str) -> str:
    """Pick retry_target vs human escalation based on the retry cap."""
    counts = dict(state.get("retry_counts") or {})
    current = counts.get(stage, 0)
    configured_limit = state.get("max_retries")
    max_retries = 3 if configured_limit is None else max(0, int(configured_limit))
    if current >= max_retries:
        logger.warning("[main] %s retry exceeded %d rounds -> human", stage, max_retries)
        gate_key = f"{stage}_gate"
        gate = state.get(gate_key)
        if isinstance(gate, dict):
            gate = dict(gate)
            gate["feedback_route"] = "HUMAN"
            gate.setdefault("diagnostic_code", f"{stage.upper()}_RETRY_EXHAUSTED")
            pending = list(gate.get("pending_requests") or [])
            if not pending:
                pending = [{
                    "request_id": f"{stage}-retry-exhausted",
                    "stage": stage,
                    "request_type": "business_retry_exhausted",
                    "context": {"retry_count": current, "retry_limit": max_retries},
                }]
            gate["pending_requests"] = pending
            # Routing callbacks receive the checkpoint state object; retaining
            # this mutation lets prepare_human_review select the exhausted
            # downstream gate instead of a stale upstream GROUND gate.
            state[gate_key] = gate
        return "human_review"
    logger.info("[main] %s retry %d/%d -> %s", stage, current + 1, max_retries, retry_target)
    return retry_target


def route_after_parse(state: Dict[str, Any]) -> str:
    route = post_l3_main_nodes._gate_route(state.get("parse_gate"))
    if route == "PASS":
        return "ground"
    if route in ("REPAIR", "REVISE"):
        return _retry_or_human(state, "parse", "parse")
    return "human_review"


def route_after_ground(state: Dict[str, Any]) -> str:
    route = post_l3_main_nodes._gate_route(state.get("ground_gate"))
    if route == "PASS":
        return "select"
    if route == "EXPLORE":
        return _retry_or_human(state, "ground", "ground")
    return "human_review"


def route_after_select(state: Dict[str, Any]) -> str:
    route = post_l3_main_nodes._gate_route(state.get("select_gate"))
    if route == "PASS":
        return "execute"
    if route == "RETRY_GROUND":
        return _retry_or_human(state, "select", "ground")
    return "human_review"


def route_after_validate(state: Dict[str, Any]) -> str:
    route = post_l3_main_nodes._gate_route(state.get("validate_gate"))
    if route == "PASS":
        return "reconcile"
    if route in ("RETRY_EXECUTE", "RETRY_SELECT", "RETRY_GROUND", "RETRY_PARSE"):
        stage_map = {
            "RETRY_EXECUTE": "validate",
            "RETRY_SELECT": "validate",
            "RETRY_GROUND": "validate",
            "RETRY_PARSE": "validate",
        }
        return _retry_or_human(state, stage_map.get(route, "validate"), route[6:].lower())
    if route == "RETRY_L3":
        return "human_review"
    return "human_review"


def route_after_reconcile(state: Dict[str, Any]) -> str:
    route = post_l3_main_nodes._gate_route(state.get("reconcile_gate"))
    if route == "PASS":
        return "deliver"
    if route == "RETRY_EXECUTE":
        return _retry_or_human(state, "reconcile", "execute")
    if route == "RETRY_L3":
        return "human_review"
    return "human_review"


def route_after_deliver(state: Dict[str, Any]) -> str:
    route = post_l3_main_nodes._gate_route(state.get("deliver_gate"))
    if route == "PASS":
        return END
    if route == "RETRY_VALIDATE":
        return _retry_or_human(state, "deliver", "validate")
    return "human_review"


def _remaining_unresolved_target_ids(state: Dict[str, Any]) -> list[str]:
    """Return unresolved target IDs still represented by the blocking gate."""
    remaining = state.get("remaining_target_ids") or []
    target_ids = [str(target_id) for target_id in remaining if str(target_id)] if isinstance(remaining, list) else []
    gate = state.get("ground_gate") or {}
    pending = gate.get("pending_requests") if isinstance(gate, dict) else getattr(gate, "pending_requests", [])
    for request in pending or []:
        context = request.get("context") if isinstance(request, dict) else getattr(request, "context", {})
        if not isinstance(context, dict):
            continue
        ids = context.get("remaining_target_ids") or []
        target_ids.extend(str(target_id) for target_id in ids if str(target_id))
    return list(dict.fromkeys(target_ids))


def route_after_human_review(state: Dict[str, Any]) -> str:
    """Route post-HITL resume: approve forwards, reject goes to conversation."""
    if state.get("fatal_error"):
        return END
    decisions = state.get("human_review_decisions") or {}
    paused_stage = state.get("paused_stage")
    action = decisions.get("action") if isinstance(decisions, dict) else None
    if action in ("accept", "approve"):
        if _remaining_unresolved_target_ids(state):
            return "human_review"
        if (
            paused_stage == "select"
            and isinstance(decisions, dict)
            and decisions.get("defer_unresolved_spatial_references") is True
            and state.get("human_deferred_select_revision")
        ):
            return "execute"
        if (
            paused_stage == "ground"
            and isinstance(decisions, dict)
            and decisions.get("defer_unresolved_spatial_references") is True
        ):
            if post_l3_main_nodes._gate_route(state.get("ground_gate")) == "PASS":
                return "select"
            return "human_review"
        if paused_stage and paused_stage in _STAGE_FORWARD_TARGET:
            target = _STAGE_FORWARD_TARGET[paused_stage]
            return END if target == "__end__" else target
        return END
    if action == "retry":
        retry_stage = paused_stage if paused_stage else "parse"
        configured_limit = state.get("max_retries")
        max_retries = 3 if configured_limit is None else max(0, int(configured_limit))
        current = int((state.get("retry_counts") or {}).get(retry_stage, 0))
        if current >= max_retries:
            return END
        return retry_stage
    if action == "reject":
        return "conversation"
    return END


def create_unified_planning_graph(checkpointer=None) -> StateGraph:
    """创建统一规划图 - 纯函数，每次返回新图。

    缓存责任由调用方承担（`PlanningRuntimeService._graph` 单例）。
    Wave M2: explore_node removed (EXPLORE is now gate-driven horizontal service).
    Wave M: post-L3 链拆为主图独立节点（parse/ground/select/execute/validate/
    reconcile/deliver/human_review），L3 gate PASS 后经 advance_phase 自动进入
    parse，不再依赖 gis_agent 黑盒节点。
    """
    from app.agent.conversation_router import after_conversation, after_analysis, conversation_node

    logger.info("[图构建] 构建规划图")
    builder = StateGraph(AgentState)

    builder.add_node("conversation", conversation_node)
    if _HAS_RETRY_POLICY:
        builder.add_node("execute_tools", execute_tools_node, retry_policy=_TRANSIENT_RETRY_POLICY)
    else:
        builder.add_node("execute_tools", execute_tools_node)
    builder.add_node("l1_worker", audited_l1_worker)
    builder.add_node("l2_worker", audited_l2_worker)
    builder.add_node("l3_worker", audited_l3_worker)
    builder.add_node("advance_phase", advance_phase_node)
    builder.add_node("layer_completion_check", layer_completion_check)
    builder.add_node("layer_aggregate", layer_aggregate_node)
    builder.add_node("bootstrap_context", bootstrap_context_node)
    # ── Wave M: post-L3 主图独立节点 ──
    builder.add_node("parse", post_l3_main_nodes.parse_node)
    builder.add_node("ground", post_l3_main_nodes.ground_node)
    builder.add_node("select", post_l3_main_nodes.select_node)
    builder.add_node("execute", post_l3_main_nodes.execute_node)
    builder.add_node("validate", post_l3_main_nodes.validate_node)
    builder.add_node("reconcile", post_l3_main_nodes.reconcile_node)
    builder.add_node("deliver", post_l3_main_nodes.deliver_node)
    builder.add_node("human_review_prepare", prepare_human_review)
    builder.add_node("human_review_publish", publish_human_review_pause)
    builder.add_node("human_review_wait", await_human_review)
    builder.add_node("human_review_apply", apply_human_review_decision)

    builder.add_edge(START, "conversation")
    builder.add_conditional_edges("conversation", after_conversation,
        {"execute_tools": "execute_tools", "parse": "bootstrap_context",
         "l1_worker": "l1_worker", "l2_worker": "l2_worker", "l3_worker": "l3_worker",
         END: END})
    builder.add_edge("execute_tools", "conversation")
    builder.add_edge("bootstrap_context", "parse")
    builder.add_edge("l1_worker", "layer_completion_check")
    builder.add_edge("l2_worker", "layer_completion_check")
    builder.add_edge("l3_worker", "layer_completion_check")
    builder.add_edge("layer_completion_check", "layer_aggregate")
    builder.add_conditional_edges("layer_aggregate", after_analysis,
        {"advance_phase": "advance_phase", "conversation": "conversation",
         "l1_worker": "l1_worker", "l2_worker": "l2_worker", "l3_worker": "l3_worker",
         "human_review": "human_review_prepare",
         END: END})
    # ── Wave M: post-L3 主图链条件边 ──
    builder.add_conditional_edges("parse", route_after_parse,
        {"ground": "ground", "parse": "parse", "human_review": "human_review_prepare"})
    builder.add_conditional_edges("ground", route_after_ground,
        {"select": "select", "ground": "ground", "human_review": "human_review_prepare"})
    builder.add_conditional_edges("select", route_after_select,
        {"execute": "execute", "ground": "ground", "human_review": "human_review_prepare"})
    builder.add_edge("execute", "validate")
    builder.add_conditional_edges("validate", route_after_validate,
        {"reconcile": "reconcile", "execute": "execute", "select": "select",
         "ground": "ground", "parse": "parse", "human_review": "human_review_prepare"})
    builder.add_conditional_edges("reconcile", route_after_reconcile,
        {"deliver": "deliver", "execute": "execute", "human_review": "human_review_prepare"})
    builder.add_conditional_edges("deliver", route_after_deliver,
        {END: END, "validate": "validate", "human_review": "human_review_prepare"})
    builder.add_edge("human_review_prepare", "human_review_publish")
    builder.add_edge("human_review_publish", "human_review_wait")
    builder.add_edge("human_review_wait", "human_review_apply")
    builder.add_conditional_edges("human_review_apply", route_after_human_review,
        {"l1_worker": "l1_worker", "l2_worker": "l2_worker", "l3_worker": "l3_worker",
         "parse": "parse", "ground": "ground", "select": "select",
         "execute": "execute", "validate": "validate", "reconcile": "reconcile",
         "deliver": "deliver", "conversation": "conversation",
         END: END})

    return builder.compile(checkpointer=checkpointer)


async def prepare_human_review(state: Dict[str, Any]) -> Dict[str, Any]:
    """Pure HITL preparation; no external side effects."""
    paused_stage, items = post_l3_main_nodes.collect_human_review_items(state)
    # Routing functions are intentionally pure and cannot persist a gate
    # mutation while selecting ``human_review``.  When a layer contract or
    # retry budget routes directly from ``after_analysis`` to HUMAN, promote
    # that decision here before building the interrupt payload.  Otherwise
    # the graph would reach the HUMAN branch with an L3 gate still labelled
    # ``L3`` and collect no review items, silently ending instead of pausing.
    gate_patch = {}
    # A retry budget is a business gate, not an implicit retry forever loop.
    # When VALIDATE exhausted RETRY_EXECUTE, preserve the exact VALIDATE
    # checkpoint as the HUMAN pause so approval can continue to RECONCILE.
    counts = state.get("retry_counts") or {}
    max_retries = 3 if state.get("max_retries") is None else max(0, int(state.get("max_retries")))
    if int(counts.get("validate", 0)) >= max_retries:
        gate = state.get("validate_gate")
        if isinstance(gate, dict) and gate.get("pending_requests"):
            human_gate = dict(gate)
            human_gate["feedback_route"] = "HUMAN"
            human_gate.setdefault("diagnostic_code", "VALIDATE_RETRY_EXHAUSTED")
            gate_patch["validate_gate"] = human_gate
            paused_stage = "validate"
            items = list(human_gate.get("pending_requests") or [])
    if not items or paused_stage == "post_l3":
        for gate_attr in (
            # Scan downstream stages first; stale upstream EXPLORE gates are
            # retained for audit but must not steal a later HUMAN pause.
            "deliver_gate", "reconcile_gate", "validate_gate", "select_gate",
            "ground_gate", "parse_gate",
            "l3_gate_decision", "l2_gate_decision", "l1_gate_decision",
        ):
            gate = state.get(gate_attr)
            if not isinstance(gate, dict):
                continue
            pending = list(gate.get("pending_requests") or [])
            route = gate.get("feedback_route")
            if pending and route not in {None, "PASS", "HUMAN"}:
                human_gate = dict(gate)
                human_gate["feedback_route"] = "HUMAN"
                human_gate.setdefault("diagnostic_code", "BUSINESS_GATE_REVIEW_REQUIRED")
                gate_patch[gate_attr] = human_gate
                paused_stage = gate_attr.removesuffix("_gate_decision").removesuffix("_gate")
                items = pending
                break
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
    event_id = hashlib.sha256(
        repr((state.get("session_id"), paused_stage, items, state.get("retry_counts"))).encode()
    ).hexdigest()[:24]
    return {
        **gate_patch,
        "human_review_items": items,
        "paused_stage": paused_stage,
        "human_review_event_id": event_id,
        "human_review_pause_published": False,
        "human_review_resume_consumed": False,
    }


async def publish_human_review_pause(state: Dict[str, Any]) -> Dict[str, Any]:
    """Idempotently publish the pause notification."""
    items = state.get("human_review_items") or []
    if not items or state.get("human_review_pause_published"):
        return {"human_review_pause_published": True}
    session_id = state.get("session_id")
    if session_id:
        try:
            from app.services.sse import sse_manager
            await sse_manager.publish(session_id, {
                "type": SSEEventType.HUMAN_REVIEW_PAUSED,
                "event_id": state.get("human_review_event_id"),
                "paused_stage": state.get("paused_stage"),
                "reason": "post_l3_human_review",
                "item_count": len(items),
            })
        except Exception as exc:
            logger.warning("[main:human_review] SSE publish failed: %s", exc)
            return {"human_review_pause_published": False}
    return {"human_review_pause_published": True}


async def await_human_review(state: Dict[str, Any]) -> Dict[str, Any]:
    """The only node containing interrupt(); it has no pre-interrupt effects."""
    from langgraph.types import interrupt
    items = state.get("human_review_items") or []
    paused_stage = state.get("paused_stage")
    if not items:
        return {"human_review_decisions": {}}
    decisions = interrupt(
        {
            "human_review_items": items,
            "paused_stage": paused_stage,
            "error_feedback": dict(state.get("error_feedback") or {}),
            "reason": "post_l3_human_review",
        }
    )
    return {"human_review_decisions": decisions or {}}


async def apply_human_review_decision(state: Dict[str, Any]) -> Dict[str, Any]:
    """Apply an already-resumed decision, creating a new gate revision."""
    items = state.get("human_review_items") or []
    paused_stage = state.get("paused_stage")
    decisions = state.get("human_review_decisions") or {}
    if not items:
        return {"human_review_items": [], "paused_stage": None}
    result = {
        "human_review_items": items,
        "paused_stage": paused_stage,
        "human_review_decisions": decisions,
        "human_review_resume_consumed": True,
    }
    action = decisions.get("action") if isinstance(decisions, dict) else None
    deferral_patch = {}
    deferred_target_ids: list[str] = []
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
        deferral_patch = await _record_target_deferrals(
            state, decisions, deferred_target_ids
        )
        if deferral_patch.get("fatal_error"):
            return {**result, **deferral_patch}
        remaining_target_ids = deferral_patch.get("remaining_target_ids") or []
        if remaining_target_ids:
            ground_gate = dict(state.get("ground_gate") or {})
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
                "ground_gate": ground_gate,
                "human_deferred_targets": deferred_target_ids,
                "human_deferred_select_revision": False,
                "remaining_target_ids": remaining_target_ids,
            })
            if paused_stage == "select":
                select_gate = dict(state.get("select_gate") or {})
                select_gate.update({
                    "stage": "select",
                    "passed": False,
                    "feedback_route": "HUMAN",
                    "diagnostic_code": "HUMAN_DEFER_SPATIAL_REMAINING",
                    "pending_requests": list(ground_gate["pending_requests"]),
                })
                result["select_gate"] = select_gate
            if deferral_patch.get("artifact_refs"):
                result["artifact_refs"] = deferral_patch["artifact_refs"]
            return result
    if action == "retry" and paused_stage:
        configured_limit = state.get("max_retries")
        max_retries = 3 if configured_limit is None else max(0, int(configured_limit))
        current = int((state.get("retry_counts") or {}).get(paused_stage, 0))
        if current >= max_retries:
            result["fatal_error"] = {
                "stage": paused_stage,
                "code": "BUSINESS_RETRY_EXHAUSTED",
                "message": f"{paused_stage} business retry limit exhausted ({current}/{max_retries})",
            }
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
        if paused_stage in {"l1", "l2", "l3"}:
            result[f"{paused_stage}_gate_decision"] = _dump(_pass_gate(paused_stage))
        else:
            result[f"{paused_stage}_gate"] = _dump(_pass_gate(paused_stage))
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
                ground_gate = dict(state.get("ground_gate") or {})
                ground_gate.update({
                    "stage": "ground",
                    "passed": True,
                    "feedback_route": "PASS",
                    "diagnostic_code": "HUMAN_DEFERRED_UNRESOLVED_SPATIAL",
                    "pending_requests": [],
                })
                result.update({
                    "ground_gate": ground_gate,
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


async def _record_target_deferrals(
    state: Dict[str, Any],
    decisions: Dict[str, Any],
    target_ids: list[str],
) -> Dict[str, Any]:
    """Persist an immutable ledger only for explicitly unresolved targets."""
    from app.agent.bootstrap.artifact_runtime import load_artifact, store_artifact
    from app.modules.schema.contracts.deferral_contracts import (
        DeferralLedger,
        HumanDeferralDecision,
        TargetDeferral,
    )
    from app.modules.schema.contracts.grounding_contracts import GroundingResult

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
    decision = HumanDeferralDecision(
        decision_id=str(state.get("human_review_event_id") or "human-review"),
        decided_by=str(decisions.get("decided_by") or ""),
        rationale=str(decisions.get("feedback") or ""),
    )
    ledger = DeferralLedger(
        entries=tuple(
            TargetDeferral(
                target_id=target_id,
                reason="spatial_reference_unresolved",
                source_refs=(
                    f"artifact:grounding_result:{grounding_id}",
                    f"spec:{spec_ids_by_target[target_id]}",
                ),
                decision=decision,
            )
            for target_id in target_ids
        )
    )
    ref = store_artifact(
        state, "deferral_ledger", "human_review", "DeferralLedger", ledger
    )
    return {
        "artifact_refs": {"deferral_ledger": ref},
        "human_deferred_targets": target_ids,
        "remaining_target_ids": sorted(unresolved_ids - set(target_ids)),
    }


async def _apply_deferred_select_review(
    state: Dict[str, Any], deferred: list[str]
) -> Dict[str, Any]:
    """Create a traceable SELECT revision for explicit human deferrals."""
    from app.agent.bootstrap.artifact_runtime import load_artifact, store_artifact
    from app.modules.schema.contracts.execution_plan_contracts import ExecutionPlan
    from app.modules.schema.contracts.parse_result_contracts import IntentCompilationResult
    from app.modules.schema.contracts.selection_contracts import SiteSelectionDecision

    decision = load_artifact(state, "site_selection", SiteSelectionDecision)
    intent_result = load_artifact(state, "intent_compilation", IntentCompilationResult)
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

    revised = decision.model_copy(deep=True)
    factors = dict(revised.decision_factors or {})
    factors.update({
        "unplaced_count": 0,
        "deferred_count": len(deferred),
        "deferred_targets": deferred,
        "deferred_by": "human_review",
    })
    revised.decision_factors = factors
    revised.review_status = "human_approved"
    select_ref = store_artifact(
        state,
        "site_selection",
        "human_review",
        "SiteSelectionDecision",
        revised,
    )

    # Keep the execution plan's embedded selection snapshot aligned with the
    # new ref.  EXECUTE still consumes the canonical site_selection ref, but
    # the plan must remain a truthful audit artifact too.
    plan = load_artifact(state, "execution_plan", ExecutionPlan)
    refs = {"site_selection": select_ref}
    if plan is not None:
        plan_revision = plan.model_copy(deep=True)
        plan_revision.site_selection = revised
        refs["execution_plan"] = store_artifact(
            state, "execution_plan", "human_review", "ExecutionPlan", plan_revision
        )

    gate = _pass_gate("select").model_dump(mode="json")
    gate.update({
        "feedback_route": "PASS",
        "diagnostic_code": "HUMAN_DEFERRED_UNRESOLVED_SPATIAL",
        "pending_requests": [],
    })
    return {
        "artifact_refs": refs,
        "select_gate": gate,
        "human_deferred_targets": deferred,
        "human_deferred_select_revision": True,
    }


__all__ = [
    "AgentState", "PlanningPhase",
    "create_unified_planning_graph",
]
