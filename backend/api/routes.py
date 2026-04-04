"""
Unified API Routes - All endpoints in one place

This module consolidates all API routes from:
- planning.py (planning execution) - migrating to planning_service
- data.py (data access)
- files.py (file upload)
- knowledge.py (knowledge base)

Architecture:
- Services handle business logic (planning_service, sse_manager, checkpoint_service)
- Routes define endpoints and call services
- Gradual migration from planning.py to planning_service
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from typing_extensions import Annotated

from backend.services import planning_service, sse_manager, checkpoint_service
from backend.services.rate_limiter import rate_limiter, RateLimiter
from backend.schemas import TaskStatus

logger = logging.getLogger(__name__)

# ============================================
# Dependency Injection
# ============================================

def get_rate_limiter() -> RateLimiter:
    return rate_limiter

RateLimiterDep = Annotated[RateLimiter, Depends(get_rate_limiter)]


# ============================================
# Request/Response Schemas
# ============================================

class StartPlanningRequest(BaseModel):
    project_name: str
    village_data: str
    task_description: str = "村庄规划"
    constraints: str = "遵循相关法规"
    enable_review: bool = False
    step_mode: bool = False
    stream_mode: bool = True


class ReviewActionRequest(BaseModel):
    action: str
    feedback: str = ""
    dimensions: list[str] = []


# ============================================
# Router Setup
# ============================================

router = APIRouter()

# Import legacy routers for gradual migration
from backend.api.planning import router as planning_router
from backend.api.data import router as data_router
from backend.api import files, knowledge


# Include legacy routers (will be removed after full migration)
router.include_router(planning_router, tags=["Planning"])
router.include_router(data_router, tags=["Data"])
router.include_router(files.router, prefix="/api/files", tags=["Files"])
router.include_router(knowledge.router, prefix="/api/knowledge", tags=["Knowledge"])


# ============================================
# New Service-Based Endpoints (Gradual Migration)
# ============================================

# These endpoints use the new service layer and will replace legacy ones


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
# Session Status (using checkpoint_service)
# ============================================

@router.get("/api/sessions/{session_id}/status", tags=["Session"])
async def get_session_status_simple(session_id: str):
    """Get session status using CheckpointService."""
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
    result = await checkpoint_service.get_layer_reports(session_id, layer)
    return result


# ============================================
# Migration Status
# ============================================

# Legacy endpoints still in planning.py:
# - POST /api/planning/start
# - GET /api/planning/stream/{session_id}
# - POST /api/planning/review/{session_id}
# - GET /api/planning/status/{session_id}
# - DELETE /api/planning/sessions/{session_id}
# - ... and more
#
# These will be gradually migrated to use planning_service directly.

__all__ = ["router"]