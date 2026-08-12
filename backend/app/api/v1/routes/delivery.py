"""GET /sessions/{session_id}/delivery transport."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.api.v1.contracts import DeliveryProjection
from app.application.projections.delivery import delivery_projections
from app.application.projections.session import ProjectionNotFoundError


router = APIRouter(prefix="/api/v1", tags=["Stable v1"])


@router.get("/sessions/{session_id}/delivery", response_model=DeliveryProjection)
async def get_delivery(session_id: str) -> DeliveryProjection:
    try:
        view = await delivery_projections.get(session_id)
    except ProjectionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return DeliveryProjection.model_validate(view.model_dump(mode="python"))


__all__ = ["get_delivery", "router"]
