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
    # Debug: log entry to confirm execution
    is_revision = state.get("is_revision", False)
    pending_count = len(state.get("pending_reports", []))
    logger.info(
        "[layer_completion_check] entry: is_revision=%s pending_reports=%d",
        is_revision, pending_count,
    )

    from app.agent.state import (
        _phase_to_layer, get_layer_dimensions, get_next_phase,
        get_layer_name,
    )
    from app.config.loader import get_dimension_layer as _get_dim_layer
    from app.utils.sse_publisher import SSEPublisher
    from app.services.report_store import ReportStore

    # 级联修订完成检测：检查所有修订波次是否完成
    if state.get("is_revision"):
        impact_tree = state.get("revision_impact_tree", {})
        completed = state.get("revision_completed_dims", {})
        all_completed = [d for dims in completed.values() for d in dims]
        all_dims = [d for dims in impact_tree.values() for d in dims]

        # 添加目标维度到 all_dims（impact_tree 不包含 Wave 0 目标维度）
        target_dims = state.get("revision_target_dimensions", [])
        all_dims.extend(target_dims)

        # 即使修订未完成，也要将 pending_reports 写入 DB
        # 作为 analyze_dimension 即时保存失败时的兜底
        # 注意：analyze_dimension 已即时保存，这里只处理兜底
        pending_reports = state.get("pending_reports", [])
        if pending_reports:
            store = ReportStore.get_instance()
            all_dims_set = set(all_dims)
            revision_reports = [r for r in pending_reports if r.get("dimension_key") in all_dims_set]
            # 按 report_id 去重
            seen_report_ids = set()
            unique_reports = []
            for r in revision_reports:
                rid = r.get("report_id")
                if rid not in seen_report_ids:
                    seen_report_ids.add(rid)
                    unique_reports.append(r)
            if unique_reports:
                # bulk_save 内部按 version 去重，已保存的会跳过
                await store.bulk_save(unique_reports)
                logger.info(
                    "[layer_completion_check] Revision: saved %d reports to DB (deduped from %d)",
                    len(unique_reports), len(revision_reports),
                )

        if set(all_completed) == set(all_dims):
            logger.info(
                "[layer_completion_check] Revision complete: %d dimensions",
                len(all_dims),
            )
            # Emit SSE events to clear frontend revision indicators
            session_id = state.get("session_id", "")
            for dim_key in all_dims:
                dim_layer = _get_dim_layer(dim_key) or 1
                SSEPublisher.send_event(
                    session_id=session_id,
                    event_type="dimension_reset_complete",
                    dimension_key=dim_key,
                    layer=dim_layer,
                )
            SSEPublisher.send_event(
                session_id=session_id,
                event_type="cascade_complete",
                revised_dimensions=all_dims,
            )
            return {
                "is_revision": False,
                "need_revision": False,
                "revision_feedback": None,
                "revision_impact_tree": None,
                "revision_completed_dims": {},
                "last_revised_dimensions": all_dims,
                "pending_reports": [],
            }
        return {}

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

    # Performance optimization: Use cached char count instead of DB query
    layer_char_counts = state.get("layer_char_counts", {})
    total_chars = layer_char_counts.get(layer, 0)

    # Reports already saved to DB by analyze_dimension immediately after completion
    pending_reports = state.get("pending_reports", [])

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
            "pending_reports": [],  # Clear buffer after batch write
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
                "pending_reports": [],  # Clear buffer after batch write
            }

    # Layer 3 complete in auto mode -> mark completed
    logger.info("[layer_completion_check] All layers complete (auto mode)")
    return {
        "phase": "completed",
        "pending_reports": [],  # Clear buffer after batch write
    }


__all__ = ["layer_completion_check"]
