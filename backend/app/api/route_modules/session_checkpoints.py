"""Session checkpoint routes - list, resume, and inspect checkpoints."""

import logging
from typing import Any, Dict

from fastapi import APIRouter, HTTPException

from app.api.session_routes import _launch_background
from app.services.runtime import PlanningRuntimeService
from app.services.sse import sse_manager

logger = logging.getLogger(__name__)
router = APIRouter()


def _is_stable_checkpoint(values: Dict[str, Any]) -> tuple:
    """判断检查点是否为稳定完成快照（非并行中间态）

    并行 Send API 每完成一个节点就保存检查点，这些中间检查点状态不完整。
    只有 layer_completion_check 执行后的检查点才是真正的完成快照。

    Returns:
        (is_stable: bool, kind: str)  kind ∈ {"layer", "revision", "completed", "intermediate"}
    """
    if not values:
        return False, "intermediate"
    if values.get("phase") == "completed":
        return True, "completed"
    if (values.get("last_revised_dimensions")
            and not values.get("is_revision", False)):
        return True, "revision"
    if (values.get("is_interrupted")
            and values.get("previous_layer", 0) > 0):
        return True, "layer"
    return False, "intermediate"


@router.get("/api/sessions/{session_id}/checkpoints")
async def get_checkpoints(session_id: str):
    """获取检查点列表，标记稳定完成检查点"""
    checkpoints = []
    async for snapshot in PlanningRuntimeService.aget_state_history(session_id):
        checkpoint_id = snapshot.config.get("configurable", {}).get("checkpoint_id", "")
        values = dict(snapshot.values) if snapshot.values else {}
        is_stable, kind = _is_stable_checkpoint(values)
        checkpoints.append({
            "checkpoint_id": checkpoint_id,
            "phase": values.get("phase", "init"),
            "layer": values.get("previous_layer", 0),
            "stable": is_stable,
            "kind": kind,
        })
    return {"session_id": session_id, "checkpoints": checkpoints, "count": len(checkpoints)}


@router.post("/api/sessions/{session_id}/resume/{checkpoint_id}")
async def resume_from_checkpoint(session_id: str, checkpoint_id: str):
    """从检查点恢复 — 仅允许稳定完成检查点"""
    target_state = None
    async for snapshot in PlanningRuntimeService.aget_state_history(session_id):
        if snapshot.config.get("configurable", {}).get("checkpoint_id", "") == checkpoint_id:
            target_state = snapshot
            break

    if not target_state:
        raise HTTPException(status_code=404, detail=f"Checkpoint not found: {checkpoint_id}")

    values = dict(target_state.values) if target_state.values else {}
    is_stable, kind = _is_stable_checkpoint(values)
    if not is_stable:
        raise HTTPException(
            status_code=400,
            detail=f"Checkpoint {checkpoint_id} is an intermediate state (kind={kind}), "
                   f"not a stable completion checkpoint. Restore from a 'layer' or 'revision' checkpoint.",
        )

    # ADR-005: migrate legacy artifact references exactly once at the
    # checkpoint-import boundary, before any runtime node executes.
    if values:
        try:
            from app.agent.bootstrap.artifact_runtime import migrate_legacy_artifacts
            values["artifact_refs"] = migrate_legacy_artifacts(values)
        except Exception as exc:
            logger.warning(
                "[checkpoint] legacy artifact migration failed for %s: %s",
                checkpoint_id, exc,
            )

    layer = values.get("previous_layer", 1) or 1
    sse_manager.append_event(session_id, {"type": "resumed", "checkpoint_id": checkpoint_id, "layer": layer, "kind": kind})
    sse_manager.publish_sync(session_id, {"type": "resumed", "checkpoint_id": checkpoint_id})

    _launch_background(session_id, PlanningRuntimeService._trigger_planning_execution(
        session_id, checkpoint_id=checkpoint_id, state_values=values
    ))
    return {"status": "resumed", "checkpoint_id": checkpoint_id, "layer": layer, "kind": kind}


__all__ = ["router"]