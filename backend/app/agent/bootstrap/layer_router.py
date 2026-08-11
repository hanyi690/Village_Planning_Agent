"""Layer router + L1/L2/L3 dimension worker nodes for the unified planning graph.

Wave M3: ``after_conversation`` / ``after_analysis`` dispatch dimension work
through ``layer_router``. LangGraph Send payloads do NOT survive a shared noop
node (per-invocation fields like ``dimension_key`` are lost once the merged
parent state is read), so ``layer_router`` is a forwarding node: it reads the
phase from its input, picks the matching worker via ``route_by_phase``, and
re-dispatches the full payload with ``Command(goto=[Send(...)])``.

``advance_phase`` performs the phase advance on gate PASS — conditional edges
cannot return ``Command`` and Send payloads do not update the parent state, so
the advance is done by a real node returning ``Command(update=..., goto=[Send] | END)``.
"""

from __future__ import annotations

from typing import Any, Dict, List

from langgraph.graph import END
from langgraph.types import Command, Send

from app.agent.bootstrap.phase_machine import _phase_to_layer, get_next_phase
from app.agent.l1_observe.analysis_node import analyze_dimension
from app.agent.l2_strategize.worker import analyze_l2_dimension
from app.agent.l3_plan.worker import analyze_l3_dimension
from app.utils.logger import get_logger

logger = get_logger(__name__)


_PHASE_TO_WORKER: Dict[str, str] = {
    "layer1": "l1_worker",
    "layer2": "l2_worker",
    "layer3": "l3_worker",
}


def _worker_for_phase(phase: str) -> str:
    """Return the worker node name matching ``phase`` (layer1/2/3 -> l1/l2/l3_worker)."""
    worker = _PHASE_TO_WORKER.get(phase)
    if worker is None:
        logger.warning("[_worker_for_phase] unexpected phase=%r, defaulting to l1_worker", phase)
        return "l1_worker"
    return worker


def route_by_phase(state: Dict[str, Any]) -> str:
    """Return the worker node name matching ``state['phase']``.

    ``layer1``/``layer2``/``layer3`` -> ``l1_worker``/``l2_worker``/``l3_worker``.
    Any unexpected value (e.g. "completed") logs and falls back to ``l1_worker``;
    this should not be reached because after_conversation / after_analysis gate
    those cases before dispatching.
    """
    phase = state.get("phase", "layer1")
    worker = _PHASE_TO_WORKER.get(phase)
    if worker is None:
        logger.warning("[route_by_phase] unexpected phase=%r, defaulting to l1_worker", phase)
        return "l1_worker"
    return worker


def layer_router_noop(state: Dict[str, Any]) -> Dict[str, Any]:
    """Pass-through noop node (kept for API compatibility).

    NOTE: not used as the graph node — a shared noop would drop per-Send fields
    (``dimension_key``) before the conditional edge reads the merged state. The
    graph wires ``layer_router`` to :func:`layer_router_node` instead.
    """
    return {}


def layer_router_node(state: Dict[str, Any]) -> Command:
    """Forward a layer_router invocation to the worker matching ``phase``.

    Preserves the full per-Send payload (including ``dimension_key``) by
    re-dispatching it via ``Command(goto=[Send(worker, state)])``.
    """
    worker = route_by_phase(state)
    return Command(goto=[Send(worker, state)])


async def l1_worker_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """L1 dimension worker — delegates to the shared L1 analysis node."""
    return await analyze_dimension(state)


async def l2_worker_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """L2 dimension worker — delegates to the independent L2 worker."""
    return await analyze_l2_dimension(state)


async def l3_worker_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """L3 dimension worker — delegates to the independent L3 worker."""
    return await analyze_l3_dimension(state)


def _ready_dispatch(state: Dict[str, Any], phase: str) -> List[Send]:
    """Build the Send list for ready dimensions of ``phase``.

    Same-layer dependency check only. Cross-layer dispatch is handled by
    ``advance_phase_node`` after the layer gate PASS.
    """
    layer = _phase_to_layer(phase)
    if layer is None:
        return []

    from app.config.loader import list_dimensions

    dim_configs = list_dimensions(layer)
    completed = state.get("completed_dimensions", {}).get(f"layer{layer}", [])
    ready: List[str] = []
    for dim in dim_configs:
        if dim.key in completed:
            continue
        if all(dep in completed for dep in (dim.depends_on or [])):
            ready.append(dim.key)

    worker = _worker_for_phase(phase)
    return [Send(worker, {**state, "phase": phase, "dimension_key": d}) for d in ready]


def advance_phase_node(state: Dict[str, Any]) -> Command:
    """Gate PASS phase advance node.

    Called when ``after_analysis`` sees a PASS gate decision. Advances ``phase``
    (layer1 -> layer2 -> layer3 -> completed) and routes to the next layer's
    dispatch via Send, or to the post-L3 chain (parse) when the plan is
    complete, or to END when nothing is ready.
    """
    phase = state.get("phase", "layer1")
    layer = _phase_to_layer(phase)
    next_phase = get_next_phase(phase)
    if next_phase is None:
        next_phase = "post_l3"

    update: Dict[str, Any] = {
        "phase": next_phase,
        "current_stage": f"L{layer}" if layer is not None else str(phase).upper(),
        "next_stage": "L3" if next_phase == "layer3" else ("PARSE" if next_phase == "post_l3" else str(next_phase).upper()),
        "previous_layer": layer if layer is not None else state.get("previous_layer", 0),
        "layer_just_completed": None,
    }
    sends = _ready_dispatch(state, next_phase)
    if sends:
        logger.info("[advance_phase] %s -> %s, dispatching %d dim(s)", phase, next_phase, len(sends))
        return Command(update=update, goto=sends)
    if next_phase == "post_l3":
        # Wave M: L1/L2/L3 全部完成 -> 自动进入 post-L3 链（parse 主图节点）。
        # 不再依赖用户消息触发 gis_analysis / gis_agent 黑盒节点。
        logger.info("[advance_phase] %s -> post_l3, entering post-L3 chain (parse)", phase)
        update.update({
            "post_l3_status": "auto_continue",
            "paused_stage": "",
            "next_stage": "PARSE",
        })
        return Command(update=update, goto="parse")
    logger.info("[advance_phase] %s -> %s, no ready dims, END", phase, next_phase)
    return Command(update=update, goto=END)


__all__ = [
    "route_by_phase",
    "layer_router_noop",
    "layer_router_node",
    "l1_worker_node",
    "l2_worker_node",
    "l3_worker_node",
    "advance_phase_node",
]
