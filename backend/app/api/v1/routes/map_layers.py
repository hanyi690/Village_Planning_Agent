"""GET /sessions/{session_id}/map-layers transport."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.api.v1.contracts import MapLayerCollection
from app.application.projections.delivery import delivery_projections
from app.application.projections.session import ProjectionNotFoundError


router = APIRouter(prefix="/api/v1", tags=["Stable v1"])


@router.get("/sessions/{session_id}/map-layers", response_model=MapLayerCollection)
async def get_map_layers(session_id: str) -> MapLayerCollection:
    try:
        view = await delivery_projections.map_layers(session_id)
    except ProjectionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return MapLayerCollection.model_validate(view.model_dump(mode="python"))


__all__ = ["get_map_layers", "router"]
