"""Session HITL routes - human-in-the-loop feedback, resume, and runtime config.

Endpoints:
- POST /api/sessions/{id}/feedback        - submit feedback/approve/reject/message
- GET/PATCH /api/sessions/{id}/rag-config - runtime RAG configuration
- PATCH /api/sessions/{id}/step-mode      - runtime step mode
"""

import logging
from typing import Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.api.session_routes import _launch_background
from app.core.events import SSEEventType
from app.services.runtime import PlanningRuntimeService
from app.services.sse import sse_manager
from app.agent.bootstrap.phase_machine import get_next_phase, _phase_to_layer
from app.utils.sse_publisher import SSEPublisher

logger = logging.getLogger(__name__)
router = APIRouter()


class FeedbackRequest(BaseModel):
    """反馈请求"""
    feedback: Optional[str] = Field(None, description="反馈内容")
    dimensions: Optional[List[str]] = Field(None, description="需修订的维度列表")
    message: Optional[str] = Field(None, description="对话消息")
    approve: bool = Field(False, description="批准当前层级继续")


@router.post("/api/sessions/{session_id}/feedback")
async def submit_feedback(session_id: str, request: FeedbackRequest):
    """提交反馈 — 使用 interrupt/resume 模式"""
    state = await PlanningRuntimeService.aget_state_values(session_id)
    if not state:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    if request.approve:
        current_phase = state.get("phase", "layer1")
        current_layer = _phase_to_layer(current_phase) or 1
        next_phase = get_next_phase(current_phase)
        logger.info("[feedback/approve] session=%s phase=%s", session_id, current_phase)

        # Resume from interrupt: approve action handled in layer_completion_check
        _launch_background(session_id, PlanningRuntimeService.resume_from_interrupt(
            session_id,
            resume_data={"action": "approve"},
        ))
        return {
            "status": "approved",
            "next_phase": next_phase,
            "current_layer": current_layer,
            "review_layer": current_layer,
        }

    if request.dimensions and request.feedback:
        # Reject with feedback: compute impact tree and resume from interrupt
        from app.config.dependency import compute_impact_tree

        final_tree: Dict[int, List[str]] = {0: list(request.dimensions)}
        completed_dims = state.get("completed_dimensions", {})
        all_completed_keys = set(d for dims in completed_dims.values() for d in dims)

        for target_dim in request.dimensions:
            tree = compute_impact_tree(target_dim)
            for wave, dims in tree.items():
                already_executed = [d for d in dims if d in all_completed_keys]
                if already_executed:
                    final_tree.setdefault(wave, []).extend(already_executed)
        final_tree = {w: list(set(dims)) for w, dims in final_tree.items() if d}

        _launch_background(session_id, PlanningRuntimeService.resume_from_interrupt(
            session_id,
            resume_data={
                "action": "reject",
                "feedback": request.feedback,
                "dimensions": request.dimensions,
                "images": [],
            },
            state_updates={
                "revision_impact_tree": final_tree,
                "revision_completed_dims": {},
            },
        ))

        # Emit SSE events for immediate visual feedback
        try:
            all_impacted = set(d for dims in final_tree.values() for d in dims)
            for target_dim in request.dimensions:
                SSEPublisher.send_event(
                    session_id=session_id,
                    event_type=SSEEventType.CASCADE_IMPACT,
                    trigger_dim=target_dim,
                    impacted_dimensions=list(all_impacted),
                )
        except Exception as e:
            logger.warning(f"[feedback] SSE cascade events failed: {e}")

        return {"status": "revision_started", "dimensions": request.dimensions}

    if request.message:
        from langchain_core.messages import HumanMessage, AIMessage

        GIS_KEYWORDS = ["空间布局", "gis分析", "布局分析", "地图分析"]
        is_gis_request = any(kw in request.message.lower() for kw in GIS_KEYWORDS)

        # Check if graph is in interrupt state
        snapshot = await PlanningRuntimeService.aget_state(session_id)
        is_interrupted = snapshot and snapshot.next and len(snapshot.next) > 0

        if is_interrupted:
            # Graph paused at interrupt — resume with message
            if is_gis_request:
                synthetic_msg = AIMessage(
                    content="",
                    tool_calls=[{
                        "name": "gis_analysis",
                        "id": f"call_gis_{session_id[:8]}",
                        "args": {"reason": request.message}
                    }],
                )
                _launch_background(session_id, PlanningRuntimeService.resume_from_interrupt(
                    session_id,
                    resume_data={"action": "message_injected", "message": request.message},
                    state_updates={"messages": [HumanMessage(content=request.message), synthetic_msg]},
                ))
                logger.info("[feedback] [%s] GIS intent detected, resumed from interrupt", session_id)
            else:
                _launch_background(session_id, PlanningRuntimeService.resume_from_interrupt(
                    session_id,
                    resume_data={"action": "message_injected", "message": request.message},
                    state_updates={"messages": [HumanMessage(content=request.message)]},
                ))
        else:
            # Graph not interrupted — inject message via aupdate_state + resume
            # Official pattern: aupdate_state(as_node="__start__") sets checkpoint.next,
            # then _trigger_planning_execution() resumes with astream(None, config)
            if is_gis_request:
                synthetic_msg = AIMessage(
                    content="",
                    tool_calls=[{
                        "name": "gis_analysis",
                        "id": f"call_gis_{session_id[:8]}",
                        "args": {"reason": request.message}
                    }],
                )
                await PlanningRuntimeService.aupdate_state(
                    session_id,
                    {"messages": [HumanMessage(content=request.message), synthetic_msg]},
                    as_node="__start__",
                )
                _launch_background(session_id, PlanningRuntimeService._trigger_planning_execution(session_id))
                logger.info("[feedback] [%s] GIS intent detected, new execution", session_id)
            else:
                await PlanningRuntimeService.aupdate_state(
                    session_id,
                    {"messages": [HumanMessage(content=request.message)]},
                    as_node="__start__",
                )
                _launch_background(session_id, PlanningRuntimeService._trigger_planning_execution(session_id))

        return {"status": "message_accepted"}

    return {"status": "no_action"}


class RagConfigRequest(BaseModel):
    """RAG configuration request"""
    rag_layer_config: Optional[Dict[int, bool]] = Field(None, description="Layer-level RAG config")
    rag_enabled: Optional[bool] = Field(None, description="Global RAG switch")


class RagConfigResponse(BaseModel):
    """RAG configuration response"""
    session_id: str
    rag_enabled: bool
    rag_layer_config: Dict[int, bool]


@router.get("/api/sessions/{session_id}/rag-config", response_model=RagConfigResponse)
async def get_rag_config(session_id: str):
    """Get current RAG configuration"""
    state = await PlanningRuntimeService.aget_state_values(session_id)
    if not state:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    config = state.get("config", {})
    return RagConfigResponse(
        session_id=session_id,
        rag_enabled=config.get("rag_enabled", True),
        rag_layer_config=config.get("rag_layer_config", {1: True, 2: False, 3: True}),
    )


@router.patch("/api/sessions/{session_id}/rag-config", response_model=RagConfigResponse)
async def update_rag_config(session_id: str, request: RagConfigRequest):
    """Update RAG configuration (runtime modification)

    Example:
        PATCH /api/sessions/{id}/rag-config
        {"rag_layer_config": {1: true, 2: false, 3: true}}
    """
    state = await PlanningRuntimeService.aget_state_values(session_id)
    if not state:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    config = state.get("config", {})
    current_rag_enabled = config.get("rag_enabled", True)
    current_layer_config = config.get("rag_layer_config", {1: True, 2: False, 3: True})

    new_rag_enabled = request.rag_enabled if request.rag_enabled is not None else current_rag_enabled
    new_layer_config = request.rag_layer_config if request.rag_layer_config is not None else current_layer_config

    for layer in [1, 2, 3]:
        if layer not in new_layer_config:
            new_layer_config[layer] = new_rag_enabled

    await PlanningRuntimeService.aupdate_state(session_id, {
        "config": {
            **config,
            "rag_enabled": new_rag_enabled,
            "rag_layer_config": new_layer_config,
        }
    }, as_node="conversation")

    logger.info(f"[rag-config] Updated {session_id}: enabled={new_rag_enabled}, layers={new_layer_config}")

    await sse_manager.publish(session_id, {
        "type": "rag_config_updated",
        "session_id": session_id,
        "rag_enabled": new_rag_enabled,
        "rag_layer_config": new_layer_config,
    })

    return RagConfigResponse(
        session_id=session_id,
        rag_enabled=new_rag_enabled,
        rag_layer_config=new_layer_config,
    )


class StepModeRequest(BaseModel):
    """Step mode configuration request"""
    step_mode: bool = Field(..., description="Enable/disable step mode")


class StepModeResponse(BaseModel):
    """Step mode configuration response"""
    session_id: str
    step_mode: bool


@router.patch("/api/sessions/{session_id}/step-mode", response_model=StepModeResponse)
async def update_step_mode(session_id: str, request: StepModeRequest):
    """Update step mode (runtime modification)"""
    state = await PlanningRuntimeService.aget_state_values(session_id)
    if not state:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    await PlanningRuntimeService.aupdate_state(session_id, {
        "step_mode": request.step_mode,
    }, as_node="conversation")

    logger.info(f"[step-mode] Updated {session_id}: step_mode={request.step_mode}")

    # If turning OFF step_mode while graph is interrupted, auto-approve
    if not request.step_mode:
        snapshot = await PlanningRuntimeService.aget_state(session_id)
        is_interrupted = snapshot and snapshot.next and len(snapshot.next) > 0
        if is_interrupted:
            _launch_background(session_id, PlanningRuntimeService.resume_from_interrupt(
                session_id,
                resume_data={"action": "approve"},
            ))
            logger.info(f"[step-mode] Auto-approved interrupted session {session_id}")

    await sse_manager.publish(session_id, {
        "type": "step_mode_updated",
        "session_id": session_id,
        "step_mode": request.step_mode,
    })

    return StepModeResponse(
        session_id=session_id,
        step_mode=request.step_mode,
    )


__all__ = ["router"]