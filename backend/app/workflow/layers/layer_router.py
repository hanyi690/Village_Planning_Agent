"""L1/L2/L3 dimension worker nodes + phase advance for the unified planning graph.

``after_conversation`` / ``after_analysis`` dispatch dimension work directly to
``l1_worker``/``l2_worker``/``l3_worker`` via ``Send`` (the per-Send payload
keeps ``dimension_key``/``phase``; a shared noop node would drop those fields).

``advance_phase`` performs the phase advance on gate PASS — conditional edges
cannot return ``Command`` and Send payloads do not update the parent state, so
the advance is done by a real node returning ``Command(update=..., goto=[Send] | END)``.
"""

from __future__ import annotations

from typing import Any, Dict, List

from langgraph.graph import END
from langgraph.types import Command, Send, TimeoutPolicy

from app.workflow.layers.phase_machine import _phase_to_layer, get_next_phase
from app.domain.assessment.analysis_node import analyze_dimension
from app.domain.objectives.worker import analyze_l2_dimension
from app.domain.program.worker import analyze_l3_dimension
from app.infrastructure.logging import get_logger

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


def _dispatch_state(state: Dict[str, Any], **overrides: Any) -> Dict[str, Any]:
    """Build a worker Send payload without one-shot layer-control residue.

    LangGraph Send branches carry the full parent state; a stale
    ``layer_just_completed`` from an earlier layer checkpoint must not ride
    along into the next wave's workers.
    """
    payload = dict(state)
    payload["layer_just_completed"] = None
    payload.update(overrides)
    return payload



def _dimension_idle_timeout(dimension_key: Any) -> float | None:
    """Per-dispatch idle timeout for a long-tail dimension, if configured (A7)."""
    key = str(dimension_key or "").strip()
    if not key:
        return None
    try:
        from app.core.settings import DIMENSION_TIMEOUT_S
    except Exception:
        return None
    configured = DIMENSION_TIMEOUT_S.get(key)
    if configured is None:
        return None
    try:
        return max(0.0, float(configured))
    except (TypeError, ValueError):
        return None


def _send_worker(worker: str, payload: Dict[str, Any]) -> Send:
    """Build a dimension-worker Send with an optional per-dispatch timeout.

    Official LangGraph API: ``Send(node, arg, timeout=TimeoutPolicy(...))``.
    When no per-dimension timeout is configured the Send is byte-for-byte the
    previous ``Send(worker, payload)``, so default behavior is unchanged.
    """
    timeout = _dimension_idle_timeout(payload.get("dimension_key"))
    if timeout is None:
        return Send(worker, payload)
    return Send(worker, payload, timeout=TimeoutPolicy(idle_timeout=timeout))

def revision_dispatch_node(state: Dict[str, Any]) -> Command:
    """Dispatch only the first pending wave of an explicit revision plan."""
    impact_tree = state.get("revision_impact_tree") or {}
    completed = {
        dimension
        for dimensions in (state.get("revision_completed_dims") or {}).values()
        for dimension in dimensions
    }
    pending_waves = [
        (int(wave), [dimension for dimension in dimensions if dimension not in completed])
        for wave, dimensions in impact_tree.items()
        if any(dimension not in completed for dimension in dimensions)
    ]
    if not pending_waves:
        return Command(goto=END)
    _, dimensions = min(pending_waves, key=lambda item: item[0])
    worker = _worker_for_phase(state.get("phase", "layer3"))
    logger.info("[revision_dispatch] dimensions=%s worker=%s", dimensions, worker)
    return Command(goto=[
        _send_worker(worker, _dispatch_state(state, dimension_key=dimension, is_revision=True))
        for dimension in dimensions
    ])


def provider_resume_dispatch_node(state: Dict[str, Any]) -> Command:
    """Resume exactly the provider-failed dimensions once.

    Infrastructure recovery is not a planning revision.  Keeping this as a
    real Command node lets the checkpoint consume the one-shot dimension list
    before fan-out and prevents ``after_analysis`` from redispatching every
    merely incomplete dimension.
    """
    dimensions = list(dict.fromkeys(
        str(item).strip()
        for item in (state.get("provider_resume_dimensions") or [])
        if str(item).strip()
    ))
    if not dimensions:
        logger.warning("[provider_resume_dispatch] empty dimension list")
        return Command(update={"provider_resume_dimensions": []}, goto=END)
    worker = _worker_for_phase(state.get("phase", "layer3"))
    logger.info(
        "[provider_resume_dispatch] dimensions=%s worker=%s",
        dimensions,
        worker,
    )
    return Command(
        update={"provider_resume_dimensions": []},
        goto=[
            _send_worker(
                worker,
                _dispatch_state(
                    state,
                    dimension_key=dimension,
                    is_revision=False,
                    provider_resume_dimensions=[],
                ),
            )
            for dimension in dimensions
        ],
    )


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
    logger.info(
        "[dimension_dispatch] phase=%s ready_count=%d ready_dimensions=%s",
        phase,
        len(ready),
        ready,
    )
    return [_send_worker(worker, _dispatch_state(state, phase=phase, dimension_key=d)) for d in ready]


def advance_phase_node(state: Dict[str, Any]) -> Command:
    """Gate PASS phase advance node.

    Called when ``after_analysis`` sees a PASS gate decision. Advances ``phase``
    (layer1 -> layer2 -> layer3 -> post_l3) and routes to the next layer's
    dispatch via Send, or to the post-L3 chain (target projection) when the plan is
    complete, or to END when nothing is ready.
    """
    phase = state.get("phase", "layer1")
    layer = _phase_to_layer(phase)
    next_phase = get_next_phase(phase)
    if next_phase is None:
        raise RuntimeError(f"INVALID_PHASE_TRANSITION: {phase!r} has no successor")

    update: Dict[str, Any] = {
        "phase": next_phase,
        "current_stage": f"L{layer}" if layer is not None else str(phase).upper(),
        "next_stage": "L3" if next_phase == "layer3" else ("TARGET_PROJECTION" if next_phase == "post_l3" else str(next_phase).upper()),
        "previous_layer": layer if layer is not None else state.get("previous_layer", 0),
        "layer_just_completed": None,
    }
    sends = _ready_dispatch(state, next_phase)
    if sends:
        logger.info("[advance_phase] %s -> %s, dispatching %d dim(s)", phase, next_phase, len(sends))
        return Command(update=update, goto=sends)
    if next_phase == "post_l3":
        # L1/L2/L3 completion enters the target-projection chain.
        # 不再依赖用户消息触发 gis_analysis / gis_agent 黑盒节点。
        logger.info("[advance_phase] %s -> post_l3, entering target-projection chain", phase)
        update.update({
            "post_l3_status": "auto_continue",
            "paused_stage": "",
            "next_stage": "TARGET_PROJECTION",
        })
        return Command(update=update, goto="target_projection")
    logger.info("[advance_phase] %s -> %s, no ready dims, END", phase, next_phase)
    return Command(update=update, goto=END)


__all__ = [
    "revision_dispatch_node",
    "provider_resume_dispatch_node",
    "l1_worker_node",
    "l2_worker_node",
    "l3_worker_node",
    "advance_phase_node",
    "_send_worker",
]
