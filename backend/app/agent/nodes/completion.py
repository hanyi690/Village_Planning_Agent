"""
Layer Completion Check Node

Runs AFTER reducer merges parallel dimension results.
Detects layer completion and sends SSE events (layer_completed, layer_paused).
Handles step_mode (pause) vs auto-advance (continuous) branching.
"""

from typing import Dict, Any

from app.utils.logger import get_logger

logger = get_logger(__name__)


async def layer_completion_check(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Check if current layer is complete after reducer merges parallel results.

    This node runs after all Send-dispatched analyze_dimension nodes have
    completed and their completed_dimensions have been merged by the reducer.

    Logic:
    1. If layer NOT complete -> no-op, return {}
    2. If layer complete + step_mode=True -> send layer_completed + layer_paused,
       set execution_paused=True
    3. If layer complete + step_mode=False -> auto-advance phase,
       send layer_completed + layer_started for next layer
    """
    from app.agent.state import (
        _phase_to_layer, get_layer_dimensions, get_next_phase,
        get_layer_name,
    )
    from app.utils.sse_publisher import SSEPublisher

    phase = state.get("phase", "layer1")
    if phase == "completed":
        return {}

    layer = _phase_to_layer(phase)
    if layer is None:
        return {}

    completed = state.get("completed_dimensions", {}).get(f"layer{layer}", [])
    total_dims = get_layer_dimensions(layer)

    logger.info(
        "[layer_completion_check] entry: phase=%s layer=%s completed=%s/%s",
        phase, layer, len(completed), len(total_dims),
    )

    # Not complete yet — continue processing
    if not (len(total_dims) > 0 and set(completed) == set(total_dims)):
        return {}

    logger.info(
        "[layer_completion_check] Layer %d completed: %d dimensions",
        layer, len(completed),
    )

    session_id = state.get("session_id", "")

    # 从数据库获取报告计算总字符数
    from ...services.report_store import ReportStore
    store = ReportStore.get_instance()
    layer_reports = await store.get_layer_reports(session_id, layer)
    total_chars = sum(len(v) for v in layer_reports.values()) if layer_reports else 0

    # Send layer_completed SSE event
    SSEPublisher.send_layer_complete(
        session_id=session_id,
        layer=layer,
        layer_name=get_layer_name(layer),
        dimension_count=len(completed),
        total_chars=total_chars,
    )

    step_mode = state.get("step_mode", False)  # Default to False for auto-advance

    if step_mode:
        # Step mode: pause and wait for user approval
        SSEPublisher.send_layer_paused(
            session_id=session_id,
            layer=layer,
            layer_name=get_layer_name(layer),
        )
        logger.info(
            "[layer_completion_check] Layer %d paused (step_mode), "
            "waiting for approval", layer,
        )
        return {
            "execution_paused": True,
            "pause_after_step": True,
            "previous_layer": layer,
        }

    # Auto mode: advance to next layer
    if layer < 3:
        next_phase = get_next_phase(phase)
        next_layer = _phase_to_layer(next_phase) if next_phase else None
        if next_phase and next_layer:
            SSEPublisher.send_layer_start(
                session_id=session_id,
                layer=next_layer,
                layer_name=get_layer_name(next_layer),
                dimension_count=len(get_layer_dimensions(next_layer)),
            )
            logger.info(
                "[layer_completion_check] Auto-advancing to layer %d", next_layer,
            )
            return {
                "phase": next_phase,
                "execution_paused": False,
                "pause_after_step": False,
                "previous_layer": layer,
            }

    # Layer 3 complete in auto mode -> mark completed
    logger.info("[layer_completion_check] All layers complete (auto mode)")
    return {"phase": "completed"}


__all__ = ["layer_completion_check"]
