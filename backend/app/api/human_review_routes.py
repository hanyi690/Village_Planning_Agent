"""HUMAN review write boundary for the active LangGraph checkpoint."""

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, model_validator

from app.services.resume_service import ResumeConflictError

logger = logging.getLogger(__name__)
router = APIRouter()


class ResolveRequest(BaseModel):
    """Canonical decision submitted for the active HUMAN checkpoint."""

    decisions: Dict[str, Any] = Field(..., min_length=1)
    action: Optional[str] = Field(
        None,
        pattern="^(retry|accept|reject|approve)$",
        description="审查动作: retry/accept(approve)/reject",
    )
    event_id: Optional[str] = Field(None, description="HUMAN checkpoint 幂等键")

    @model_validator(mode="after")
    def populate_action(self):
        if self.action is None:
            self.action = self.decisions.get("action")
        if self.action is None:
            raise ValueError("action is required")
        if self.action not in {"retry", "accept", "reject", "approve"}:
            raise ValueError(f"unsupported action: {self.action!r}")
        if self.action == "accept":
            self.action = "approve"
        self.decisions.setdefault("action", self.action)
        if self.decisions.get("action") == "accept":
            self.decisions["action"] = "approve"
        return self


@router.post("/api/human-review/{session_id}/resolve")
async def resolve_human_review(session_id: str, request: ResolveRequest):
    """Submit the decision and resume the exact active checkpoint."""
    try:
        from app.services.runtime import PlanningRuntimeService

        current = await PlanningRuntimeService.aget_state_values(session_id) or {}
        current_interrupt = current.get("human_interrupt") or {}
        if request.event_id and request.event_id != current_interrupt.get("event_id"):
            raise HTTPException(status_code=409, detail="event_id does not match active checkpoint")
        if current.get("human_review_resume_consumed"):
            raise HTTPException(status_code=409, detail="checkpoint was already resumed")
        await PlanningRuntimeService.resume_from_interrupt(
            session_id,
            request.decisions,
            expected_event_id=request.event_id,
        )
        resumed = await PlanningRuntimeService.aget_state_values(session_id) or {}
        result = {
            "phase": resumed.get("phase"),
            "paused_stage": resumed.get("paused_stage"),
            "delivery_status": resumed.get("delivery_status"),
            "human_review_event_id": resumed.get("human_review_event_id"),
        }
    except ResumeConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("[human-review] resolve failed for %s: %s", session_id, exc)
        raise HTTPException(status_code=500, detail=f"Resume failed: {exc}") from exc
    return {"session_id": session_id, "resolved": True, "result": result}


__all__ = ["router", "ResolveRequest"]
