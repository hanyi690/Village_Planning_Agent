"""Human Review Routes — post-L3 chain HITL (Wave N P5).

Endpoints:
1. GET  /api/human-review/{session_id}          — pending items of a paused chain
2. POST /api/human-review/{session_id}/resolve   — submit decisions, resume chain

Follows the session_routes.py style (APIRouter, pydantic request models,
HTTPException error handling).
"""

import logging
from typing import Any, Dict

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.post_l3_resume import resume_post_l3_chain

logger = logging.getLogger(__name__)
router = APIRouter()


class ResolveRequest(BaseModel):
    """审查决策请求体 — 直接传给 post-L3 链的 interrupt() 调用点。"""

    decisions: Dict[str, Any] = Field(..., description="审查决策（resume payload）")


@router.get("/api/human-review/{session_id}")
async def get_human_review(session_id: str):
    """返回暂停在 human_review 的 post-L3 链待审 items（从主图 AgentState 读）。"""
    from app.services.runtime import PlanningRuntimeService

    state = await PlanningRuntimeService.aget_state_values(session_id)
    if not state:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    pending = list(state.get("post_l3_pending_review") or [])
    return {
        "session_id": session_id,
        "post_l3_status": state.get("post_l3_status", ""),
        "pending_items": pending,
        "count": len(pending),
    }


@router.post("/api/human-review/{session_id}/resolve")
async def resolve_human_review(session_id: str, request: ResolveRequest):
    """提交审查决策并 resume post-L3 链，返回最终成果。"""
    try:
        result = await resume_post_l3_chain(session_id, request.decisions)
    except Exception as e:  # noqa: BLE001 — surface to caller
        logger.error("[human-review] resolve failed for %s: %s", session_id, e)
        raise HTTPException(status_code=500, detail=f"Resume failed: {e}")

    return {"session_id": session_id, "resolved": True, "result": result}


__all__ = ["router"]
