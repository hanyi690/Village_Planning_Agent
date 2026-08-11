"""Human Review Routes — post-L3 chain HITL (Wave N P5).

Endpoints:
1. GET  /api/human-review/{session_id}          — pending items of a paused chain
2. POST /api/human-review/{session_id}/resolve   — submit decisions, resume chain

Follows the session_routes.py style (APIRouter, pydantic request models,
HTTPException error handling).
"""

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, model_validator

from app.services.post_l3_resume import resume_post_l3_chain

logger = logging.getLogger(__name__)
router = APIRouter()


class ResolveRequest(BaseModel):
    """审查决策请求体 - 直接传给 post-L3 链的 interrupt() 调用点。"""

    decisions: Dict[str, Any] = Field(..., min_length=1, description="审查决策（resume payload，不可为空）")
    action: Optional[str] = Field(None, pattern="^(retry|accept|reject|approve)$", description="审查动作: retry/accept(approve)/reject")
    event_id: Optional[str] = Field(None, description="可选的 HUMAN checkpoint 幂等键")

    @model_validator(mode="after")
    def _populate_action(self):
        if self.action is None:
            dec = self.decisions if isinstance(self.decisions, dict) else {}
            dec_action = dec.get("action")
            if dec_action is not None:
                self.action = dec_action
        if self.action is None:
            raise ValueError("action is required (either top-level or decisions['action'])")
        if self.action not in ("retry", "accept", "reject", "approve"):
            raise ValueError(f"action must be one of retry/accept(approve)/reject, got {self.action!r}")
        if self.action == "accept":
            self.action = "approve"
        if isinstance(self.decisions, dict) and self.decisions.get("action") == "accept":
            self.decisions["action"] = "approve"
        if isinstance(self.decisions, dict) and self.decisions.get("action") is None:
            self.decisions["action"] = self.action
        return self


@router.get("/api/human-review/{session_id}")
async def get_human_review(session_id: str):
    """Return pending human-review items of a paused post-L3 chain."""
    from app.services.runtime import PlanningRuntimeService

    snapshot = await PlanningRuntimeService.aget_state(session_id)
    if not snapshot:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    state = dict(snapshot.values) if snapshot.values else {}

    interrupt_info = state.get("human_interrupt") or {}
    pending = list(
        interrupt_info.get("items")
        or state.get("human_review_items")
        or state.get("post_l3_pending_review")
        or []
    )
    paused_stage = interrupt_info.get("paused_stage") or state.get("paused_stage") or ""

    # On the first interrupt the checkpoint state has not yet been written,
    # so fall back to the interrupt payload carried by snapshot.tasks.
    from app.modules.schema.contracts.human_interrupt_contracts import normalize_human_interrupt

    for task in snapshot.tasks or ():
        for interrupt in getattr(task, "interrupts", None) or ():
            payload = getattr(interrupt, "value", None)
            if not isinstance(payload, dict):
                continue
            if not interrupt_info:
                interrupt_info = normalize_human_interrupt(payload)
            if not pending:
                pending = list(interrupt_info.get("items") or [])
            if not paused_stage:
                paused_stage = interrupt_info.get("paused_stage") or ""
            if pending and paused_stage:
                break
        if pending and paused_stage:
            break

    return {
        "session_id": session_id,
        "post_l3_status": state.get("post_l3_status", ""),
        "interrupt_info": interrupt_info or None,
        "event_id": interrupt_info.get("event_id") if interrupt_info else None,
        "paused_stage": paused_stage,
        "pending_items": pending,
        "count": len(pending),
    }


@router.post("/api/human-review/{session_id}/resolve")
async def resolve_human_review(session_id: str, request: ResolveRequest):
    """提交审查决策并 resume post-L3 链，返回最终成果。"""
    if not request.decisions:
        raise HTTPException(status_code=422, detail="decisions must be a non-empty object")
    try:
        # One interrupt checkpoint has one resume token.  A client may poll
        # or retry an HTTP request while the graph is still running; do not
        # feed the same decision into the checkpoint a second time.  A new
        # HUMAN pause resets this marker in ``prepare_human_review``.
        from app.services.runtime import PlanningRuntimeService

        current = await PlanningRuntimeService.aget_state_values(session_id) or {}
        current_interrupt = current.get("human_interrupt") or {}
        if request.event_id and request.event_id != current_interrupt.get("event_id"):
            raise HTTPException(
                status_code=409,
                detail="human review event_id does not match the active checkpoint",
            )
        if current.get("human_review_resume_consumed"):
            raise HTTPException(
                status_code=409,
                detail="human review checkpoint was already resumed; wait for a new HUMAN pause",
            )
        result = await resume_post_l3_chain(session_id, request.decisions)
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:  # noqa: BLE001 — surface to caller
        logger.exception("[human-review] resolve failed for %s: %s", session_id, e)
        raise HTTPException(status_code=500, detail=f"Resume failed: {e}")

    return {"session_id": session_id, "resolved": True, "result": result}


__all__ = ["router"]
