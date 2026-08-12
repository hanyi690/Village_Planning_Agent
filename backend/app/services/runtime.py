"""
Planning Runtime Service - Unified Planning Runtime

Merges GraphRuntimeService + PlanningService into a single unified service.
Provides both LangGraph runtime operations and planning business logic.

Architecture:
    API Layer → PlanningRuntimeService → LangGraph StateGraph
                  ↓
                  EventConnectionHub (online event publishing)

Key benefits:
- Single entry point for all planning operations
- Eliminates redundant call chain (PlanningService → GraphRuntimeService)
- Cleaner separation between API layer and business logic
"""

import asyncio
import logging
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, List

from fastapi import BackgroundTasks, HTTPException
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import StateGraph

from app.database.engine import get_global_checkpointer
from app.database.operations import (
    create_planning_session_async,
    update_planning_session_async,
)
from app.api.schemas import TaskStatus
from app.infrastructure.events import event_hub as sse_manager
from app.services.checkpoint import checkpoint_service, checkpoint_persistence_manager
from app.core.settings import GRAPH_MAX_CONCURRENCY, GRAPH_RECURSION_LIMIT
from app.workflow.root_graph import create_unified_planning_graph
from app.workflow.runtime_adapter import materialize_workflow_state, pack_workflow_patch
from app.agent.plan_state.state import state_to_ui_status
from app.agent.bootstrap.phase_machine import (
    get_layer_dimensions,
    get_layer_name,
    _phase_to_layer,
)
from app.utils.sse_publisher import SSEPublisher
from app.utils.event_factory import (
    create_completed_event,
    create_error_event,
    create_layer_started_event,
    create_checkpoint_saved_event,
)

logger = logging.getLogger(__name__)
from app.services.resume_service import ResumeConflictError, ResumeService

# Known intent tool names that should not be overridden by synthetic messages
_KNOWN_INTENT_NAMES = frozenset({"advance_planning_intent", "gis_analysis", "GISAnalysis"})


def _has_existing_intent(last_msg) -> bool:
    """Check if the last message already carries a known intent tool_call."""
    if not last_msg or not hasattr(last_msg, "tool_calls") or not last_msg.tool_calls:
        return False
    return last_msg.tool_calls[0].get("name") in _KNOWN_INTENT_NAMES


def _build_synthetic_intent_message(session_id: str, reason: str = "用户启动规划") -> AIMessage:
    """Build synthetic AIMessage with advance_planning_intent tool call."""
    return AIMessage(
        content="",
        tool_calls=[{
            "name": "advance_planning_intent",
            "id": f"call_{session_id[:8]}",
            "args": {"reason": reason},
        }],
    )


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
    _execute_subgraph: Optional[Any] = None
    _initialized: bool = False
    _lock: Optional[asyncio.Lock] = None
    _execution_locks: Dict[str, asyncio.Lock] = {}

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

            from app.domain.materialization.execute_agent import build_execute_agent_graph
            # EXECUTE has a different local worker schema and is invoked as a
            # stage adapter. Its workspace never crosses the parent graph
            # checkpoint; the parent receives only typed artifact refs/results.
            cls._execute_subgraph = build_execute_agent_graph(checkpointer=None)
            logger.info(
                "[PlanningRuntimeService] EXECUTE subgraph compiled "
                "(parent checkpoint owns stage boundary)"
            )

            cls._initialized = True
            logger.info("[PlanningRuntimeService] Initialization complete")

    @classmethod
    async def ensure_initialized(cls) -> None:
        """Ensure the service is initialized (lazy initialization)."""
        if not cls._initialized or cls._graph is None:
            await cls.initialize()

    @classmethod
    async def shutdown(cls) -> None:
        """Cancel all tracked background tasks on application shutdown."""
        from app.services.composition import CompositionRoot

        sup = CompositionRoot.get_task_supervisor()
        await sup.cancel_all()
        logger.info("[PlanningRuntimeService] All tracked tasks cancelled")

    @classmethod
    def get_thread_config(cls, session_id: str, checkpoint_id: str = None) -> Dict[str, Any]:
        """Build configurable dict for LangGraph operations."""
        configurable = {"thread_id": session_id, "checkpoint_ns": ""}
        if checkpoint_id:
            configurable["checkpoint_id"] = checkpoint_id
        return {"configurable": configurable}

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
        if snapshot:
            values = materialize_workflow_state(dict(snapshot.values or {}))
            # During the first interrupt checkpoint LangGraph can expose the
            # resume payload on the pending task before it merges the waiting
            # node's values.  Surface the same HUMAN fields to internal
            # callers so they cannot mistake a real pause for a running gap.
            for task in snapshot.tasks or ():
                for pending_interrupt in getattr(task, "interrupts", None) or ():
                    payload = getattr(pending_interrupt, "value", None)
                    if not isinstance(payload, dict):
                        continue
                    from app.modules.schema.contracts.human_interrupt_contracts import normalize_human_interrupt

                    normalized_interrupt = normalize_human_interrupt(payload)
                    values["human_interrupt"] = normalized_interrupt
                    values["human_review_items"] = normalized_interrupt.get("items", [])
                    values["human_review_event_id"] = normalized_interrupt.get("event_id", "")
                    for key in ("paused_stage", "post_l3_status"):
                        value = normalized_interrupt.get(key) or payload.get(key)
                        if value not in (None, "", []):
                            values[key] = value
            if values or any(getattr(t, "interrupts", None) for t in snapshot.tasks or ()):
                return values
        return None

    @classmethod
    async def aupdate_state(
        cls,
        session_id: str,
        updates: Dict[str, Any],
        as_node: Optional[str] = None
    ) -> bool:
        """Update checkpoint state for a session (no graph resumption).

        Uses native graph.aupdate_state() after packing the stage view into
        the ref-only WorkflowState checkpoint.
        """
        await cls.ensure_initialized()
        config = cls.get_thread_config(session_id)
        snapshot = await cls._graph.aget_state(config)
        raw_state = dict(snapshot.values or {}) if snapshot else {}
        if "runtime" in updates:
            runtime_patch = updates.get("runtime")
            patch = {key: value for key, value in updates.items() if key != "runtime"}
            if isinstance(runtime_patch, dict):
                merged_patch = dict(runtime_patch)
                merged_patch.update(patch)
                updates = pack_workflow_patch(raw_state, merged_patch)
            else:
                updates = pack_workflow_patch(raw_state, patch)
        else:
            updates = pack_workflow_patch(raw_state, updates)

        await cls._graph.aupdate_state(config, updates, as_node=as_node)

        logger.info(
            "[PlanningRuntimeService] [%s] aupdate_state: keys=%s, as_node=%s",
            session_id, list(updates.keys()), as_node,
        )
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
    async def resume_from_interrupt(
        cls,
        session_id: str,
        resume_data: Dict[str, Any],
        state_updates: Optional[Dict[str, Any]] = None,
        expected_event_id: Optional[str] = None,
    ) -> None:
        """Resume graph after interrupt() using official Command(resume=...) pattern.

        Args:
            session_id: Session identifier
            resume_data: Data passed back to interrupt() call site
                         e.g. {"action": "approve"} or {"action": "reject", "feedback": "..."}
            state_updates: Optional state updates combined with resume
        """
        from langgraph.types import Command

        await cls.ensure_initialized()
        config = cls.get_thread_config(session_id)
        config["recursion_limit"] = GRAPH_RECURSION_LIMIT

        if not resume_data:
            raise ValueError("resume payload must be a non-empty object")

        if state_updates:
            raw_snapshot = await cls.aget_state(session_id)
            raw_state = dict(raw_snapshot.values or {}) if raw_snapshot else {}
            command = Command(
                resume=resume_data,
                update=pack_workflow_patch(raw_state, state_updates),
            )
        else:
            command = Command(resume=resume_data)

        async with cls._execution_locks.setdefault(session_id, asyncio.Lock()):
            # Check the token inside the execution lock.  Checking only in
            # the HTTP handler leaves a race where two identical requests
            # both pass before the first graph run marks the checkpoint as
            # consumed, causing duplicate downstream LLM work.
            if expected_event_id:
                current = await cls.aget_state_values(session_id) or {}
                ResumeService.validate_interrupt(current, expected_event_id)
            else:
                current = await cls.aget_state_values(session_id) or {}

            paused_stage = str(current.get("paused_stage") or "").lower()
            if paused_stage in {"l1", "l2", "l3", "ground", "select"}:
                from app.services.session_kg import ensure_session_kg

                context_ref = current.get("context_ref") or {}
                raw_version = context_ref.get("version") or current.get("context_version")
                try:
                    bundle_version = int(raw_version) if raw_version is not None else None
                except (TypeError, ValueError):
                    bundle_version = None
                restored = await ensure_session_kg(
                    session_id,
                    force=bundle_version is not None,
                    bundle_version=bundle_version,
                )
                if restored is None:
                    raise RuntimeError(
                        f"cannot resume {paused_stage}: session data/KG restoration failed"
                    )

            # A provider failure opens a session-scoped circuit breaker so a
            # parallel wave stops spending requests.  An explicit HUMAN
            # resume is the operator's bounded permission to try the failed
            # dimension again; reset it only after the token is accepted.
            from app.agent.common.dimension_runtime import reset_provider_failure
            reset_provider_failure(session_id)

            initial_state = await cls.aget_state_values(session_id) or {}
            initial_signature = (
                initial_state.get("phase"),
                initial_state.get("current_stage"),
                initial_state.get("next_stage"),
                initial_state.get("paused_stage"),
                initial_state.get("human_review_event_id"),
            )
            logger.info(
                "[PlanningRuntimeService] [%s] RESUME from interrupt: resume_data=%s state_updates=%s",
                session_id, resume_data,
                {k: type(v).__name__ for k, v in state_updates.items()} if state_updates else None,
            )
            stream_iterator = cls._graph.astream(
                command, config,
                stream_mode=['values', 'checkpoints'],
                version="v2",
            )

            last_completed_layer = 0
            last_phase = ""
            observed_signatures = []

            async for part in stream_iterator:
                if part.get("type") == 'values':
                    state = materialize_workflow_state(part["data"])
                    observed_signatures.append((
                        state.get("phase"),
                        state.get("current_stage"),
                        state.get("next_stage"),
                        state.get("paused_stage"),
                        state.get("human_review_event_id"),
                    ))
                    # Detect layer completion for SSE events (correlate with checkpoint)
                    if state.get('previous_layer') and state.get('previous_layer', 0) > 0:
                        layer = state.get('previous_layer', 0)
                        if layer > 0:
                            last_completed_layer = layer
                            last_phase = state.get('phase', '')

                    # Detect revision completion
                    last_revised = state.get('last_revised_dimensions', [])
                    if last_revised and not state.get('is_revision', False):
                        logger.info(
                            "[PlanningRuntimeService] [%s] Revision completed after resume: %d dims",
                            session_id, len(last_revised),
                        )

                elif part.get("type") == 'checkpoints':
                    data = part["data"]
                    await checkpoint_persistence_manager.mark_write_complete(session_id)
                    if last_completed_layer > 0:
                        checkpoint_id = None
                        if hasattr(data, 'config'):
                            checkpoint_id = data.config.get('configurable', {}).get('checkpoint_id', '')
                        if checkpoint_id:
                            checkpoint_saved_event = create_checkpoint_saved_event(
                                checkpoint_id=checkpoint_id,
                                layer=last_completed_layer,
                                phase=last_phase,
                                session_id=session_id,
                            )
                            sse_manager.publish_sync(session_id, checkpoint_saved_event)
                            last_completed_layer = 0

            final_state = await cls.aget_state_values(session_id)
            final_signature = (
                (final_state or {}).get("phase"),
                (final_state or {}).get("current_stage"),
                (final_state or {}).get("next_stage"),
                (final_state or {}).get("paused_stage"),
                (final_state or {}).get("human_review_event_id"),
            )
            terminal_status = str((final_state or {}).get("delivery_status") or "")
            still_paused = bool((final_state or {}).get("human_interrupt")) or bool(
                (final_state or {}).get("paused_stage")
            )
            if (
                final_state
                and final_signature == initial_signature
                and still_paused
                and terminal_status not in {"complete", "partial", "diagnostic_only"}
                and not final_state.get("fatal_error")
            ):
                diagnostic = {
                    "stage": (final_state.get("paused_stage") or final_state.get("phase") or "unknown"),
                    "reason": "resume_no_progress",
                    "message": "Resume returned without advancing the checkpoint or reaching a terminal state.",
                    "initial_signature": initial_signature,
                    "final_signature": final_signature,
                }
                logger.error("[PlanningRuntimeService] [%s] Resume made no progress: %s", session_id, diagnostic)
                try:
                    await cls.aupdate_state(
                        session_id,
                        {
                            "delivery_status": "diagnostic_only",
                            "diagnostic_terminal": diagnostic,
                            "fatal_error": diagnostic,
                            "phase": "completed",
                            "current_stage": diagnostic["stage"],
                            "next_stage": "TERMINAL",
                        },
                        as_node="end_diagnostic",
                    )
                except Exception as state_error:
                    logger.error("[PlanningRuntimeService] [%s] failed to persist resume diagnostic: %s", session_id, state_error)
                await update_planning_session_async(session_id, {
                    "status": TaskStatus.failed,
                    "execution_error": diagnostic["message"],
                })
                await cls._append_event(session_id, create_error_event(session_id, diagnostic["message"]))
                return
            fatal_error = (final_state or {}).get("fatal_error")
            if fatal_error:
                message = fatal_error.get("message", "planning execution failed") if isinstance(fatal_error, dict) else str(fatal_error)
                await update_planning_session_async(session_id, {
                    "status": TaskStatus.failed,
                    "execution_error": message,
                })
                await cls._append_event(session_id, create_error_event(session_id, message))
                logger.error("[PlanningRuntimeService] [%s] Terminal graph failure: %s", session_id, fatal_error)
                return
            deliver_gate = (final_state or {}).get("deliver_gate") or {}
            deliver_route = deliver_gate.get("feedback_route") if isinstance(deliver_gate, dict) else getattr(deliver_gate, "feedback_route", None)
            delivery_status = str((final_state or {}).get("delivery_status") or "")
            if final_state and final_state.get("phase") == "completed" and (
                deliver_route == "PASS"
                or delivery_status in {"complete", "partial", "diagnostic_only"}
            ):
                await cls._append_event(session_id, create_completed_event(
                    session_id,
                    delivery_status=delivery_status,
                    deferral_summary=final_state.get("deferral_summary") or {},
                    diagnostic_terminal=final_state.get("diagnostic_terminal") or {},
                ))

            # Send resumed SSE event
            sse_manager.publish_sync(session_id, {
                "type": "execution_resumed",
                "session_id": session_id,
                "timestamp": datetime.now().isoformat(),
            })

            logger.info("[PlanningRuntimeService] [%s] Interrupt resumption complete", session_id)

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
        image_ids: Optional[List[str]] = None,
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
            image_ids: Optional list of image IDs for multimodal analysis

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
        from app.agent.plan_state.state_factory import StateFactory
        initial_state = StateFactory.create(
            project_name=project_name,
            village_name=village_name,
            session_id=session_id,
            enable_review=enable_review,
            stream_mode=stream_mode,
            step_mode=step_mode,
            image_ids=image_ids,
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
        from app.database.operations import get_planning_session_async

        db_session = await get_planning_session_async(session_id)
        if not db_session:
            raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

        checkpoint_state = await cls.aget_state(session_id)
        state = await cls.aget_state_values(session_id) or {}
        # ``snapshot.next`` means scheduled nodes, not necessarily a HUMAN
        # pause.  A real interrupt is represented by PregelTask.interrupts.
        is_interrupted = bool(
            checkpoint_state
            and checkpoint_state.tasks
            and any(getattr(task, "interrupts", None) for task in checkpoint_state.tasks)
        )

        ui_status = state_to_ui_status(state, db_session, is_interrupted=is_interrupted)
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
        ui_status["revision_history"] = state.get("revision_history", [])
        ui_status["last_checkpoint_id"] = checkpoint_state.config.get("configurable", {}).get("checkpoint_id", "") if checkpoint_state else ""

        return ui_status

    # ==========================================
    # Background Execution & Event Handling
    # ==========================================

    @staticmethod
    async def _append_event(session_id: str, event: Dict) -> bool:
        """Publish an event through the single runtime event boundary."""
        try:
            await sse_manager.publish(session_id, event)
            return True
        except Exception as e:
            logger.warning(f"[PlanningRuntimeService] [{session_id}] event publish failed: {e}")
            return False

    @classmethod
    async def _trigger_planning_execution(
        cls,
        session_id: str,
        initial_state: Optional[Dict[str, Any]] = None,
        checkpoint_id: str = None,
        state_values: Optional[Dict[str, Any]] = None,
        replay_from_stage: Optional[str] = None,
        branch_id: Optional[str] = None,
    ) -> None:
        """
        Unified trigger for planning execution (skip conversation_node).

        Used for Layer 1 start and Layer 2/3 resume, unified execution entry.

        Args:
            session_id: Session identifier
            initial_state: Optional initial state (only for Layer 1 start)
            checkpoint_id: Optional checkpoint ID to resume from
            state_values: Optional pre-fetched state values (avoids redundant checkpoint read)
        """
        await cls.ensure_initialized()

        # Execution guard: prevent duplicate execution for the same session
        if session_id not in cls._execution_locks:
            cls._execution_locks[session_id] = asyncio.Lock()

        if cls._execution_locks[session_id].locked():
            logger.warning(
                "[PlanningRuntimeService] [%s] Execution already running, skipping duplicate trigger",
                session_id,
            )
            return

        async with cls._execution_locks[session_id]:
            await cls._execute_planning(
                session_id,
                initial_state,
                checkpoint_id,
                state_values,
                replay_from_stage,
                branch_id,
            )

    @classmethod
    async def _execute_planning(
        cls,
        session_id: str,
        initial_state: Optional[Dict[str, Any]] = None,
        checkpoint_id: str = None,
        state_values: Optional[Dict[str, Any]] = None,
        replay_from_stage: Optional[str] = None,
        branch_id: Optional[str] = None,
    ) -> None:
        """Internal execution method called within the session lock."""
        from app.utils.logger import set_session_id as _set_sid
        _set_sid(session_id)
        # Wait for SSE subscriber to connect before starting execution
        # This prevents early dimension_delta events from being lost
        # Reduced timeout for script mode efficiency (1s instead of 5s)
        subscriber_ready = await sse_manager.wait_for_subscriber(session_id, timeout=1.0)
        if not subscriber_ready:
            logger.debug(f"[PlanningRuntimeService] [{session_id}] No SSE subscriber (script mode), proceeding immediately")

        # 0. Pre-build session KG BEFORE L1 dimension analysis (idempotent).
        #    KG is built from the session bundle with parcel topology relations,
        #    so L1/L2/L3 dimension analysis receives real KG spatial cognition.
        #    Non-fatal: any failure logs a warning and the pipeline continues.
        if initial_state:
            try:
                from app.services.session_kg import ensure_session_kg

                initial_runtime = materialize_workflow_state(initial_state)
                vname = str((initial_runtime.get("config") or {}).get("village_name", ""))
                from app.core.settings import KG_BUILD_TIMEOUT_SECONDS
                logger.info(
                    "[PlanningRuntimeService] [%s] KG pre-build started (timeout=%ss)",
                    session_id,
                    KG_BUILD_TIMEOUT_SECONDS,
                )
                async with asyncio.timeout(KG_BUILD_TIMEOUT_SECONDS):
                    await ensure_session_kg(session_id, village_name=vname)
                logger.info("[PlanningRuntimeService] [%s] KG pre-build finished", session_id)
            except TimeoutError:
                # KG is enrichment, not a reason to leave the graph without a
                # checkpoint. Continue with the uploaded bundle and preserve a
                # diagnostic for the final manifest.
                logger.error(
                    "[PlanningRuntimeService] [%s] KG pre-build timed out after %ss; continuing without KG",
                    session_id,
                    KG_BUILD_TIMEOUT_SECONDS,
                )
            except Exception as e:  # noqa: BLE001 — non-fatal
                logger.warning(
                    "[PlanningRuntimeService] [%s] Session KG pre-build failed: %s",
                    session_id, e,
                )

        # 1. For initial_state, write all state + optional synthetic message
        #    in a single aupdate_state call with as_node="__start__".
        #    Per LangGraph docs: "Explicitly specify as_node when setting up state
        #    on a fresh thread with no execution history."
        #    LangGraph 1.2.8 fixes DeltaChannel fresh-thread aupdate_state bug (PR #8290).
        if initial_state:
            from app.agent.common.dimension_runtime import reset_provider_failure
            reset_provider_failure(session_id)
            clean_state = {
                k: v
                for k, v in materialize_workflow_state(initial_state).items()
                if k != "messages"
            }
            clean_state["phase"] = "layer1"

            # Inject synthetic AIMessage unless last message already has intent
            state_values = state_values or await cls.aget_state_values(session_id)
            messages = state_values.get("messages", []) if state_values else []
            last_msg = messages[-1] if messages else None

            if _has_existing_intent(last_msg):
                logger.info(
                    "[PlanningRuntimeService] [%s] Last message already has intent '%s', skipping synthetic injection",
                    session_id, last_msg.tool_calls[0].get("name"),
                )
            else:
                synthetic_ai_message = _build_synthetic_intent_message(session_id)
                clean_state["messages"] = [synthetic_ai_message]
                logger.info("[PlanningRuntimeService] [%s] Synthetic AIMessage added", session_id)

            await cls.aupdate_state(session_id, clean_state, as_node="__start__")
            logger.info(
                "[PlanningRuntimeService] [%s] Initial state written (as_node=__start__, has_messages=%s)",
                session_id, "messages" in clean_state,
            )

        stream_input = None  # Resume from checkpoint
        if replay_from_stage or branch_id:
            # Command(update=...) creates a descendant checkpoint while
            # preserving the historical cursor's next node.  This marks the
            # execution as a recovery revision without mutating the source
            # checkpoint or routing through START again.
            from langgraph.types import Command

            updates: dict[str, Any] = {}
            if replay_from_stage:
                retry_counts = dict((state_values or {}).get("retry_counts") or {})
                retry_counts[replay_from_stage] = int(retry_counts.get(replay_from_stage, 0)) + 1
                updates["retry_counts"] = retry_counts
            if branch_id:
                from app.infrastructure.artifacts.runtime import fork_artifact_refs

                fork_state = state_values or await cls.aget_state_values(session_id) or {}
                updates["artifact_refs"] = fork_artifact_refs(fork_state, branch_id)
                updates["branch_id"] = branch_id
            raw_snapshot = await cls.aget_state(session_id)
            raw_state = dict(raw_snapshot.values or {}) if raw_snapshot else {}
            stream_input = Command(update=pack_workflow_patch(raw_state, updates))

        # 4. Build config with max_concurrency + optional streaming callback
        config = cls.get_thread_config(session_id, checkpoint_id=checkpoint_id)
        config["max_concurrency"] = GRAPH_MAX_CONCURRENCY
        config["recursion_limit"] = GRAPH_RECURSION_LIMIT

        initial_runtime = materialize_workflow_state(initial_state) if initial_state else {}
        streaming_enabled = initial_runtime.get("_streaming_enabled", True)
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
            # stream_input already set above:
            #   - initial_state: plain dict with initial state + synthetic message
            #   - resume: None (aupdate_state already injected messages, astream resumes from checkpoint)

            stream_iterator = cls._graph.astream(
                stream_input, config,
                stream_mode=['values', 'checkpoints'],
                version="v2",
            )

            async for part in stream_iterator:
                if part.get("type") == 'values':
                    state = materialize_workflow_state(part["data"])

                    # 级联修订完成检测（独立于正常层完成检测）
                    last_revised_dimensions = state.get('last_revised_dimensions', [])
                    if last_revised_dimensions and not state.get('is_revision', False):
                        is_revision = True
                        revision_dimensions = last_revised_dimensions
                        last_completed_layer = state.get('previous_layer', 0)
                        last_phase = state.get('phase', '')
                        logger.info(
                            "[PlanningRuntimeService] [%s] Revision completed: %d dims",
                            session_id, len(revision_dimensions),
                        )

                    # Normal layer completion detection (for SSE event correlation)
                    if state.get('previous_layer') and state.get('previous_layer', 0) > 0 and not is_revision:
                        layer = state.get('previous_layer', 0)
                        if layer > 0 and not is_revision:
                            last_completed_layer = layer
                            last_phase = state.get('phase', '')
                            is_revision = False
                            revision_dimensions = []

                            logger.info(f"[PlanningRuntimeService] [{session_id}] Layer {layer} completed")

                elif part.get("type") == 'checkpoints':
                    data = part["data"]
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

                        sse_manager.publish_sync(session_id, checkpoint_saved_event)

                        # 修订完成后清除 last_revised_dimensions，防止后续正常检查点被误判
                        if is_revision:
                            await cls.aupdate_state(session_id, {
                                "last_revised_dimensions": [],
                            }, as_node="layer_completion_check")
                            logger.info(
                                "[PlanningRuntimeService] [%s] Cleared last_revised_dimensions after revision checkpoint",
                                session_id,
                            )

                        # Reset tracking for next layer
                        last_completed_layer = 0
                        last_phase = ""
                        is_revision = False
                        revision_dimensions = []

                else:
                    # Legacy single-mode handling (if stream_mode=['values'] only)
                    # This branch handles the case where event is not a tuple
                    pass

            # Only send completed event when all 3 layers are done
            final_state = await cls.aget_state_values(session_id)
            deliver_gate = (final_state or {}).get("deliver_gate") or {}
            deliver_route = deliver_gate.get("feedback_route") if isinstance(deliver_gate, dict) else getattr(deliver_gate, "feedback_route", None)
            delivery_status = str((final_state or {}).get("delivery_status") or "")
            if final_state and final_state.get("phase") == "completed" and (
                deliver_route == "PASS"
                or delivery_status in {"complete", "partial", "diagnostic_only"}
            ):
                await cls._append_event(session_id, create_completed_event(
                    session_id,
                    delivery_status=delivery_status,
                    deferral_summary=final_state.get("deferral_summary") or {},
                    diagnostic_terminal=final_state.get("diagnostic_terminal") or {},
                ))

            logger.info(f"[PlanningRuntimeService] [{session_id}] Background execution completed")

        except Exception as e:
            logger.error(f"[PlanningRuntimeService] [{session_id}] Execution failed: {e}", exc_info=True)
            failure = {
                "stage": str((await cls.aget_state_values(session_id) or {}).get("phase") or "unknown"),
                "code": type(e).__name__,
                "message": str(e),
            }
            try:
                await cls.aupdate_state(session_id, {
                    "fatal_error": failure,
                    "delivery_status": "diagnostic_only",
                    "diagnostic_terminal": failure,
                    "phase": "completed",
                    "current_stage": "TERMINAL",
                    "next_stage": "",
                }, as_node="end_diagnostic")
            except Exception as state_error:
                logger.error("[PlanningRuntimeService] failed to persist terminal error: %s", state_error)
            await cls._append_event(session_id, create_error_event(session_id, str(e)))
        finally:
            # Clean up execution lock to prevent memory leak
            cls._execution_locks.pop(session_id, None)

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
        sse_manager.publish_sync(session_id, resumed_event)

        # Update database status
        await update_planning_session_async(session_id, {
            "status": TaskStatus.running,
            "execution_error": None,
        })

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

        # Start background execution
        from app.services.composition import CompositionRoot

        CompositionRoot.get_task_supervisor().create_task(
            session_id,
            cls._trigger_planning_execution(session_id, state_values=full_state),
        )

        return {
            "message": "Execution resumed",
            "session_id": session_id,
            "stream_url": f"/api/planning/stream/{session_id}",
            "current_layer": current_layer,
            "resumed": True
        }

# Singleton instance
planning_runtime_service = PlanningRuntimeService()


__all__ = ["PlanningRuntimeService", "planning_runtime_service"]
