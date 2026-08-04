"""Post-L3 chain graph factory — wires the Wave B-L subgraphs in sequence.

Wave M1 topology:
    START -> parse -> ground -> select -> execute -> validate -> reconcile
             -> deliver -> END

Each node wraps a subgraph aggregate + gate. Gate routing is simplified for
M1: a PASS gate continues linearly; a non-PASS gate logs the route and the
chain terminates at END (no retry loops yet — those land with M2's full
gate-driven routing). The accumulated upstream_gates list flows through to
DELIVER so pending human items can be collected.
"""

from __future__ import annotations

from typing import Literal

from langgraph.graph import END, START, StateGraph

from app.utils.logger import get_logger

from .post_l3_nodes import (
    deliver_node,
    execute_node,
    ground_node,
    parse_node,
    reconcile_node,
    select_node,
    validate_node,
)
from .post_l3_state import PostL3ChainState

logger = get_logger(__name__)


def _route_after_parse(state: PostL3ChainState) -> Literal["ground", "end"]:
    gate = state.parse_gate
    route = getattr(gate, "feedback_route", None) or "PASS"
    if route != "PASS":
        logger.warning("[post_l3] parse gate routed %s; terminating chain", route)
        return "end"
    return "ground"


def _route_after_ground(state: PostL3ChainState) -> Literal["select", "end"]:
    gate = state.ground_gate
    route = getattr(gate, "feedback_route", None) or "PASS"
    if route != "PASS":
        logger.warning("[post_l3] ground gate routed %s; terminating chain", route)
        return "end"
    return "select"


def _route_after_select(state: PostL3ChainState) -> Literal["execute", "end"]:
    gate = state.select_gate
    route = getattr(gate, "feedback_route", None) or "PASS"
    if route != "PASS":
        logger.warning("[post_l3] select gate routed %s; terminating chain", route)
        return "end"
    return "execute"


def _route_after_validate(state: PostL3ChainState) -> Literal["reconcile", "end"]:
    gate = state.validate_gate
    route = getattr(gate, "feedback_route", None) or "PASS"
    if route != "PASS":
        logger.warning("[post_l3] validate gate routed %s; terminating chain", route)
        return "end"
    return "reconcile"


def _route_after_reconcile(state: PostL3ChainState) -> Literal["deliver", "end"]:
    gate = state.reconcile_gate
    route = getattr(gate, "feedback_route", None) or "PASS"
    if route != "PASS":
        logger.warning("[post_l3] reconcile gate routed %s; terminating chain", route)
        return "end"
    return "deliver"


def _route_after_deliver(state: PostL3ChainState) -> Literal["end"]:
    gate = state.deliver_gate
    route = getattr(gate, "feedback_route", None) or "PASS"
    if route != "PASS":
        logger.warning("[post_l3] deliver gate routed %s; terminating chain", route)
    return "end"


def build_post_l3_chain():
    """Build and compile the post-L3 subgraph chain."""
    graph = StateGraph(PostL3ChainState)

    graph.add_node("parse", parse_node)
    graph.add_node("ground", ground_node)
    graph.add_node("select", select_node)
    graph.add_node("execute", execute_node)
    graph.add_node("validate", validate_node)
    graph.add_node("reconcile", reconcile_node)
    graph.add_node("deliver", deliver_node)

    graph.add_edge(START, "parse")
    graph.add_conditional_edges(
        "parse", _route_after_parse, {"ground": "ground", "end": END}
    )
    graph.add_conditional_edges(
        "ground", _route_after_ground, {"select": "select", "end": END}
    )
    graph.add_conditional_edges(
        "select", _route_after_select, {"execute": "execute", "end": END}
    )
    graph.add_edge("execute", "validate")
    graph.add_conditional_edges(
        "validate", _route_after_validate, {"reconcile": "reconcile", "end": END}
    )
    graph.add_conditional_edges(
        "reconcile", _route_after_reconcile, {"deliver": "deliver", "end": END}
    )
    graph.add_conditional_edges(
        "deliver", _route_after_deliver, {"end": END}
    )

    compiled = graph.compile()
    logger.info(
        "[post_l3] chain compiled: parse->ground->select->execute->validate->reconcile->deliver"
    )
    return compiled


__all__ = ["build_post_l3_chain"]
