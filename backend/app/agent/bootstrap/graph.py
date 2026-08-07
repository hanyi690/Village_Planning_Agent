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


# ── Wave M: post-L3 gate routers (pure functions over AgentState) ──────


def _retry_or_human(state: Dict[str, Any], stage: str, retry_target: str) -> str:
    """Pick retry_target vs human escalation based on the retry cap."""
    counts = dict(state.get("retry_counts") or {})
    current = counts.get(stage, 0)
    max_retries = state.get("max_retries") or 3
    if current >= max_retries:
        logger.warning("[main] %s retry exceeded %d rounds -> human", stage, max_retries)
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


def route_after_human_review(state: Dict[str, Any]) -> str:
    """Route post-HITL resume: approve forwards, reject goes to conversation."""
    decisions = state.get("human_review_decisions") or {}
    paused_stage = state.get("paused_stage")
    action = decisions.get("action") if isinstance(decisions, dict) else None
    if action in ("accept", "approve"):
        if paused_stage and paused_stage in _STAGE_FORWARD_TARGET:
            target = _STAGE_FORWARD_TARGET[paused_stage]
            return END if target == "__end__" else target
        return END
    if action == "retry":
        return paused_stage if paused_stage else "parse"
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
    builder.add_node("l1_worker", l1_worker_node)
    builder.add_node("l2_worker", l2_worker_node)
    builder.add_node("l3_worker", l3_worker_node)
    builder.add_node("advance_phase", advance_phase_node)
    builder.add_node("layer_completion_check", layer_completion_check)
    builder.add_node("layer_aggregate", layer_aggregate_node)
    builder.add_node("bootstrap_context", bootstrap_context_node)
    # ── Wave M: post-L3 主图独立节点 ──
    builder.add_node("parse", post_l3_main_nodes.parse_node)
    builder.add_node("ground", post_l3_main_nodes.ground_node)
    builder.add_node("select", post_l3_main_nodes.select_node)
    from app.agent.execute.execute_agent import build_execute_agent_graph
    compiled_execute = build_execute_agent_graph()
    builder.add_node("pre_execute", post_l3_main_nodes.pre_execute_node)
    builder.add_node("execute", compiled_execute)
    builder.add_node("post_execute", post_l3_main_nodes.post_execute_node)
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
        {"execute": "pre_execute", "ground": "ground", "human_review": "human_review_prepare"})
    builder.add_edge("pre_execute", "execute")
    builder.add_edge("execute", "post_execute")
    builder.add_edge("post_execute", "validate")
    builder.add_conditional_edges("validate", route_after_validate,
        {"reconcile": "reconcile", "execute": "pre_execute", "select": "select",
         "ground": "ground", "parse": "parse", "human_review": "human_review_prepare"})
    builder.add_conditional_edges("reconcile", route_after_reconcile,
        {"deliver": "deliver", "execute": "pre_execute", "human_review": "human_review_prepare"})
    builder.add_conditional_edges("deliver", route_after_deliver,
        {END: END, "validate": "validate", "human_review": "human_review_prepare"})
    builder.add_edge("human_review_prepare", "human_review_publish")
    builder.add_edge("human_review_publish", "human_review_wait")
    builder.add_edge("human_review_wait", "human_review_apply")
    builder.add_conditional_edges("human_review_apply", route_after_human_review,
        {"parse": "parse", "ground": "ground", "select": "select",
         "execute": "pre_execute", "validate": "validate", "reconcile": "reconcile",
         "deliver": "deliver", "conversation": "conversation",
         END: END})

    return builder.compile(checkpointer=checkpointer)


async def prepare_human_review(state: Dict[str, Any]) -> Dict[str, Any]:
    """Pure HITL preparation; no external side effects."""
    paused_stage, items = post_l3_main_nodes.collect_human_review_items(state)
    event_id = hashlib.sha256(
        repr((state.get("session_id"), paused_stage, items, state.get("retry_counts"))).encode()
    ).hexdigest()[:24]
    return {
        "human_review_items": items,
        "paused_stage": paused_stage,
        "human_review_event_id": event_id,
        "human_review_pause_published": False,
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
    }
    action = decisions.get("action") if isinstance(decisions, dict) else None
    if action in ("accept", "approve") and paused_stage:
        result[f"{paused_stage}_gate"] = _dump(_pass_gate(paused_stage))
    elif action == "reject":
        feedback = decisions.get("feedback") if isinstance(decisions, dict) else None
        result["messages"] = [HumanMessage(content=feedback or "方案已拒绝，请调整后重新规划")]
    return result


__all__ = [
    "AgentState", "PlanningPhase",
    "create_unified_planning_graph",
]
