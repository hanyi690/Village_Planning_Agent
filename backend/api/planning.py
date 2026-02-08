"""
Unified Planning API - Simplified Architecture

This API consolidates tasks.py and orchestration.py into a single, clean interface.

Endpoints:
- POST /api/planning/start - Create and start planning session
- GET /api/planning/stream/{session_id} - SSE streaming
- POST /api/planning/review/{session_id} - Review actions (approve/reject/rollback)
- GET /api/planning/status/{session_id} - Session status
- DELETE /api/planning/sessions/{session_id} - Delete session
"""

import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from backend.api.tool_manager import tool_manager
from backend.schemas import TaskStatus
from backend.services.background_task_manager import background_task_manager
from backend.services.rate_limiter import rate_limiter
from backend.utils.progress_helper import calculate_progress
from src.core.streaming import _format_sse_event
from src.orchestration.main_graph import create_village_planning_graph
from src.utils.output_manager import create_output_manager
from src.utils.paths import get_results_dir

router = APIRouter()
logger = logging.getLogger(__name__)

# In-memory session storage (for production: use Redis)
_sessions: Dict[str, Dict[str, Any]] = {}
# Track active executions to prevent duplicate runs
_active_executions: Dict[str, bool] = {}
# Store checkpointers for resume operations (keyed by session_id)
_session_checkpointer: Dict[str, Any] = {}
# Track stream states to prevent infinite reconnection
_stream_states: Dict[str, str] = {}  # session_id -> "active" | "paused" | "completed"


# ============================================
# Request/Response Schemas
# ============================================

class StartPlanningRequest(BaseModel):
    """Request to start planning session"""
    project_name: str = Field(..., description="项目名称/村庄名称")
    village_data: str = Field(..., description="村庄现状数据")
    task_description: str = Field(default="制定村庄总体规划方案", description="规划任务描述")
    constraints: str = Field(default="无特殊约束", description="规划约束条件")
    enable_review: bool = Field(default=True, description="启用人工审查")
    step_mode: bool = Field(default=True, description="步进模式（每层暂停）")
    stream_mode: bool = Field(default=False, description="启用流式输出（token级实时传输）")


class ReviewActionRequest(BaseModel):
    """Request for review action"""
    action: str = Field(..., description="Action: approve | reject | rollback")
    feedback: Optional[str] = Field(None, description="反馈内容（驳回时必填）")
    dimensions: Optional[List[str]] = Field(None, description="审查维度")
    checkpoint_id: Optional[str] = Field(None, description="目标检查点ID（回退时必填）")


class ResumeRequest(BaseModel):
    """Request to resume from checkpoint"""
    checkpoint_id: str = Field(..., description="检查点ID")
    project_name: str = Field(..., description="项目名称")


class SessionStatusResponse(BaseModel):
    """Session status response"""
    session_id: str
    status: str
    current_layer: Optional[int] = None
    created_at: str
    checkpoints: List[Dict[str, Any]]
    checkpoint_count: int
    progress: Optional[float] = None


# ============================================
# Helper Functions
# ============================================

def _generate_session_id() -> str:
    """Generate session ID (timestamp format)"""
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _get_session_path(project_name: str, session_id: str) -> Path:
    """Get file system path for session"""
    safe_name = project_name.replace('/', '_').replace('\\', '_').replace(':', '_')
    return get_results_dir() / safe_name / session_id


def _validate_resume_state(state: Dict[str, Any], current_layer: int) -> bool:
    """
    Validate that required state is present for resume

    Args:
        state: Current state dictionary
        current_layer: Layer to resume from

    Returns:
        True if state is valid for resume
    """
    if current_layer == 2:
        # Need Layer 1 data
        return bool(state.get("analysis_report") and state.get("analysis_dimension_reports"))
    elif current_layer == 3:
        # Need Layer 1 and 2 data
        return bool(
            state.get("analysis_report") and
            state.get("analysis_dimension_reports") and
            state.get("planning_concept") and
            state.get("concept_dimension_reports")
        )
    return True


async def _resume_graph_execution(session_id: str, state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Resume graph execution with restored state using background task manager

    Args:
        session_id: Session identifier
        state: Current state dictionary

    Returns:
        Response with stream URL for resuming execution
    """
    from langgraph.checkpoint.memory import MemorySaver

    # Validate state before resuming
    current_layer = state.get("current_layer", 1)
    if not _validate_resume_state(state, current_layer):
        logger.error(f"[Planning API] Invalid state for resume at layer {current_layer}")
        raise HTTPException(
            status_code=400,
            detail=f"Cannot resume at layer {current_layer}: missing required data"
        )

    # Retrieve or create checkpointer for this session
    checkpointer = _session_checkpointer.get(session_id)
    if not checkpointer:
        logger.warning(f"[Planning API] No checkpointer found for session {session_id}, creating new one")
        checkpointer = MemorySaver()
        _session_checkpointer[session_id] = checkpointer

    # Update session state
    if session_id in _sessions:
        _sessions[session_id]["initial_state"] = state
        _sessions[session_id]["current_layer"] = current_layer

    # Create graph and resume background execution
    graph = create_village_planning_graph(checkpointer=checkpointer)
    await background_task_manager.start_execution(
        session_id=session_id,
        graph=graph,
        initial_state=state,
        checkpointer=checkpointer,
        enable_streaming=state.get("_streaming_enabled", False)
    )

    logger.info(f"[Planning API] Resumed background execution for session {session_id}")

    return {
        "message": "Execution resumed",
        "session_id": session_id,
        "stream_url": f"/api/planning/stream/{session_id}",
        "current_layer": current_layer,
        "resumed": True
    }


def _build_initial_state(request: StartPlanningRequest, session_id: str) -> Dict[str, Any]:
    """
    Build initial state for main graph execution

    Consolidates all state initialization logic in one place for better maintainability.

    Args:
        request: Planning request with user inputs
        session_id: Unique session identifier

    Returns:
        Complete initial state dictionary
    """
    output_manager = create_output_manager(
        project_name=request.project_name,
        custom_output_path=str(_get_session_path(request.project_name, session_id))
    )

    # Register output_manager to global registry
    from src.utils.output_manager_registry import get_output_manager_registry
    registry = get_output_manager_registry()
    registry.register(session_id, output_manager)

    logger.info(f"[Planning API] 构建 LangGraph 初始状态")
    logger.info(f"[Planning API] village_data 字段长度: {len(request.village_data)} 字符")

    # Web environment: Always disable interactive review
    enable_review_effective = False  # Force disable for web environment
    if request.enable_review:
        logger.info("[Planning API] Web environment detected, disabling interactive review")

    state = {
        # User input
        "project_name": request.project_name,
        "village_data": request.village_data,
        "task_description": request.task_description,
        "constraints": request.constraints,

        # Session management
        "session_id": session_id,

        # Flow control
        "current_layer": 1,
        "layer_1_completed": False,
        "layer_2_completed": False,
        "layer_3_completed": False,

        # Review settings
        "need_human_review": enable_review_effective,
        "human_feedback": None,
        "need_revision": False,

        # Layer outputs
        "analysis_report": "",
        "analysis_dimension_reports": {},
        "planning_concept": "",
        "concept_dimension_reports": {},
        "detailed_plan": "",
        "detailed_dimension_reports": {},
        "final_output": "",

        # Output management - use serializable path string
        "output_path": str(output_manager.output_path),

        # Checkpoint configuration
        "checkpoint_enabled": True,
        "last_checkpoint_id": "",

        # Step mode settings
        "step_mode": request.step_mode,
        "step_level": "layer",
        "pause_after_step": request.step_mode,

        # Routing control flags
        "quit_requested": False,
        "trigger_rollback": False,
        "rollback_target": "",

        # Optional fields
        "required_dimensions": None,
        "enable_adapters": False,
        "adapter_config": {},

        # Messages and blackboard
        "messages": [],
        "blackboard": {},

        # Streaming output configuration
        "_streaming_enabled": request.stream_mode,
        "_token_callback_factory": None,
        "_pending_tokens": [],
    }

    logger.info(f"[Planning API] LangGraph 状态构建完成，流式输出模式: {request.stream_mode}")
    return state


# ============================================
# API Endpoints
# ============================================

@router.post("/api/planning/start")
async def start_planning(request: StartPlanningRequest):
    """
    Start a new planning session

    Creates a new session and initializes the main graph.
    Returns session_id immediately for SSE streaming.
    """
    try:
        logger.info(f"[Planning API] 收到规划请求: {request.project_name}")
        logger.info(f"[Planning API] 村庄数据长度: {len(request.village_data)} 字符")

        # ===== Rate limit check =====
        allowed, message = rate_limiter.check_rate_limit(
            project_name=request.project_name,
            session_id=""  # session_id not yet generated
        )

        if not allowed:
            logger.warning(f"[Planning API] 限流触发: {message}")

            # Calculate retry-after time if available
            retry_after = rate_limiter.get_retry_after(request.project_name)

            raise HTTPException(
                status_code=429,  # 429 Too Many Requests
                detail=message,
                headers={"Retry-After": str(retry_after)} if retry_after is not None else {}
            )
        # ===== Rate limit check end =====

        # Defensive check: Detect if village_data equals task_description
        if request.village_data == request.task_description:
            logger.warning(
                f"[Planning API] ⚠️ 警告：village_data 与 task_description 完全相同！"
                "这通常表明用户未上传文件"
            )

        # Validate input
        if not request.project_name or not request.project_name.strip():
            raise HTTPException(status_code=400, detail="项目名称不能为空")

        if not request.village_data or len(request.village_data.strip()) < 10:
            logger.error(f"[Planning API] 村庄数据验证失败: 长度={len(request.village_data) if request.village_data else 0}")
            raise HTTPException(status_code=400, detail="村庄数据不能为空或过短（至少需要10个字符）")

        session_id = _generate_session_id()
        logger.info(f"[Planning API] Starting session {session_id} for {request.project_name}")

        # Mark task as started
        rate_limiter.mark_task_started(request.project_name)

        # Initialize session
        _sessions[session_id] = {
            "session_id": session_id,
            "project_name": request.project_name,
            "status": TaskStatus.pending,
            "created_at": datetime.now().isoformat(),
            "request": request.dict(),
            "current_layer": 1,
        }

        # Build and store initial state
        initial_state = _build_initial_state(request, session_id)
        _sessions[session_id]["initial_state"] = initial_state
        _sessions[session_id]["status"] = TaskStatus.running

        # Initialize execution flag
        _active_executions[session_id] = False

        # ===== NEW: Create graph and start background execution =====
        from langgraph.checkpoint.memory import MemorySaver
        checkpointer = MemorySaver()
        _session_checkpointer[session_id] = checkpointer

        graph = create_village_planning_graph(checkpointer=checkpointer)

        # Start background execution immediately
        await background_task_manager.start_execution(
            session_id=session_id,
            graph=graph,
            initial_state=initial_state,
            checkpointer=checkpointer,
            enable_streaming=request.stream_mode
        )
        logger.info(f"[Planning API] Background execution started for {session_id}")
        # ===== Background execution started =====

        return {
            "task_id": session_id,
            "status": TaskStatus.running,
            "message": "Planning session started",
            "stream_url": f"/api/planning/stream/{session_id}"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[Planning API] Failed to start planning: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to start planning: {str(e)}")


@router.get("/api/planning/stream/{session_id}")
async def stream_planning(session_id: str):
    """
    SSE stream for planning progress

    Consumes events from background task queue.

    Event Types:
    - layer_started: Layer execution started
    - layer_completed: Layer finished successfully
    - checkpoint_saved: Checkpoint created
    - pause: Execution paused (step mode or review)
    - resumed: Execution resumed after review
    - progress: Progress update
    - completed: Planning finished
    - error: Execution error
    """
    try:
        if session_id not in _sessions:
            raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

        # Check background task status
        task_status = background_task_manager.get_task_status(session_id)
        if task_status == "unknown":
            raise HTTPException(
                status_code=400,
                detail="Background task not found. Session may not be properly initialized."
            )

        logger.info(f"[Planning API] Starting SSE stream for {session_id} (background status: {task_status})")

        async def event_generator():
            """Consume events from background task queue"""
            try:
                while True:
                    # Check task status
                    status = background_task_manager.get_task_status(session_id)

                    # Get next event (with timeout)
                    event = await background_task_manager.get_event(session_id, timeout=2.0)

                    if event:
                        yield event

                        # Check if task completed
                        if '"completed"' in event or '"error"' in event:
                            logger.info(f"[Planning API] Task {session_id} finished")
                            _stream_states[session_id] = "completed"
                            break
                    else:
                        # No event received
                        if status == "completed":
                            yield _format_sse_event("completed", {
                                "session_id": session_id,
                                "success": True
                            })
                            _stream_states[session_id] = "completed"
                            break
                        elif status == "failed":
                            yield _format_sse_event("error", {
                                "session_id": session_id,
                                "error": "Background task failed"
                            })
                            _stream_states[session_id] = "completed"
                            break
                        # Continue waiting for running tasks

            except Exception as e:
                logger.error(f"[Planning API] Stream error: {e}", exc_info=True)
                yield _format_sse_event("error", {
                    "session_id": session_id,
                    "error": str(e)
                })

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no"
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[Planning API] Stream error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Stream error: {str(e)}")


@router.post("/api/planning/review/{session_id}")
async def review_action(session_id: str, request: ReviewActionRequest):
    """
    Handle review actions from web frontend

    Actions:
    - approve: Continue execution
    - reject: Submit feedback and trigger revision
    - rollback: Rollback to checkpoint
    """
    try:
        if session_id not in _sessions:
            raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

        session = _sessions[session_id]
        initial_state = session.get("initial_state", {})
        review_id = initial_state.get("review_id", "")

        # 支持两种暂停模式：Step Mode (pause_after_step) 和 Review Mode (waiting_for_review)
        is_pause_mode = initial_state.get("pause_after_step", False)
        is_review_mode = initial_state.get("waiting_for_review", False)

        if not review_id and not is_pause_mode and request.action != "rollback":
            raise HTTPException(status_code=400, detail="No pending review or pause")

        from src.tools.web_review_tool import WebReviewTool
        web_review_tool = WebReviewTool()

        if request.action == "approve":
            # 重置流状态为 active
            _stream_states[session_id] = "active"
            logger.info(f"[Planning API] Stream state reset to 'active' for session {session_id}")

            # 清除两种暂停标志
            initial_state["waiting_for_review"] = False
            initial_state["pause_after_step"] = False
            initial_state["human_feedback"] = ""
            initial_state["__interrupt__"] = False  # Clear interruption flag
            session["status"] = TaskStatus.running

            # Log which mode is being approved
            if is_pause_mode:
                logger.info(f"[Planning API] Approving in step mode (pause_after_step=True)")
            elif is_review_mode:
                logger.info(f"[Planning API] Approving in review mode (waiting_for_review=True)")

            if review_id:
                web_review_tool.submit_review_decision(review_id=review_id, action="approve")

            logger.info(f"[Planning API] Review approved, resuming session {session_id}")

            # NEW: Trigger graph re-invocation
            return await _resume_graph_execution(session_id, initial_state)

        elif request.action == "reject":
            initial_state["waiting_for_review"] = False
            initial_state["pause_after_step"] = False
            initial_state["human_feedback"] = request.feedback
            initial_state["need_revision"] = True
            initial_state["revision_target_dimensions"] = request.dimensions
            initial_state["__interrupt__"] = False  # Clear interruption flag
            session["status"] = TaskStatus.revising

            if review_id:
                web_review_tool.submit_review_decision(
                    review_id=review_id,
                    action="reject",
                    feedback=request.feedback,
                    target_dimensions=request.dimensions
                )

            logger.info(f"[Planning API] Review rejected with feedback, session {session_id}")

            # Trigger graph re-invocation for revision
            return await _resume_graph_execution(session_id, initial_state)

        elif request.action == "rollback":
            if not request.checkpoint_id:
                raise HTTPException(status_code=400, detail="Checkpoint ID required for rollback")

            project_name = session.get("project_name", "")
            checkpoint_tool = tool_manager.get_checkpoint_tool(project_name)
            rollback_result = checkpoint_tool.rollback(
                checkpoint_id=request.checkpoint_id,
                current_output_dir=None
            )

            if not rollback_result.get("success"):
                raise HTTPException(
                    status_code=400,
                    detail=f"Rollback failed: {rollback_result.get('error', 'Unknown error')}"
                )

            if review_id:
                web_review_tool.submit_review_decision(
                    review_id=review_id,
                    action="rollback",
                    checkpoint_id=request.checkpoint_id
                )

            state = rollback_result.get("state", {})
            initial_state.update(state)
            session["current_layer"] = state.get("current_layer", 1)
            session["status"] = TaskStatus.paused

            logger.info(f"[Planning API] Rolling back session {session_id}")

            return {
                "message": f"Rolling back to checkpoint {request.checkpoint_id}",
                "resumed": True
            }

        else:
            raise HTTPException(status_code=400, detail=f"Invalid action: {request.action}")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[Planning API] Review action error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Review action failed: {str(e)}")


@router.get("/api/planning/status/{session_id}", response_model=SessionStatusResponse)
async def get_status(session_id: str):
    """
    Get session status

    Returns current status, progress, and checkpoint information.
    """
    try:
        if session_id not in _sessions:
            raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

        session = _sessions[session_id]
        project_name = session.get("project_name", "")

        # Get checkpoints
        checkpoints = []
        if project_name:
            try:
                checkpoint_tool = tool_manager.get_checkpoint_tool(project_name)
                list_result = checkpoint_tool.list(include_all=True)
                if list_result.get("success"):
                    checkpoints = list_result.get("checkpoints", [])
            except Exception as e:
                logger.warning(f"Failed to load checkpoints: {e}")

        current_layer = session.get("current_layer")
        progress = calculate_progress(current_layer)

        return SessionStatusResponse(
            session_id=session_id,
            status=session.get("status", TaskStatus.pending),
            current_layer=current_layer,
            created_at=session.get("created_at", ""),
            checkpoints=checkpoints,
            checkpoint_count=len(checkpoints),
            progress=progress
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[Planning API] Status error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Status fetch failed: {str(e)}")


@router.delete("/api/planning/sessions/{session_id}")
async def delete_session(session_id: str):
    """
    Delete a session

    Removes session from memory and cleans up checkpointer and background tasks.
    Checkpoint data is preserved by default.
    """
    try:
        if session_id not in _sessions:
            raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

        del _sessions[session_id]

        # Clean up checkpointer
        if session_id in _session_checkpointer:
            del _session_checkpointer[session_id]
            logger.info(f"[Planning API] Cleaned up checkpointer for session {session_id}")

        # Clean up background task
        background_task_manager.cleanup(session_id)

        logger.info(f"[Planning API] Session {session_id} deleted")

        return {"message": f"Session {session_id} deleted"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[Planning API] Delete session error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to delete session: {str(e)}")


@router.post("/api/planning/resume")
async def resume_from_checkpoint(request: ResumeRequest):
    """
    Resume execution from checkpoint

    Loads checkpoint state and creates new session for continued execution.
    """
    try:
        session_id = _generate_session_id()
        logger.info(f"[Planning API] Resuming from checkpoint {request.checkpoint_id}")

        checkpoint_tool = tool_manager.get_checkpoint_tool(request.project_name)
        load_result = checkpoint_tool.load(request.checkpoint_id)

        if not load_result.get("success"):
            raise HTTPException(
                status_code=404,
                detail=f"Checkpoint not found: {request.checkpoint_id}"
            )

        state = load_result.get("state", {})
        metadata = load_result.get("metadata", {})

        _sessions[session_id] = {
            "session_id": session_id,
            "project_name": request.project_name,
            "status": TaskStatus.running,
            "created_at": datetime.now().isoformat(),
            "resumed_from": request.checkpoint_id,
            "current_layer": metadata.get("layer", 1),
            "initial_state": state,
        }

        return {
            "session_id": session_id,
            "status": TaskStatus.running,
            "message": f"Resumed from Layer {metadata.get('layer', 1)}",
            "stream_url": f"/api/planning/stream/{session_id}",
            "current_layer": metadata.get("layer", 1)
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[Planning API] Resume error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Resume failed: {str(e)}")


@router.get("/api/planning/checkpoints/{project_name}")
async def list_checkpoints(project_name: str):
    """
    List all checkpoints for a project
    """
    try:
        checkpoint_tool = tool_manager.get_checkpoint_tool(project_name)
        list_result = checkpoint_tool.list(include_all=True)

        if not list_result.get("success"):
            return {
                "project_name": project_name,
                "checkpoints": [],
                "error": list_result.get("error", "Unknown error"),
                "count": 0
            }

        return {
            "project_name": project_name,
            "checkpoints": list_result.get("checkpoints", []),
            "count": list_result.get("count", 0)
        }

    except Exception as e:
        logger.error(f"[Planning API] List checkpoints error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to list checkpoints: {str(e)}")


# ============================================
# Management Endpoints (for monitoring)
# ============================================

@router.get("/api/planning/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "active_sessions": len(_sessions),
        "timestamp": datetime.now().isoformat()
    }


@router.get("/api/planning/sessions")
async def list_sessions():
    """List all active sessions (for debugging)"""
    return {
        "sessions": list(_sessions.keys()),
        "count": len(_sessions)
    }


@router.get("/api/planning/rate-limit/status")
async def get_rate_limit_status():
    """Get rate limit status (for monitoring)"""
    return rate_limiter.get_status()


@router.post("/api/planning/rate-limit/reset/{project_name}")
async def reset_rate_limit(project_name: str):
    """Reset rate limit status for a project (admin function)"""
    success = rate_limiter.reset_project(project_name)
    if success:
        return {"message": f"已重置项目 '{project_name}' 的限流状态"}
    else:
        raise HTTPException(status_code=404, detail=f"项目不存在: {project_name}")


# ============================================
# Legacy Compatibility Layer
# ============================================

@router.post("/api/tasks")
async def create_task_legacy(request: StartPlanningRequest):
    """Legacy task creation endpoint (maps to start_planning)"""
    result = await start_planning(request)
    return {
        "task_id": result["task_id"],
        "status": result["status"],
        "message": result["message"]
    }


@router.get("/api/tasks/{task_id}/stream")
async def stream_task_legacy(task_id: str):
    """Legacy task streaming endpoint (maps to stream_planning)"""
    return await stream_planning(task_id)


__all__ = ["router"]
