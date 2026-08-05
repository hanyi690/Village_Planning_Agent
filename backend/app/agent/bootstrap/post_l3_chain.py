"""Post-L3 chain graph factory - wires the Wave B-L subgraphs in sequence.

Wave M2 topology (with retry loops):
    START -> parse -> ground -> select -> execute -> validate -> reconcile
             -> deliver -> END

Gate routing: PASS continues linearly; retryable routes (REPAIR/REVISE/
EXPLORE/RETRY_*) loop back to the source node; HUMAN routes to the
human_review node which populates human_review_items then terminates.
Retry caps at max_retries (default 3) per stage, after which HUMAN fires.
"""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph

from app.utils.logger import get_logger

from .post_l3_nodes import (
    deliver_node,
    execute_node,
    ground_node,
    human_review_node,
    parse_node,
    reconcile_node,
    select_node,
    validate_node,
)
from .post_l3_state import PostL3ChainState

logger = get_logger(__name__)


def _gate_route(gate: Any) -> str:
    """Extract feedback_route from gate (typed or dict), defaulting to PASS."""
    if gate is None:
        return "PASS"
    route = getattr(gate, "feedback_route", None)
    if route is None and isinstance(gate, dict):
        route = gate.get("feedback_route")
    return route or "PASS"


def _retry_or_human(state: PostL3ChainState, stage: str, retry_target: str) -> str:
    """Check retry count; if under cap, return retry_target; else human_end."""
    counts = dict(state.retry_counts or {})
    current = counts.get(stage, 0)
    max_retries = state.max_retries or 3
    if current >= max_retries:
        logger.warning(
            "[post_l3] %s retry exceeded %d rounds -> HUMAN", stage, max_retries,
        )
        return "human_end"
    counts[stage] = current + 1
    logger.info(
        "[post_l3] %s retry %d/%d -> %s", stage, current + 1, max_retries, retry_target,
    )
    # Note: retry_counts update is returned by the node, not the router.
    # The router only decides the target; the node increments the counter.
    return retry_target


def _route_after_parse(state: PostL3ChainState) -> str:
    route = _gate_route(state.parse_gate)
    if route == "PASS":
        return "ground"
    if route in ("REPAIR", "REVISE"):
        return _retry_or_human(state, "parse", "parse")
    # HUMAN or unknown
    return "human_end"


def _route_after_ground(state: PostL3ChainState) -> str:
    route = _gate_route(state.ground_gate)
    if route == "PASS":
        return "select"
    if route == "EXPLORE":
        return _retry_or_human(state, "ground", "ground")
    return "human_end"


def _route_after_select(state: PostL3ChainState) -> str:
    route = _gate_route(state.select_gate)
    if route == "PASS":
        return "execute"
    if route == "RETRY_GROUND":
        return _retry_or_human(state, "select", "ground")
    return "human_end"


def _route_after_validate(state: PostL3ChainState) -> str:
    route = _gate_route(state.validate_gate)
    if route == "PASS":
        return "reconcile"
    if route == "RETRY_EXECUTE":
        return _retry_or_human(state, "validate", "execute")
    if route == "RETRY_SELECT":
        return _retry_or_human(state, "validate", "select")
    if route == "RETRY_GROUND":
        return _retry_or_human(state, "validate", "ground")
    if route == "RETRY_PARSE":
        return _retry_or_human(state, "validate", "parse")
    if route == "RETRY_L3":
        # Cannot loop back to L3 in the post-L3 chain; terminate
        logger.warning("[post_l3] validate RETRY_L3 cannot loop -> END")
        return "end"
    return "human_end"


def _route_after_reconcile(state: PostL3ChainState) -> str:
    route = _gate_route(state.reconcile_gate)
    if route == "PASS":
        return "deliver"
    if route == "RETRY_EXECUTE":
        return _retry_or_human(state, "reconcile", "execute")
    if route == "RETRY_L3":
        logger.warning("[post_l3] reconcile RETRY_L3 cannot loop -> END")
        return "end"
    return "human_end"


def _route_after_deliver(state: PostL3ChainState) -> str:
    route = _gate_route(state.deliver_gate)
    if route == "PASS":
        return "end"
    if route == "RETRY_VALIDATE":
        return _retry_or_human(state, "deliver", "validate")
    return "human_end"


def build_post_l3_chain():
    """Build and compile the post-L3 subgraph chain with retry loops."""
    graph = StateGraph(PostL3ChainState)

    graph.add_node("parse", parse_node)
    graph.add_node("ground", ground_node)
    graph.add_node("select", select_node)
    graph.add_node("execute", execute_node)
    graph.add_node("validate", validate_node)
    graph.add_node("reconcile", reconcile_node)
    graph.add_node("deliver", deliver_node)
    graph.add_node("human_review", human_review_node)

    graph.add_edge(START, "parse")
    graph.add_conditional_edges(
        "parse", _route_after_parse,
        {"ground": "ground", "parse": "parse", "human_end": "human_review", "end": END},
    )
    graph.add_conditional_edges(
        "ground", _route_after_ground,
        {"select": "select", "ground": "ground", "human_end": "human_review", "end": END},
    )
    graph.add_conditional_edges(
        "select", _route_after_select,
        {"execute": "execute", "ground": "ground", "human_end": "human_review", "end": END},
    )
    graph.add_edge("execute", "validate")
    graph.add_conditional_edges(
        "validate", _route_after_validate,
        {"reconcile": "reconcile", "execute": "execute", "select": "select",
         "ground": "ground", "parse": "parse", "human_end": "human_review", "end": END},
    )
    graph.add_conditional_edges(
        "reconcile", _route_after_reconcile,
        {"deliver": "deliver", "execute": "execute", "human_end": "human_review", "end": END},
    )
    graph.add_conditional_edges(
        "deliver", _route_after_deliver,
        {"end": END, "validate": "validate", "human_end": "human_review"},
    )
    graph.add_edge("human_review", END)

    compiled = graph.compile()
    logger.info(
        "[post_l3] chain compiled (M2 retry): "
        "parse->ground->select->execute->validate->reconcile->deliver + human_review"
    )
    return compiled


__all__ = ["build_post_l3_chain"]
