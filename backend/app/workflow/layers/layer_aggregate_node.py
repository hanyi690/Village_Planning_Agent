"""Layer aggregate node - wires L1/L2/L3 aggregates after layer completion.

Wave M2: this node sits between `layer_completion_check` and `after_analysis`.
When `layer_completion_check` detects that a layer's dimensions are all complete
and sets `layer_just_completed`, this node invokes the corresponding
`l1_aggregate`/`l2_aggregate`/`l3_aggregate` to produce the typed artifact
(snapshot/strategy/program), evaluate the gate, and persist the review package.

Placed as a SEPARATE node (not inline in completion_check) to respect the
interrupt invariant: `interrupt()` in step_mode re-executes the entire node
on resume, so aggregates must run in a different node to avoid double-execution.
"""

from __future__ import annotations

from typing import Any, Dict

from app.infrastructure.logging import get_logger

logger = get_logger(__name__)


def _update_explore_retry(state: Dict[str, Any], patch: Dict[str, Any], layer: int, stage: str) -> None:
    """Update the EXPLORE retry counter based on the persisted layer gate.

    Non-PASS gates (EXPLORE/rework) increment the counter; PASS resets it.
    The gate is loaded from the merged CAS artifact refs, not an inline dict.
    """
    from app.workflow.state import load_root_gate

    merged = {
        **state,
        **patch,
        "artifact_refs": {
            **dict(state.get("artifact_refs") or {}),
            **dict(patch.get("artifact_refs") or {}),
        },
    }
    try:
        gate = load_root_gate(merged, stage)
    except Exception:
        gate = None
    route = gate.feedback_route if gate is not None else None
    counts = dict(state.get("retry_counts") or {})
    counter_key = f"l{layer}_explore"
    if route is None or route == "PASS":
        counts.pop(counter_key, None)
    else:
        counts[counter_key] = counts.get(counter_key, 0) + 1
    patch["retry_counts"] = counts


async def layer_aggregate_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Invoke the layer-specific aggregate based on `layer_just_completed`."""
    if state.get("is_revision"):
        return {}

    layer = state.get("layer_just_completed")
    if layer is None:
        return {}

    # Defensive: a stale layer_just_completed from an earlier layer must
    # never run the wrong aggregate.  phase is the authoritative cursor.
    phase_layer = None
    try:
        from app.workflow.layers.phase_machine import _phase_to_layer
        phase_layer = _phase_to_layer(str(state.get("phase") or ""))
    except Exception:
        phase_layer = None
    if phase_layer is not None and int(layer) != phase_layer:
        logger.warning(
            "[layer_aggregate] stale layer_just_completed=%s vs phase=%s, clearing",
            layer, state.get("phase"),
        )
        return {"layer_just_completed": None}

    logger.info("[layer_aggregate] layer=%d, invoking aggregate", layer)

    # L1 is the first producer of a persisted typed artifact.  Establish the
    # frozen PlanningContext before writing that artifact so its ref cannot be
    # created with an empty context version and become unrecoverable after the
    # later post-L3 bootstrap.  The helper is idempotent and only rebuilds the
    # context when a resumed worker has lost its in-process cache.
    aggregate_state = state
    if not state.get("context_version") or not state.get("context_ref"):
        from app.workflow.layers.context_bootstrap import bootstrap_context_node

        context_patch = await bootstrap_context_node(state)
        aggregate_state = {**state, **context_patch}

    if not aggregate_state.get("context_version") or not aggregate_state.get("context_ref"):
        raise RuntimeError(
            "CONTEXT_NOT_FROZEN: cannot persist versioned artifact with empty "
            "context_version. bootstrap_context failed to establish a valid context."
        )

    if layer == 1:
        from app.domain.assessment.aggregate import l1_aggregate

        patch = await l1_aggregate(aggregate_state)
        if aggregate_state is not state:
            patch = {**{k: aggregate_state[k] for k in ("context_version", "context_fingerprint", "context_ref", "bootstrap_context_done") if k in aggregate_state}, **patch}
        patch["layer_just_completed"] = None
        _update_explore_retry(state, patch, layer, "l1")
        # Enrichment consumes the typed L1Snapshot; it must run after this
        # aggregate persisted its artifact, not in layer_completion_check.
        from app.workflow.plan_state.completion_node import _invoke_extraction

        await _invoke_extraction(
            session_id=state.get("session_id", ""),
            layer=1,
            state={**aggregate_state, **patch},
        )
        return patch

    if layer == 2:
        from app.domain.objectives.aggregate import l2_aggregate

        patch = await l2_aggregate(aggregate_state)
        if aggregate_state is not state:
            patch = {**{k: aggregate_state[k] for k in ("context_version", "context_fingerprint", "context_ref", "bootstrap_context_done") if k in aggregate_state}, **patch}
        patch["layer_just_completed"] = None
        _update_explore_retry(state, patch, layer, "l2")
        from app.workflow.plan_state.completion_node import _invoke_extraction

        await _invoke_extraction(
            session_id=state.get("session_id", ""),
            layer=2,
            state={**aggregate_state, **patch},
        )
        return patch

    if layer == 3:
        from app.domain.program.aggregate import l3_aggregate

        patch = await l3_aggregate(aggregate_state)
        if aggregate_state is not state:
            patch = {**{k: aggregate_state[k] for k in ("context_version", "context_fingerprint", "context_ref", "bootstrap_context_done") if k in aggregate_state}, **patch}
        patch["layer_just_completed"] = None
        _update_explore_retry(state, patch, layer, "l3")
        from app.workflow.plan_state.completion_node import _invoke_extraction

        await _invoke_extraction(
            session_id=state.get("session_id", ""),
            layer=3,
            state={**aggregate_state, **patch},
        )
        return patch

    logger.warning("[layer_aggregate] unknown layer=%s, skipping", layer)
    return {"layer_just_completed": None}


__all__ = ["layer_aggregate_node"]
