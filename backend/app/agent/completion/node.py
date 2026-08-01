"""
Layer Completion Check Node

Runs AFTER reducer merges parallel dimension results.
Detects layer completion and sends SSE events (layer_completed, layer_paused).
Handles step_mode (pause via interrupt()) vs auto-advance (continuous) branching.

Key: interrupt() re-executes the entire node on resume, so SSE events
must fire AFTER the interrupt point to avoid duplication.
"""

from typing import Dict, Any

from langgraph.types import interrupt
from app.utils.logger import get_logger

logger = get_logger(__name__)


async def _snapshot_bundle(session_id: str, trigger_reason: str) -> None:
    """Persist a versioned session bundle snapshot at a layer boundary.

    Non-fatal: a failed snapshot is logged and the pipeline continues.
    """
    if not session_id:
        return
    try:
        from app.services.session_bundle import snapshot_session_bundle

        await snapshot_session_bundle(session_id, trigger_reason=trigger_reason)
    except Exception as e:
        logger.warning(
            "[layer_completion_check] Bundle snapshot failed for %s (trigger=%s): %s",
            session_id, trigger_reason, e,
        )


async def _maybe_extract_bindings(session_id: str, layer: int) -> None:
    """Wave-end hook: extract village/BSM bindings from the completed layer.

    Non-fatal: extraction failures are logged and never break the pipeline.
    """
    if not session_id:
        return
    try:
        from app.services.report_store import ReportStore

        store = ReportStore.get_instance()
        reports = await store.get_layer_reports(session_id, layer)
        if not reports:
            logger.info("[layer_completion_check] No reports for L%d, skip extraction", layer)
            return
        from app.agent.gis.parse.agent import extract_bindings

        stats = await extract_bindings(session_id, wave=layer, reports=reports)
        logger.info("[layer_completion_check] PARSE bindings layer=%d stats=%s", layer, stats)
    except Exception as e:
        logger.warning("[layer_completion_check] PARSE bindings failed for %s L%d: %s", session_id, layer, e)


async def layer_completion_check(
    state: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Check if current layer is complete after reducer merges parallel results.

    This node runs after all Send-dispatched analyze_dimension nodes have
    completed and their completed_dimensions have been merged by the reducer.

    Logic:
    1. If layer NOT complete -> no-op, return {}
    2. If layer complete + step_mode=True -> interrupt() BEFORE any SSE events,
       then fire events based on resume action (approve/reject)
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
            session_id = state.get("session_id", "")
            # removed dimension_reset_complete (covered by dimension_complete)
            SSEPublisher.send_event(
                session_id=session_id,
                event_type="cascade_complete",
                revised_dimensions=all_dims,
            )
            await _snapshot_bundle(session_id, "revision")
            return {
                "is_revision": False,
                "need_revision": False,
                "revision_feedback": None,
                "revision_impact_tree": None,
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

    step_mode = state.get("step_mode", False)

    if step_mode:
        # CRITICAL: interrupt() BEFORE any SSE side effects.
        # On resume, the entire node re-executes from the top, so events
        # placed before interrupt() would fire twice. By placing interrupt()
        # first, we ensure events only fire once — after resume.
        logger.info(
            "[layer_completion_check] INTERRUPT: layer=%d phase=%s step_mode=True, awaiting human review",
            layer, phase,
        )
        resume_data = interrupt({
            "layer": layer,
            "phase": phase,
            "layer_name": get_layer_name(layer),
            "reason": "step_mode_awaiting_review",
        })
        action = resume_data.get("action", "approve")
        logger.info(
            "[layer_completion_check] RESUME received: action=%s layer=%d feedback=%s dimensions=%s images_count=%d resume_data_keys=%s",
            action, layer,
            resume_data.get("feedback", "")[:100] if resume_data.get("feedback") else "none",
            resume_data.get("dimensions", [])[:10],
            len(resume_data.get("images", []) or []),
            list(resume_data.keys()),
        )

        if action == "approve":
            # Now safe to send SSE events — this code only runs after resume
            SSEPublisher.send_layer_complete(
                session_id=session_id,
                layer=layer,
                layer_name=get_layer_name(layer),
                dimension_count=len(completed),
                total_chars=total_chars,
            )
            await _maybe_extract_bindings(session_id, layer)
            await _snapshot_bundle(
                session_id, "final" if layer >= 3 else f"layer{layer}",
            )
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
                        "[layer_completion_check] Approved: advancing to layer %d", next_layer,
                    )
                    return {
                        "phase": next_phase,
                        "previous_layer": layer,
                        "pending_reports": [],
                    }
            # Layer 3 complete after approval
            logger.info("[layer_completion_check] Layer 3 approved, all layers complete")
            return {"phase": "completed", "pending_reports": []}

        elif action == "reject":
            SSEPublisher.send_layer_complete(
                session_id=session_id,
                layer=layer,
                layer_name=get_layer_name(layer),
                dimension_count=len(completed),
                total_chars=total_chars,
            )
            await _snapshot_bundle(session_id, f"layer{layer}")
            logger.info(
                "[layer_completion_check] Rejected: starting revision for %s",
                resume_data.get("dimensions", []),
            )
            return {
                "need_revision": True,
                "is_revision": True,
                "revision_target_dimensions": resume_data.get("dimensions", []),
                "human_feedback": resume_data.get("feedback", ""),
                "revision_feedback": resume_data.get("feedback", ""),
                "revision_images": resume_data.get("images", []),
                "pending_reports": [],
            }

    # Auto mode: advance to next layer
    SSEPublisher.send_layer_complete(
        session_id=session_id,
        layer=layer,
        layer_name=get_layer_name(layer),
        dimension_count=len(completed),
        total_chars=total_chars,
    )
    await _maybe_extract_bindings(session_id, layer)
    await _snapshot_bundle(
        session_id, "final" if layer >= 3 else f"layer{layer}",
    )
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
                "previous_layer": layer,
                "pending_reports": [],
            }

    # Layer 3 complete in auto mode -> mark completed
    logger.info("[layer_completion_check] All layers complete (auto mode)")
    return {
        "phase": "completed",
        "pending_reports": [],
    }


__all__ = ["layer_completion_check"]
