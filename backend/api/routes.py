"""
Unified API Routes - All endpoints in one place

This module consolidates all API routes from:
- planning/ (planning execution)
- data.py (data access)
- files.py (file upload)
- knowledge.py (knowledge base)

Architecture:
- Services handle business logic (planning_runtime_service, sse_manager, checkpoint_service)
- Routes define endpoints and call services
"""

from __future__ import annotations

import logging

from fastapi import APIRouter

from backend.api.planning import router as planning_router
from backend.api.data import router as data_router
from backend.api import files, knowledge, gis_upload

logger = logging.getLogger(__name__)

# Main router
router = APIRouter()

# Include planning module router
router.include_router(planning_router, tags=["Planning"])

# Include other routers
router.include_router(data_router, tags=["Data"])
router.include_router(files.router, prefix="/api/files", tags=["Files"])
router.include_router(knowledge.router, prefix="/api/knowledge", tags=["Knowledge"])
router.include_router(gis_upload.router, prefix="/api/gis", tags=["GIS"])


# ============================================
# Health Check
# ============================================

@router.get("/api/health", tags=["Health"])
async def unified_health_check():
    """Unified health check endpoint"""
    return {
        "status": "healthy",
        "service": "village-planning-backend",
        "version": "1.0.0",
        "modules": ["planning", "data", "files", "knowledge"]
    }


# ============================================
# Session Status (convenience endpoints)
# ============================================

@router.get("/api/sessions/{session_id}/status", tags=["Session"])
async def get_session_status_simple(session_id: str):
    """Get session status using CheckpointService."""
    from backend.services import checkpoint_service
    from src.orchestration.state import get_layer_dimensions

    state = await checkpoint_service.get_state(session_id)
    if not state:
        return {"status": "not_found", "session_id": session_id}

    phase = state.get("phase", "init")
    completed_dims = state.get("completed_dimensions", {})

    return {
        "session_id": session_id,
        "status": "active",
        "phase": phase,
        "completed_layers": {
            "layer1": len(completed_dims.get("layer1", [])) >= len(get_layer_dimensions(1)),
            "layer2": len(completed_dims.get("layer2", [])) >= len(get_layer_dimensions(2)),
            "layer3": len(completed_dims.get("layer3", [])) >= len(get_layer_dimensions(3)),
        }
    }


@router.get("/api/sessions/{session_id}/reports/{layer}", tags=["Session"])
async def get_session_reports_simple(session_id: str, layer: int):
    """Get layer reports using CheckpointService."""
    from backend.services import checkpoint_service

    result = await checkpoint_service.get_layer_reports(session_id, layer)
    return result


__all__ = ["router"]