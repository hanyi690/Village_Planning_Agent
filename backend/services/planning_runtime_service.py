"""
Planning Runtime Service - Unified Planning Runtime

Merges GraphRuntimeService + PlanningService into a single unified service.
Provides both LangGraph runtime operations and planning business logic.

Architecture:
    API Layer → PlanningRuntimeService → LangGraph StateGraph
                  ↓
                  SSEManager (event publishing)

Key benefits:
- Single entry point for all planning operations
- Eliminates redundant call chain (PlanningService → GraphRuntimeService)
- Cleaner separation between API layer and business logic
"""

import asyncio
import logging
import time
import uuid
from collections import deque
from datetime import datetime
from typing import Any, Dict, Optional, List

from fastapi import BackgroundTasks, HTTPException
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import StateGraph

from backend.database.engine import get_global_checkpointer
from backend.database.operations_async import (
    create_planning_session_async,
    update_planning_session_async,
    set_stream_state_async,
    add_session_event_async,
)
from backend.schemas import TaskStatus
from backend.services.sse_manager import sse_manager
from backend.services.checkpoint_service import checkpoint_service, checkpoint_persistence_manager
from backend.constants import MAX_SESSION_EVENTS
from src.orchestration.main_graph import create_unified_planning_graph
from src.orchestration.state import (
    get_layer_dimensions,
    get_layer_name,
    _phase_to_layer,
    state_to_ui_status,
)
from src.utils.sse_publisher import SSEPublisher
from src.utils.event_factory import (
    create_completed_event,
    create_error_event,
    create_layer_started_event,
    create_checkpoint_saved_event,
)

logger = logging.getLogger(__name__)


class PlanningRuntimeService:
    """
    Unified Planning Runtime Service - LangGraph + Business Logic.

    Combines:
    - LangGraph operations (initialize, astream, aget_state, aupdate_state)
    - Session management (start, resume, subscribe)
    - Event handling (background execution, SSE publishing)

    Uses singleton pattern for graph/checkpointer instances.
    """

    # LangGraph runtime state (singleton)
    _instance: Optional["PlanningRuntimeService"] = None
    _checkpointer: Optional[BaseCheckpointSaver] = None
    _graph: Optional[StateGraph] = None
    _initialized: bool = False
    _lock: Optional[asyncio.Lock] = None

    # ==========================================
    # LangGraph Runtime Operations
    # ==========================================

    @classmethod
    async def initialize(cls, event_loop: asyncio.AbstractEventLoop = None) -> None:
        """
        Initialize the runtime service at application startup.

        Should be called once during application lifespan.
        """
        if cls._initialized and cls._graph is not None:
            logger.info("[PlanningRuntimeService] Already initialized, skipping")
            return

        if cls._lock is None:
            cls._lock = asyncio.Lock()

        async with cls._lock:
            if cls._initialized and cls._graph is not None:
                return

            logger.info("[PlanningRuntimeService] Initializing...")

            cls._checkpointer = await get_global_checkpointer()
            logger.info("[PlanningRuntimeService] Checkpointer acquired")

            cls._graph = create_unified_planning_graph(checkpointer=cls._checkpointer)
            logger.info("[PlanningRuntimeService] Graph created")

            cls._initialized = True
            logger.info("[PlanningRuntimeService] Initialization complete")

    @classmethod
    async def ensure_initialized(cls) -> None:
        """Ensure the service is initialized (lazy initialization)."""
        if not cls._initialized or cls._graph is None:
            await cls.initialize()

    @classmethod
    def get_thread_config(cls, session_id: str) -> Dict[str, Any]:
        """Build thread_id configuration for LangGraph operations."""
        return {"configurable": {"thread_id": session_id}}

    @classmethod
    async def astream(
        cls,
        session_id: str,
        input_state: Optional[Dict[str, Any]] = None,
        stream_mode: str = "values"
    ):
        """Stream execution for planning workflow."""
        await cls.ensure_initialized()
        config = cls.get_thread_config(session_id)
        return cls._graph.astream(input_state, config, stream_mode=stream_mode)

    @classmethod
    async def astream_events(
        cls,
        session_id: str,
        input_state: Dict[str, Any],
        version: str = "v2"
    ):
        """Event stream execution for conversation mode."""
        await cls.ensure_initialized()
        config = cls.get_thread_config(session_id)
        return cls._graph.astream_events(input_state, config, version=version)

    @classmethod
    async def aget_state(cls, session_id: str) -> Optional[Any]:
        """Get checkpoint state snapshot for a session."""
        await cls.ensure_initialized()
        config = cls.get_thread_config(session_id)
        return await cls._graph.aget_state(config)

    @classmethod
    async def aget_state_values(cls, session_id: str) -> Optional[Dict[str, Any]]:
        """Get checkpoint state values (convenience method)."""
        snapshot = await cls.aget_state(session_id)
        if snapshot and snapshot.values:
            return dict(snapshot.values)
        return None

    @classmethod
    async def aupdate_state(
        cls,
        session_id: str,
        updates: Dict[str, Any],
        as_node: Optional[str] = None
    ) -> bool:
        """Update checkpoint state for a session."""
        await cls.ensure_initialized()
        config = cls.get_thread_config(session_id)
        await cls._graph.aupdate_state(config, updates, as_node=as_node)
        return True

    @classmethod
    async def aget_state_history(cls, session_id: str):
        """Get checkpoint history iterator for a session.

        Yields state snapshots from the graph's checkpoint history.
        """
        await cls.ensure_initialized()
        config = cls.get_thread_config(session_id)
        async for snapshot in cls._graph.aget_state_history(config):
            yield snapshot

    @classmethod
    def get_checkpointer(cls) -> Optional[BaseCheckpointSaver]:
        """Get the checkpointer instance."""
        return cls._checkpointer

    @classmethod
    def get_graph(cls) -> Optional[StateGraph]:
        """Get the graph instance."""
        return cls._graph

    @classmethod
    def is_initialized(cls) -> bool:
        """Check if the service is initialized."""
        return cls._initialized and cls._graph is not None

    # ==========================================
    # Session Management Operations
    # ==========================================

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
        village_name: str = "",
        enable_review: bool = False,
        stream_mode: bool = True,
        step_mode: bool = False,
        images: Optional[List] = None,
    ) -> Dict[str, Any]:
        """Build initial state for main graph execution."""
        # Convert images to dict format for serialization
        images_data = []
        if images:
            for img in images:
                if hasattr(img, 'model_dump'):
                    images_data.append(img.model_dump())
                elif hasattr(img, 'dict'):
                    images_data.append(img.dict())
                else:
                    images_data.append(img)

        state = {
            "messages": [],  # Will be set by _trigger_planning_execution
            "session_id": session_id,
            "project_name": project_name,
            "config": {
                "village_data": village_data,
                "village_name": village_name or project_name,
                "task_description": task_description,
                "constraints": constraints,
                "knowledge_cache": {},
                # images 移至顶层，不再放在 config 内部
            },
            "images": images_data,  # 图片作为顶层属性，仅 Layer 1 使用
            "phase": "init",
            "current_wave": 1,
            "reports": {"layer1": {}, "layer2": {}, "layer3": {}},
            "completed_dimensions": {"layer1": [], "layer2": [], "layer3": []},
            "dimension_results": [],
            "sse_events": [],
            "pending_review": False,
            "need_revision": False,
            "revision_target_dimensions": [],
            "human_feedback": "",
            "metadata": {
                "published_layers": [],
                "version": 0,
                "last_signal_timestamp": None,
            },
            "_streaming_enabled": stream_mode,
            "step_mode": step_mode,
        }
        logger.info(f"[PlanningRuntimeService] Initial state built for session {session_id}")
        return state

    @classmethod
    async def start_session(
        cls,
        project_name: str,
        village_data: str,
        village_name: str = "",
        task_description: str = "",
        constraints: str = "",
        enable_review: bool = False,
        stream_mode: bool = True,
        step_mode: bool = False,
        background_tasks: BackgroundTasks = None,
        rate_limiter=None,
        images: Optional[List] = None,
    ) -> Dict[str, Any]:
        """
        Start a new planning session.

        Args:
            project_name: Project/village name
            village_data: Village input data
            village_name: Village name for prompt constraints
            task_description: Task description
            constraints: Planning constraints
            enable_review: Enable interactive review
            stream_mode: Enable streaming output
            step_mode: Enable step-by-step execution
            background_tasks: FastAPI BackgroundTasks
            rate_limiter: Optional rate limiter instance
            images: Optional list of uploaded images for multimodal analysis

        Returns:
            Dict with session details
        """
        start_time = time.time()

        # Rate limit check
        if rate_limiter:
            allowed, message = rate_limiter.check_rate_limit(
                project_name=project_name,
                session_id=""
            )
            if not allowed:
                retry_after = rate_limiter.get_retry_after(project_name)
                raise HTTPException(
                    status_code=429,
                    detail=message,
                    headers={"Retry-After": str(retry_after)} if retry_after else {}
                )

        # Generate session ID
        session_id = cls.generate_session_id()
        logger.info(f"[PlanningRuntimeService] Generated session ID: {session_id}")

        if rate_limiter:
            rate_limiter.mark_task_started(project_name)

        # Build initial state
        initial_state = cls.build_initial_state(
            project_name=project_name,
            village_data=village_data,
            village_name=village_name,
            task_description=task_description,
            constraints=constraints,
            session_id=session_id,
            enable_review=enable_review,
            stream_mode=stream_mode,
            step_mode=step_mode,
            images=images,
        )

        # Create session state for database
        session_state = {
            "session_id": session_id,
            "project_name": project_name,
            "status": TaskStatus.running,
            "created_at": datetime.now().isoformat(),
            "request": {
                "project_name": project_name,
                "village_data": village_data,
                "village_name": village_name,
                "task_description": task_description,
                "constraints": constraints,
            },
        }

        # Create database session
        try:
            await create_planning_session_async(session_state)
            logger.info(f"[PlanningRuntimeService] [{session_id}] Database session created")
        except Exception as db_error:
            logger.error(f"[PlanningRuntimeService] [{session_id}] DB creation failed: {db_error}")
            if rate_limiter:
                rate_limiter.mark_task_completed(project_name, success=False)
            raise HTTPException(
                status_code=500,
                detail=f"Failed to create session in database: {db_error}"
            )

        # Initialize SSE manager session
        sse_manager.init_session(session_id, {
            "session_id": session_id,
            "project_name": project_name,
            "created_at": datetime.now().isoformat(),
            "events": deque(maxlen=MAX_SESSION_EVENTS),
        })
        sse_manager.set_execution_active(session_id, True)

        # Ensure graph is initialized
        await cls.ensure_initialized()

        # Send Layer 1 layer_started event
        SSEPublisher.send_layer_start(
            session_id=session_id,
            layer=1,
            layer_name=get_layer_name(1),
            dimension_count=len(get_layer_dimensions(1))
        )
        logger.info(f"[PlanningRuntimeService] [{session_id}] Sent layer_started for Layer 1")

        # Start background execution
        background_tasks.add_task(
            cls._trigger_planning_execution,
            session_id,
            initial_state,
        )

        elapsed = (time.time() - start_time) * 1000
        logger.info(f"[PlanningRuntimeService] [{session_id}] Session started ({elapsed:.2f}ms)")

        return {
            "task_id": session_id,
            "status": TaskStatus.running,
            "message": "Planning session started",
            "stream_url": f"/api/planning/stream/{session_id}"
        }

    @classmethod
    async def get_session_status(cls, session_id: str) -> Dict[str, Any]:
        """
        Get session status using state_to_ui_status.

        Args:
            session_id: Session identifier

        Returns:
            UI-ready status dictionary
        """
        from backend.database.operations_async import get_planning_session_async, get_ui_messages_async

        db_session = await get_planning_session_async(session_id)
        if not db_session:
            raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

        checkpoint_state = await cls.aget_state(session_id)
        state = dict(checkpoint_state.values) if checkpoint_state and checkpoint_state.values else {}

        ui_status = state_to_ui_status(state, db_session)
        ui_status["session_id"] = session_id

        # Extract messages
        messages = []
        raw_messages = state.get("messages", [])
        for msg in raw_messages:
            if hasattr(msg, "content"):
                messages.append({
                    "type": msg.__class__.__name__.lower().replace("message", ""),
                    "content": msg.content,
                    "role": "assistant" if "ai" in msg.__class__.__name__.lower() else "user"
                })
        ui_status["messages"] = messages
        ui_status["ui_messages"] = await get_ui_messages_async(session_id)
        ui_status["revision_history"] = state.get("revision_history", [])
        ui_status["last_checkpoint_id"] = checkpoint_state.config.get("configurable", {}).get("checkpoint_id", "") if checkpoint_state else ""

        return ui_status

    # ==========================================
    # Background Execution & Event Handling
    # ==========================================

    @staticmethod
    async def _append_event(session_id: str, event: Dict) -> bool:
        """Append event to database and SSE manager."""
        try:
            await add_session_event_async(session_id, event)
            sse_manager.append_event(session_id, event)
            sse_manager.publish_sync(session_id, event)
            return True
        except Exception as e:
            logger.warning(f"[PlanningRuntimeService] [{session_id}] DB event append failed: {e}")
            sse_manager.append_event(session_id, event)
            sse_manager.publish_sync(session_id, event)
            return False

    @classmethod
    async def _trigger_planning_execution(
        cls,
        session_id: str,
        initial_state: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Unified trigger for planning execution (skip conversation_node).

        Used for Layer 1 start and Layer 2/3 resume, unified execution entry.

        Args:
            session_id: Session identifier
            initial_state: Optional initial state (only for Layer 1 start)
        """
        await cls.ensure_initialized()

        # Wait for SSE subscriber to connect before starting execution
        # This prevents early dimension_delta events from being lost
        # Reduced timeout for script mode efficiency (1s instead of 5s)
        subscriber_ready = await sse_manager.wait_for_subscriber(session_id, timeout=1.0)
        if not subscriber_ready:
            logger.debug(f"[PlanningRuntimeService] [{session_id}] No SSE subscriber (script mode), proceeding immediately")

        # 1. If initial_state (Layer 1 new session), create checkpoint first
        if initial_state:
            # Remove messages, we don't trigger through LLM
            clean_state = {k: v for k, v in initial_state.items() if k != "messages"}
            await cls.aupdate_state(session_id, clean_state)
            logger.info(f"[PlanningRuntimeService] [{session_id}] Initial checkpoint created")

        # 2. Create synthetic AIMessage with AdvancePlanningIntent tool call
        synthetic_ai_message = AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "AdvancePlanningIntent",
                    "id": f"call_{session_id[:8]}",
                    "args": {}
                }
            ]
        )

        # 3. Use as_node="conversation" to skip conversation_node
        await cls.aupdate_state(
            session_id,
            {"messages": [synthetic_ai_message]},
            as_node="conversation"
        )
        logger.info(f"[PlanningRuntimeService] [{session_id}] Synthetic AIMessage added as conversation output")

        # 4. Build config with optional streaming callback
        config = cls.get_thread_config(session_id)

        streaming_enabled = (initial_state.get("_streaming_enabled", True) if initial_state else True)
        if streaming_enabled:
            def token_callback_factory(layer: int, dimension: str):
                def on_token(token: str, accumulated: str):
                    event_data = {
                        "type": "dimension_delta",
                        "layer": layer,
                        "dimension_key": dimension,
                        "delta": token,
                        "timestamp": datetime.now().isoformat()
                    }
                    sse_manager.append_event(session_id, event_data)
                    sse_manager.publish_sync(session_id, event_data)
                return on_token
            config["configurable"]["_token_callback_factory"] = token_callback_factory

        # 5. Resume from checkpoint, go directly to intent_router -> route_planning
        logger.info(f"[PlanningRuntimeService] [{session_id}] Background execution started")

        # Track last completed layer from values mode
        # This is used to correlate checkpoint_saved events with the correct layer
        last_completed_layer = 0
        last_phase = ""
        is_revision = False
        revision_dimensions = []

        try:
            # Use dual stream mode: 'values' for state updates, 'checkpoints' for checkpoint persistence
            stream_iterator = cls._graph.astream(None, config, stream_mode=['values', 'checkpoints'])

            async for event in stream_iterator:
                if isinstance(event, tuple) and len(event) == 2:
                    mode, data = event

                    if mode == 'values':
                        # From values mode: detect layer completion by checking pause_after_step
                        state = data
                        if state.get('pause_after_step') and state.get('previous_layer'):
                            layer = state.get('previous_layer', 0)
                            if layer > 0:
                                last_completed_layer = layer
                                last_phase = state.get('phase', '')

                                # Detect if this is a revision completion
                                last_revised_dimensions = state.get('last_revised_dimensions', [])
                                if last_revised_dimensions:
                                    is_revision = True
                                    revision_dimensions = last_revised_dimensions
                                else:
                                    is_revision = False
                                    revision_dimensions = []

                                logger.info(f"[PlanningRuntimeService] [{session_id}] {'Revision' if is_revision else 'Layer'} {layer} completed")

                    elif mode == 'checkpoints':
                        # From checkpoints mode: checkpoint persisted, now send checkpoint_saved event
                        checkpoint_id = None
                        if hasattr(data, 'config'):
                            checkpoint_id = data.config.get('configurable', {}).get('checkpoint_id', '')
                        elif isinstance(data, dict):
                            checkpoint_id = data.get('config', {}).get('configurable', {}).get('checkpoint_id', '')

                        # Mark checkpoint write complete for synchronization
                        await checkpoint_persistence_manager.mark_write_complete(session_id)

                        if last_completed_layer > 0 and checkpoint_id:
                            logger.info(f"[PlanningRuntimeService] [{session_id}] checkpoints mode: checkpoint_id={checkpoint_id} for {'Revision' if is_revision else 'Layer'} {last_completed_layer}")

                            # Build event using factory function
                            checkpoint_saved_event = create_checkpoint_saved_event(
                                checkpoint_id=checkpoint_id,
                                layer=last_completed_layer,
                                phase=last_phase,
                                session_id=session_id,
                                is_revision=is_revision,
                                revised_dimensions=revision_dimensions,
                            )

                            sse_manager.append_event(session_id, checkpoint_saved_event)
                            sse_manager.publish_sync(session_id, checkpoint_saved_event)

                            # Reset tracking for next layer
                            last_completed_layer = 0
                            last_phase = ""
                            is_revision = False
                            revision_dimensions = []

                else:
                    # Legacy single-mode handling (if stream_mode=['values'] only)
                    # This branch handles the case where event is not a tuple
                    pass

            # Send completed event
            await cls._append_event(session_id, create_completed_event(session_id))
            sse_manager.set_execution_active(session_id, False)

            logger.info(f"[PlanningRuntimeService] [{session_id}] Background execution completed")

        except Exception as e:
            logger.error(f"[PlanningRuntimeService] [{session_id}] Execution failed: {e}", exc_info=True)
            await cls._append_event(session_id, create_error_event(session_id, str(e)))
            sse_manager.set_execution_active(session_id, False)

    @classmethod
    async def resume_execution(cls, session_id: str) -> Dict[str, Any]:
        """
        Resume graph execution from checkpoint.

        Args:
            session_id: Session identifier

        Returns:
            Response dict with stream URL
        """
        await cls.ensure_initialized()

        full_state = await checkpoint_service.validate_session(session_id)
        phase = full_state.get("phase", "init")
        current_layer = _phase_to_layer(phase) or 1

        logger.info(f"[PlanningRuntimeService] [{session_id}] Resuming from checkpoint: phase={phase}")

        # Send resumed event (create once, use twice)
        resumed_event = {
            "type": "resumed",
            "session_id": session_id,
            "current_layer": current_layer,
            "message": "Execution resumed after review approval",
            "timestamp": datetime.now().isoformat()
        }
        sse_manager.append_event(session_id, resumed_event)
        sse_manager.publish_sync(session_id, resumed_event)

        # Update database status
        await update_planning_session_async(session_id, {
            "status": TaskStatus.running,
            "execution_error": None,
        })

        # Clear pause flags
        if full_state.get("pause_after_step", False):
            await checkpoint_service.clear_pause_flags(session_id)

        # Send layer_started event
        need_revision = full_state.get("need_revision", False)
        logger.debug(f"[PlanningRuntimeService] [{session_id}] resume: phase={phase}, current_layer={current_layer}, need_revision={need_revision}")
        if current_layer in [1, 2, 3] and not need_revision:
            logger.info(f"[PlanningRuntimeService] [{session_id}] Sending layer_started for Layer {current_layer}")
            SSEPublisher.send_layer_start(
                session_id=session_id,
                layer=current_layer,
                layer_name=get_layer_name(current_layer),
                dimension_count=len(get_layer_dimensions(current_layer))
            )
        else:
            logger.debug(f"[PlanningRuntimeService] [{session_id}] Skipping layer_started: current_layer={current_layer}, need_revision={need_revision}")

        await set_stream_state_async(session_id, "active")

        # Start background execution
        asyncio.create_task(cls._trigger_planning_execution(session_id))

        return {
            "message": "Execution resumed",
            "session_id": session_id,
            "stream_url": f"/api/planning/stream/{session_id}",
            "current_layer": current_layer,
            "resumed": True
        }

    @classmethod
    async def subscribe_with_history(cls, session_id: str) -> asyncio.Queue:
        """Subscribe to session event stream with historical event sync."""
        queue = await sse_manager.subscribe(session_id)

        historical_events = sse_manager.get_events_copy(session_id)
        layer_completed_found = any(e.get("type") == "layer_completed" for e in historical_events)

        if len(historical_events) == 0 or not layer_completed_found:
            logger.info(f"[PlanningRuntimeService] [{session_id}] Rebuilding from checkpoint")
            rebuilt_events = await checkpoint_service.rebuild_events(session_id)

            if rebuilt_events:
                for event in rebuilt_events:
                    try:
                        queue.put_nowait(event)
                        sse_manager.append_event(session_id, event)
                    except asyncio.QueueFull:
                        logger.warning(f"[PlanningRuntimeService] [{session_id}] Queue full, dropping rebuilt event")
                        break

        return queue


# Singleton instance
planning_runtime_service = PlanningRuntimeService()


__all__ = ["PlanningRuntimeService", "planning_runtime_service"]