"""Post-L3 chain node functions.

Wave M1: each node wraps a Wave B-L subgraph aggregate and the corresponding
gate evaluator, reading inputs from PostL3ChainState and writing typed
artifacts back. Deterministic (the aggregates are deterministic); no LLM in
this module. The EXECUTE/VALIDATE/RECONCILE/DELIVER nodes are added in the
companion half of this file (Task 5).
"""

from __future__ import annotations

from typing import Any

from app.agent.ground.aggregate import ground_aggregate
from app.agent.ground.gate import evaluate_ground_gate
from app.agent.parse.aggregate import compile_program
from app.agent.parse.gate_node import evaluate_parse_gate
from app.agent.select_graph.aggregate import select_aggregate
from app.agent.select_graph.gate import evaluate_select_gate
from app.utils.logger import get_logger

from .post_l3_state import PostL3ChainState

logger = get_logger(__name__)


def _accumulate_gate(gates: list[Any], gate: Any) -> list[Any]:
    return list(gates or []) + ([gate] if gate is not None else [])


async def parse_node(state: PostL3ChainState) -> dict[str, Any]:
    """PARSE node: compile PlanningProgram -> IntentCompilationResult + specs."""
    program = state.planning_program
    if program is None:
        logger.warning("[post_l3:parse] no planning_program in state; empty compile")
    run_id = state.run_id or state.session_id
    result, specs, gate = compile_program(
        program,
        run_id=run_id,
        context_version=state.context_version,
    )
    return {
        "intent": result,
        "specs": specs,
        "parse_gate": gate,
        "upstream_gates": _accumulate_gate(state.upstream_gates, gate),
    }


async def ground_node(state: PostL3ChainState) -> dict[str, Any]:
    """GROUND node: specs + context -> GroundingResult + gate."""
    context = state.context
    result = ground_aggregate(list(state.specs or []), context)
    gate = evaluate_ground_gate(result)
    return {
        "grounding_result": result,
        "ground_gate": gate,
        "upstream_gates": _accumulate_gate(state.upstream_gates, gate),
    }


async def select_node(state: PostL3ChainState) -> dict[str, Any]:
    """SELECT node: GroundingResult + intent + context -> SiteSelectionDecision."""
    context = state.context
    decision, briefs = select_aggregate(
        state.grounding_result, state.intent, context
    )
    projects = list(getattr(state.intent, "project_targets", None) or [])
    gate = evaluate_select_gate(decision, target_count=len(projects))
    return {
        "site_selection": decision,
        "land_design_briefs": briefs,
        "select_gate": gate,
        "upstream_gates": _accumulate_gate(state.upstream_gates, gate),
    }


__all__ = [
    "parse_node",
    "ground_node",
    "select_node",
]
