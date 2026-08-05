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

from app.utils.logger import get_logger

logger = get_logger(__name__)


async def layer_aggregate_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Invoke the layer-specific aggregate based on `layer_just_completed`."""
    if state.get("is_revision"):
        return {}

    layer = state.get("layer_just_completed")
    if layer is None:
        return {}

    logger.info("[layer_aggregate] layer=%d, invoking aggregate", layer)

    if layer == 1:
        from app.agent.l1_observe.aggregate import l1_aggregate

        patch = await l1_aggregate(state)
        patch["layer_just_completed"] = None
        return patch

    if layer == 2:
        from app.agent.l2_strategize.aggregate import l2_aggregate

        patch = await l2_aggregate(state)
        patch["layer_just_completed"] = None
        return patch

    if layer == 3:
        from app.agent.l3_plan.aggregate import l3_aggregate

        patch = await l3_aggregate(state)
        patch["layer_just_completed"] = None
        return patch

    logger.warning("[layer_aggregate] unknown layer=%s, skipping", layer)
    return {"layer_just_completed": None}


__all__ = ["layer_aggregate_node"]
