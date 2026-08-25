"""HUMAN review transport: projection read and decision submit."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.api.v1.contracts import HumanReviewDecision, HumanReviewProjection
from app.application.commands.submit_human_review import (
    HumanDecisionConflictError,
    HumanDecisionNotFoundError,
    SubmitHumanDecisionCommand,
    submit_human_decision_service,
)
from app.application.projections.session import ProjectionNotFoundError, session_projections


router = APIRouter(prefix="/api/v1", tags=["Stable v1"])


@router.get("/sessions/{session_id}/human-review", response_model=HumanReviewProjection)
async def get_review(session_id: str) -> HumanReviewProjection:
    try:
        view = await session_projections.human_review(session_id)
    except ProjectionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return HumanReviewProjection.model_validate(view.model_dump(mode="python"))


@router.post("/sessions/{session_id}/human-review")
async def submit_review(session_id: str, decision: HumanReviewDecision) -> dict[str, object]:
    try:
        result = await submit_human_decision_service.execute(
            SubmitHumanDecisionCommand(
                session_id=session_id,
                event_id=decision.event_id,
                action=decision.action,
                decisions=dict(decision.decisions),
            )
        )
    except HumanDecisionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except HumanDecisionConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return result.model_dump(mode="json")


__all__ = [
    "get_review",
    "router",
    "submit_review",
]
