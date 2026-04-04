"""
Planning Service - Business Logic for Planning Execution

This service contains the core business logic for planning operations:
- Building initial state
- Starting planning sessions
- Executing graph in background
- Resume from checkpoint
- Review actions (approve/reject)

Phase 5 Refactoring: Complete execution logic migration from planning.py
"""

import asyncio
import logging
import time
import uuid
from collections import deque
from datetime import datetime
from typing import Any, Dict, Optional, Set

from fastapi import BackgroundTasks, HTTPException
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.base import BaseCheckpointSaver

from src.orchestration.main_graph import create_unified_planning_graph
from src.orchestration.state import get_layer_dimensions, get_layer_name, LAYER_NAMES_BY_NUMBER
from backend.schemas import TaskStatus
from backend.services.sse_manager import sse_manager
from backend.services.checkpoint_service import checkpoint_service

logger = logging.getLogger(__name__)

# Configuration
MAX_SESSION_EVENTS = 5000


class StartPlanningRequest:
    """Request model for starting a planning session."""
    def __init__(
        self,
        project_name: str,
        village_data: str,
        task_description: str = "",
        constraints: str = "",
        enable_review: bool = False,
        stream_mode: bool = True,
        step_mode: bool = False,
    ):
        self.project_name = project_name
        self.village_data = village_data
        self.task_description = task_description
        self.constraints = constraints
        self.enable_review = enable_review
        self.stream_mode = stream_mode
        self.step_mode = step_mode


class StartPlanningResponse:
    """Response model for starting a planning session."""
    def __init__(self, session_id: str, stream_url: str):
        self.task_id = session_id
        self.status = TaskStatus.running
        self.message = "Planning session started"
        self.stream_url = stream_url

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "status": self.status,
            "message": self.message,
            "stream_url": self.stream_url
        }


class PlanningService:
    """
    Core planning business logic service.

    Provides:
    - Initial state building
    - Session creation and management
    - Graph execution management
    - Resume from checkpoint
    - Review actions
    """

    @staticmethod
    def generate_session_id() -> str:
        """Generate unique session ID."""
        return str(uuid.uuid4())

    @staticmethod
    def build_initial_state(
        project_name: str,
        village_data: str,
        task_description: str,
        constraints: str,
        session_id: str,
        enable_review: bool = False,
        stream_mode: bool = True,
        step_mode: bool = False,
    ) -> Dict[str, Any]:
        """
        Build initial state for main graph execution.

        Uses NEW UnifiedPlanningState schema.

        Args:
            project_name: Project/village name
            village_data: Village input data
            task_description: Task description
            constraints: Planning constraints
            session_id: Unique session identifier
            enable_review: Enable interactive review (forced False for web)
            stream_mode: Enable streaming output
            step_mode: Enable step-by-step execution

        Returns:
            Complete initial state dictionary
        """
        # Web environment: Always disable interactive review
        enable_review_effective = False
        if enable_review:
            logger.info("[PlanningService] Web environment, disabling interactive review")

        state = {
            # Core driver - messages
            "messages": [HumanMessage(content="请开始规划分析")],

            # Business params
            "session_id": session_id,
            "project_name": project_name,
            "config": {
                "village_data": village_data,
                "task_description": task_description,
                "constraints": constraints,
                "knowledge_cache": {}
            },

            # Execution progress - NEW UnifiedPlanningState Schema
            "phase": "init",
            "current_wave": 1,
            "reports": {"layer1": {}, "layer2": {}, "layer3": {}},
            "completed_dimensions": {"layer1": [], "layer2": [], "layer3": []},
            "dimension_results": [],
            "sse_events": [],

            # Interaction control
            "pending_review": False,
            "need_revision": False,
            "revision_target_dimensions": [],
            "review_feedback": "",

            # Metadata
            "metadata": {
                "published_layers": [],
                "version": 0,
                "last_signal_timestamp": None,
            },

            # Runtime flags (not persisted)
            "_streaming_enabled": stream_mode,
            "step_mode": step_mode,
        }

        logger.info(f"[PlanningService] Initial state built for session {session_id}")
        return state

    @staticmethod
    async def start_planning_session(
        request: StartPlanningRequest,
        background_tasks: BackgroundTasks,
        rate_limiter=None,
    ) -> StartPlanningResponse:
        """
        Start a new planning session.

        Refactored to use direct dependencies instead of callbacks.

        Args:
            request: Planning request with user inputs
            background_tasks: FastAPI BackgroundTasks
            rate_limiter: Optional rate limiter instance

        Returns:
            StartPlanningResponse with session details

        Raises:
            HTTPException: On validation or creation errors
        """
        from backend.database.operations_async import create_planning_session_async

        start_time = time.time()

        # Rate limit check
        if rate_limiter:
            allowed, message = rate_limiter.check_rate_limit(
                project_name=request.project_name,
                session_id=""
            )
            if not allowed:
                retry_after = rate_limiter.get_retry_after(request.project_name)
                raise HTTPException(
                    status_code=429,
                    detail=message,
                    headers={"Retry-After": str(retry_after)} if retry_after else {}
                )

        # Generate session ID
        session_id = PlanningService.generate_session_id()
        logger.info(f"[PlanningService] Generated session ID: {session_id}")

        # Mark task as started
        if rate_limiter:
            rate_limiter.mark_task_started(request.project_name)

        # Build initial state
        initial_state = PlanningService.build_initial_state(
            project_name=request.project_name,
            village_data=request.village_data,
            task_description=request.task_description,
            constraints=request.constraints,
            session_id=session_id,
            enable_review=request.enable_review,
            stream_mode=request.stream_mode,
            step_mode=request.step_mode,
        )

        # Create session state for database
        session_state = {
            "session_id": session_id,
            "project_name": request.project_name,
            "status": TaskStatus.running,
            "created_at": datetime.now().isoformat(),
            "request": {
                "project_name": request.project_name,
                "village_data": request.village_data,
                "task_description": request.task_description,
                "constraints": request.constraints,
            },
        }

        # Create database session directly
        try:
            await create_planning_session_async(session_state)
            logger.info(f"[PlanningService] [{session_id}] Database session created")
        except Exception as db_error:
            logger.error(f"[PlanningService] [{session_id}] DB creation failed: {db_error}")
            if rate_limiter:
                rate_limiter.mark_task_completed(request.project_name, success=False)
            raise HTTPException(
                status_code=500,
                detail=f"Failed to create session in database: {db_error}"
            )

        # Initialize SSE manager session
        sse_manager.get_session_events(session_id)
        sse_manager.init_session(session_id, {
            "session_id": session_id,
            "project_name": request.project_name,
            "created_at": datetime.now().isoformat(),
            "events": deque(maxlen=MAX_SESSION_EVENTS),
        })

        # Set execution active via SSEManager
        sse_manager.set_execution_active(session_id, True)

        # Get checkpointer via checkpoint_service
        checkpointer = await checkpoint_service.get_checkpointer()
        graph = create_unified_planning_graph(checkpointer=checkpointer)

        # Start background execution
        background_tasks.add_task(
            PlanningService.execute_graph_background,
            session_id,
            graph,
            initial_state,
            checkpointer,
            sse_manager.append_event,
            PlanningService._append_event_async_wrapper,
        )

        elapsed = (time.time() - start_time) * 1000
        logger.info(f"[PlanningService] [{session_id}] Session started ({elapsed:.2f}ms)")

        return StartPlanningResponse(
            session_id=session_id,
            stream_url=f"/api/planning/stream/{session_id}"
        )

    @staticmethod
    async def _append_event_async_wrapper(session_id: str, event: Dict) -> bool:
        """Wrapper for async event append (used by execute_graph_background)."""
        from backend.database.operations_async import add_session_event_async
        try:
            success = await add_session_event_async(session_id, event)
            sse_manager.append_event(session_id, event)
            sse_manager.publish_sync(session_id, event)
            return success
        except Exception:
            sse_manager.append_event(session_id, event)
            sse_manager.publish_sync(session_id, event)
            return False

    @staticmethod
    async def execute_graph_background(
        session_id: str,
        graph,
        initial_state: Optional[Dict[str, Any]],
        checkpointer: BaseCheckpointSaver,
        append_event_func,
        append_event_async_func,
    ):
        """
        Execute LangGraph in background and emit SSE events.

        Args:
            session_id: Session identifier
            graph: LangGraph compiled graph
            initial_state: Initial state (None for resume)
            checkpointer: Checkpointer instance
            append_event_func: Sync event append function
            append_event_async_func: Async event append function
        """
        logger.info(f"[PlanningService] [{session_id}] Background execution started")

        try:
            config = {"configurable": {"thread_id": session_id}}

            def token_callback_factory(layer: int, dimension: str):
                def on_token(token: str, accumulated: str):
                    event_data = {
                        "type": "dimension_delta",
                        "layer": layer,
                        "dimension_key": dimension,
                        "delta": token,
                        "timestamp": datetime.now().isoformat()
                    }
                    append_event_func(session_id, event_data)

                return on_token

            streaming_enabled = (initial_state.get("_streaming_enabled", True) if initial_state else True)
            if streaming_enabled:
                config["configurable"]["_token_callback_factory"] = token_callback_factory

            # Runtime keys to exclude from checkpoint
            RUNTIME_KEYS = {
                "_streaming_queue",
                "_storage_pipeline",
                "_dimension_events",
                "_token_callback_factory",
                "_streaming_enabled",
                "_pending_tokens",
            }

            clean_state = {k: v for k, v in (initial_state or {}).items() if k not in RUNTIME_KEYS}

            stream_iterator = graph.astream(clean_state, config, stream_mode="values")

            # Get published layers from checkpoint
            checkpoint_state = await graph.aget_state(config)
            metadata = checkpoint_state.values.get("metadata", {})
            published_layers = set(metadata.get("published_layers", []))
            published_revisions = set(metadata.get("published_revisions", []))

            sent_layer_started_this_run = set()
            sent_pause_this_run = set()

            async for event in stream_iterator:
                current_layer = event.get("current_layer")
                pause_after_step = event.get("pause_after_step", False)
                previous_layer = event.get("previous_layer", 0)
                step_mode = event.get("step_mode", False)

                # Layer started detection
                should_send_started = (
                    current_layer and
                    current_layer in [1, 2, 3] and
                    not pause_after_step and
                    not (step_mode and previous_layer > 0) and
                    current_layer not in published_layers
                )

                if should_send_started:
                    layer_started_key = f"layer_{current_layer}_started"
                    if layer_started_key not in sent_layer_started_this_run:
                        started_event = {
                            "type": "layer_started",
                            "layer": current_layer,
                            "layer_number": current_layer,
                            "layer_name": get_layer_name(current_layer),
                            "session_id": session_id,
                            "message": f"开始执行 Layer {current_layer}",
                            "timestamp": datetime.now().isoformat()
                        }
                        await append_event_async_func(session_id, started_event)
                        sent_layer_started_this_run.add(layer_started_key)

                # Layer completion detection
                reports = event.get("reports", {})
                completed_dims = event.get("completed_dimensions", {})

                for layer_num in [1, 2, 3]:
                    layer_key = f"layer{layer_num}"
                    now_completed = len(completed_dims.get(layer_key, [])) >= len(get_layer_dimensions(layer_num))

                    if now_completed and layer_num not in published_layers:
                        dimension_reports = reports.get(layer_key, {})
                        total_chars = sum(len(v) for v in dimension_reports.values()) if dimension_reports else 0

                        event_data = {
                            "type": "layer_completed",
                            "layer": layer_num,
                            "session_id": session_id,
                            "has_data": len(dimension_reports) > 0,
                            "dimension_count": len(dimension_reports),
                            "total_chars": total_chars,
                            "pause_after_step": event.get("pause_after_step", False),
                            "phase": event.get("phase", "init"),
                            "dimension_reports": dimension_reports,
                            "timestamp": datetime.now().isoformat()
                        }

                        await append_event_async_func(session_id, event_data)

                        published_layers.add(layer_num)
                        current_metadata = event.get("metadata", {})
                        updated_metadata = {
                            **current_metadata,
                            "published_layers": list(published_layers),
                            "version": current_metadata.get("version", 0) + 1,
                            "last_signal_timestamp": datetime.now().isoformat(),
                        }
                        await graph.aupdate_state(config, {"metadata": updated_metadata})

                # Pause detection
                if pause_after_step and previous_layer > 0:
                    pause_key = f"pause_{previous_layer}"
                    if pause_key not in sent_pause_this_run:
                        pause_event = {
                            "type": "pause",
                            "current_layer": previous_layer,
                            "checkpoint_id": checkpoint_state.config.get("configurable", {}).get("thread_id", session_id),
                            "message": f"Layer {previous_layer} completed, waiting for review",
                            "timestamp": datetime.now().isoformat()
                        }
                        await append_event_async_func(session_id, pause_event)
                        sent_pause_this_run.add(pause_key)

            # Execution completed
            completed_event = {
                "type": "completed",
                "session_id": session_id,
                "message": "Planning completed successfully",
                "timestamp": datetime.now().isoformat()
            }
            await append_event_async_func(session_id, completed_event)

            logger.info(f"[PlanningService] [{session_id}] Background execution completed")

        except Exception as e:
            logger.error(f"[PlanningService] [{session_id}] Execution failed: {e}", exc_info=True)

            error_event = {
                "type": "error",
                "session_id": session_id,
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            }
            await append_event_async_func(session_id, error_event)

    @staticmethod
    async def resume_from_checkpoint(
        session_id: str,
        checkpointer: BaseCheckpointSaver,
        append_event_func,
        update_session_func,
        set_stream_state_func,
    ) -> Dict[str, Any]:
        """
        Resume graph execution from checkpoint.

        Args:
            session_id: Session identifier
            checkpointer: Checkpointer instance
            append_event_func: Event append function
            update_session_func: Database update function
            set_stream_state_func: Stream state setter

        Returns:
            Response dict with stream URL
        """
        graph = create_unified_planning_graph(checkpointer=checkpointer)
        config = {"configurable": {"thread_id": session_id}}

        checkpoint_state = await graph.aget_state(config)
        if not checkpoint_state or not checkpoint_state.values:
            raise ValueError(f"Session {session_id} not found in checkpoint")

        full_state = checkpoint_state.values
        current_layer = full_state.get("current_layer", 1)

        logger.info(f"[PlanningService] [{session_id}] Resuming from checkpoint:")
        logger.info(f"[PlanningService] [{session_id}]   phase: {full_state.get('phase', 'init')}")
        completed_dims = full_state.get("completed_dimensions", {})
        l1_count = len(completed_dims.get("layer1", []))
        l2_count = len(completed_dims.get("layer2", []))
        l3_count = len(completed_dims.get("layer3", []))
        logger.info(f"[PlanningService] [{session_id}]   completed: L1={l1_count}, L2={l2_count}, L3={l3_count}")

        # Add resumed event
        append_event_func(session_id, {
            "type": "resumed",
            "session_id": session_id,
            "current_layer": current_layer,
            "message": "Execution resumed after review approval",
            "timestamp": datetime.now().isoformat()
        })

        # Update database status
        try:
            await update_session_func(session_id, {
                "status": TaskStatus.running,
                "execution_error": None,
            })
            logger.info(f"[PlanningService] [{session_id}] Status persisted to database: running")
        except Exception as db_error:
            logger.error(f"[PlanningService] [{session_id}] DB update failed: {db_error}")

        # Clear pause flags
        if full_state.get("pause_after_step", False):
            await graph.aupdate_state(config, {
                "pause_after_step": False,
                "previous_layer": 0,
            })
            logger.info(f"[PlanningService] [{session_id}] Cleared pause_after_step flag")

        # Send layer_started event if valid layer
        need_revision = full_state.get("need_revision", False)
        if current_layer in [1, 2, 3] and not need_revision:
            started_event = {
                "type": "layer_started",
                "layer": current_layer,
                "layer_number": current_layer,
                "layer_name": get_layer_name(current_layer),
                "session_id": session_id,
                "message": f"开始执行 Layer {current_layer}: {get_layer_name(current_layer)}",
                "timestamp": datetime.now().isoformat()
            }
            append_event_func(session_id, started_event)
            logger.info(f"[PlanningService] [{session_id}] Sent layer_started event: Layer {current_layer}")
        elif need_revision:
            logger.info(f"[PlanningService] [{session_id}] need_revision=True, skipping layer_started event")

        await set_stream_state_func(session_id, "active")

        return {
            "message": "Execution resumed",
            "session_id": session_id,
            "stream_url": f"/api/planning/stream/{session_id}",
            "current_layer": current_layer,
            "resumed": True
        }


# Singleton instance
planning_service = PlanningService()


__all__ = ["PlanningService", "planning_service"]