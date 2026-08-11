"""Session checkpoint routes - list, resume, and inspect checkpoints."""

import logging
from typing import Any, Dict

from fastapi import APIRouter, HTTPException

from app.services.composition import CompositionRoot
from app.services.runtime import PlanningRuntimeService
from app.services.sse import sse_manager
from app.modules.schema.contracts.resume_contracts import (
    ResumeMode,
    build_resume_plan,
)
from app.services.checkpoint_policy import (
    classify_checkpoint,
    first_pending_interrupt_payload,
    has_pending_interrupt,
)

logger = logging.getLogger(__name__)
router = APIRouter()


def _launch_background(session_id: str, coro) -> None:
    """Use the task supervisor without importing the aggregate router."""
    CompositionRoot.get_task_supervisor().create_task(session_id, coro)


@router.get("/api/sessions/{session_id}/checkpoints")
async def get_checkpoints(session_id: str):
    """获取检查点列表，标记稳定完成检查点"""
    checkpoints = []
    async for snapshot in PlanningRuntimeService.aget_state_history(session_id):
        checkpoint_id = snapshot.config.get("configurable", {}).get("checkpoint_id", "")
        values = dict(snapshot.values) if snapshot.values else {}
        pending_interrupt = has_pending_interrupt(snapshot)
        is_stable, kind = classify_checkpoint(values, pending_interrupt=pending_interrupt)
        plan = build_resume_plan(
            values,
            session_id=session_id,
            checkpoint_id=checkpoint_id,
            checkpoint_kind=kind,
            next_nodes=snapshot.next or (),
            pending_interrupt=first_pending_interrupt_payload(snapshot),
        )
        checkpoints.append({
            "checkpoint_id": checkpoint_id,
            "phase": values.get("phase", "init"),
            "layer": values.get("previous_layer", 0),
            "stable": is_stable,
            "kind": kind,
            "resume_plan": plan.model_dump(mode="json"),
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
    pending_interrupt = has_pending_interrupt(target_state)
    is_stable, kind = classify_checkpoint(values, pending_interrupt=pending_interrupt)
    interrupt_payload = first_pending_interrupt_payload(target_state)
    plan = build_resume_plan(
        values,
        session_id=session_id,
        checkpoint_id=checkpoint_id,
        checkpoint_kind=kind,
        next_nodes=target_state.next or (),
        pending_interrupt=interrupt_payload,
    )
    if not is_stable:
        raise HTTPException(
            status_code=400,
            detail=f"Checkpoint {checkpoint_id} is an intermediate state (kind={kind}), "
                   f"not a stable completion checkpoint. Restore from a 'layer' or 'revision' checkpoint.",
        )

    if plan.mode == ResumeMode.INTERRUPT:
        raise HTTPException(
            status_code=409,
            detail="This checkpoint has a pending HUMAN interrupt; use the channel-specific resolve endpoint.",
        )
    if plan.mode in {ResumeMode.BLOCKED, ResumeMode.COMPLETED}:
        raise HTTPException(status_code=409, detail=plan.reason)

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
    return {
        "status": "resumed",
        "checkpoint_id": checkpoint_id,
        "layer": layer,
        "kind": kind,
        "resume_plan": plan.model_dump(mode="json"),
    }


__all__ = ["router"]
