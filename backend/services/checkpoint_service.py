"""
Checkpoint Service - Shared LangGraph Checkpoint Access

This service provides centralized access to LangGraph checkpoints.
Uses lazy import to avoid circular dependency with PlanningRuntimeService.

Includes async persistence with checkpoint synchronization:
- Writes don't block execution flow
- Reads can wait for latest checkpoint write completion
"""

import asyncio
import logging
import time
from collections import deque
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple

from backend.constants import MAX_SESSION_EVENTS
from src.orchestration.state import get_layer_dimensions, get_layer_name, _phase_to_layer
from src.utils.event_factory import create_layer_completed_event

# Lazy import for DIMENSION_NAMES to avoid circular dependency
_DIMENSION_NAMES = None

logger = logging.getLogger(__name__)


def _get_dimension_names():
    """Get dimension names mapping (lazy import)."""
    global _DIMENSION_NAMES
    if _DIMENSION_NAMES is None:
        from src.config.dimension_metadata import get_dimension_config
        from src.orchestration.nodes.dimension_node import DIMENSION_NAMES
        _DIMENSION_NAMES = DIMENSION_NAMES
    return _DIMENSION_NAMES


class CheckpointPersistenceManager:
    """
    Manages async checkpoint persistence with synchronization.

    Ensures:
    - Writes don't block execution (async fire-and-forget)
    - Reads can wait for latest write completion (checkpoint sync)

    This is a lightweight wrapper that tracks pending writes via Futures.
    Includes TTL-based cleanup to prevent memory leaks.
    """

    _pending_writes: Dict[str, Tuple[asyncio.Future, float]] = {}  # (future, start_time)
    _lock = asyncio.Lock()
    MAX_TTL = 300.0  # 5 minutes max wait for a write to complete

    @classmethod
    async def mark_write_complete(cls, session_id: str) -> None:
        """
        Mark that a checkpoint write has completed.
        Also cleans up any stale entries (TTL expired).
        """
        async with cls._lock:
            # Clean up stale entries first
            current_time = time.time()
            stale_keys = [
                k for k, (_, start_time) in cls._pending_writes.items()
                if current_time - start_time > cls.MAX_TTL
            ]
            for k in stale_keys:
                future, _ = cls._pending_writes[k]
                if not future.done():
                    future.set_exception(asyncio.TimeoutError(f"Write TTL expired after {cls.MAX_TTL}s"))
                del cls._pending_writes[k]
                logger.warning(f"[CheckpointPersistence] Session {k}: cleaned up stale entry (TTL expired)")

            # Mark current session complete
            if session_id in cls._pending_writes:
                future, _ = cls._pending_writes[session_id]
                if not future.done():
                    future.set_result(True)
                del cls._pending_writes[session_id]

    @classmethod
    async def wait_for_write(cls, session_id: str, timeout: float = 5.0) -> bool:
        """
        Wait for pending checkpoint write to complete.

        Args:
            session_id: Session identifier
            timeout: Maximum wait time in seconds

        Returns:
            True if write completed (or no pending write), False if timeout
        """
        async with cls._lock:
            entry = cls._pending_writes.get(session_id)
            if entry is None:
                return True
            future, start_time = entry
            if future.done():
                return True
            # Check if already TTL expired
            if time.time() - start_time > cls.MAX_TTL:
                del cls._pending_writes[session_id]
                return False

        try:
            await asyncio.wait_for(future, timeout=timeout)
            return True
        except asyncio.TimeoutError:
            logger.warning(f"[CheckpointPersistence] Session {session_id}: write wait timeout after {timeout}s")
            return False


checkpoint_persistence_manager = CheckpointPersistenceManager()


class CheckpointService:
    """
    Centralized checkpoint access service.

    Uses lazy import for PlanningRuntimeService to avoid circular dependencies.

    Provides a single point of access for:
    - Getting checkpoint state
    - Extracting layer reports
    - Checking layer completion status
    """

    @classmethod
    async def get_state(cls, session_id: str, wait_for_write: bool = False) -> Optional[Dict[str, Any]]:
        """
        Get the full checkpoint state for a session.

        Args:
            session_id: Session identifier
            wait_for_write: If True, wait for any pending checkpoint write to complete

        Returns:
            State dict or None if not found
        """
        from backend.services.planning_runtime_service import PlanningRuntimeService
        try:
            # Optionally wait for pending write completion
            if wait_for_write:
                await checkpoint_persistence_manager.wait_for_write(session_id)

            return await PlanningRuntimeService.aget_state_values(session_id)
        except Exception as e:
            logger.error(f"[CheckpointService] Failed to get state for {session_id}: {e}")
            return None

    @classmethod
    async def get_layer_reports(
        cls,
        session_id: str,
        layer: int
    ) -> Dict[str, Any]:
        """Get reports for a specific layer."""
        state = await cls.get_state(session_id)
        if not state:
            return {
                "layer": layer,
                "reports": {},
                "completed": False,
                "stats": {"dimension_count": 0, "total_chars": 0}
            }

        reports_raw = state.get("reports", {})
        completed_dims = state.get("completed_dimensions", {})

        layer_key = f"layer{layer}"
        reports = reports_raw.get(layer_key, {})
        completed_dims_list = completed_dims.get(layer_key, [])
        expected_dims = get_layer_dimensions(layer)

        layer_completed = len(completed_dims_list) >= len(expected_dims)
        total_chars = sum(len(v) for v in reports.values()) if reports else 0

        return {
            "layer": layer,
            "reports": reports,
            "completed": layer_completed,
            "stats": {
                "dimension_count": len(reports),
                "total_chars": total_chars
            }
        }

    @classmethod
    async def get_completion_status(
        cls,
        session_id: str,
        state: Optional[Dict[str, Any]] = None
    ) -> Dict[str, bool]:
        """Get the completion status for all layers."""
        if state is None:
            state = await cls.get_state(session_id)
        if not state:
            return {"layer1": False, "layer2": False, "layer3": False}

        completed_dims = state.get("completed_dimensions", {})

        return {
            "layer1": len(completed_dims.get("layer1", [])) >= len(get_layer_dimensions(1)),
            "layer2": len(completed_dims.get("layer2", [])) >= len(get_layer_dimensions(2)),
            "layer3": len(completed_dims.get("layer3", [])) >= len(get_layer_dimensions(3)),
        }

    @classmethod
    async def get_phase(cls, session_id: str) -> str:
        """Get the current phase for a session."""
        state = await cls.get_state(session_id)
        if not state:
            return "init"
        return state.get("phase", "init")

    @classmethod
    async def get_project_name(cls, session_id: str) -> str:
        """Get the project name for a session."""
        state = await cls.get_state(session_id)
        if not state:
            return "村庄规划"
        return state.get("project_name", state.get("config", {}).get("village_data", "村庄规划")[:50])

    @classmethod
    async def update_state(cls, session_id: str, updates: Dict[str, Any], as_node: Optional[str] = None) -> bool:
        """Update the checkpoint state for a session."""
        from backend.services.planning_runtime_service import PlanningRuntimeService
        try:
            return await PlanningRuntimeService.aupdate_state(session_id, updates, as_node=as_node)
        except Exception as e:
            logger.error(f"[CheckpointService] Failed to update state for {session_id}: {e}")
            return False

    @classmethod
    async def validate_session(cls, session_id: str) -> Dict[str, Any]:
        """Get and validate session state, raise ValueError if not found."""
        state = await cls.get_state(session_id)
        if not state:
            raise ValueError(f"Session {session_id} not found in checkpoint")
        return state

    @classmethod
    async def clear_pause_flags(cls, session_id: str) -> bool:
        """Clear pause flags and reset wave for next layer."""
        return await cls.update_state(session_id, {
            "pause_after_step": False,
            "previous_layer": 0,
            "current_wave": 1,  # Reset wave for next layer execution
        })

    @classmethod
    async def calculate_next_layer(
        cls,
        session_id: str,
        state: Optional[Dict[str, Any]] = None
    ) -> tuple[int, str]:
        """Calculate next layer and phase based on completion status."""
        if state is None:
            state = await cls.get_state(session_id)

        phase = state.get("phase", "init")
        previous_layer = state.get("previous_layer", 0)

        if previous_layer > 0:
            next_layer = previous_layer + 1
        else:
            completion = await cls.get_completion_status(session_id, state)
            if completion["layer1"]:
                next_layer = 2 if not completion["layer2"] else 3
            else:
                next_layer = 1

        phase_map = {1: "layer1", 2: "layer2", 3: "layer3"}
        next_phase = phase_map.get(next_layer, "completed")

        return next_layer, next_phase

    @classmethod
    async def get_checkpoint_history(cls, session_id: str) -> List[Dict[str, Any]]:
        """Get checkpoint history for a session."""
        from backend.services.planning_runtime_service import PlanningRuntimeService
        try:
            history = []
            async for state_snapshot in PlanningRuntimeService.aget_state_history(session_id):
                checkpoint_id = state_snapshot.config.get("configurable", {}).get("checkpoint_id", "")
                history.append({
                    "checkpoint_id": checkpoint_id,
                    "values": state_snapshot.values,
                    "config": state_snapshot.config,
                })
            return history
        except Exception as e:
            logger.error(f"[CheckpointService] Failed to get history for {session_id}: {e}")
            return []

    @classmethod
    async def rebuild_events(cls, session_id: str) -> List[Dict[str, Any]]:
        """Rebuild key events from checkpoint state."""
        from backend.services.planning_runtime_service import PlanningRuntimeService
        events = []

        try:
            checkpoint_state = await PlanningRuntimeService.aget_state(session_id)

            if not checkpoint_state or not checkpoint_state.values:
                logger.debug(f"[CheckpointService] Session {session_id}: no checkpoint state")
                return events

            state = checkpoint_state.values

            metadata = state.get("metadata", {})
            reports = state.get("reports", {})
            completed_dims = state.get("completed_dimensions", {})
            phase = state.get("phase", "init")

            # Get knowledge sources cache from state config
            config = state.get("config", {})
            knowledge_sources_cache = config.get("knowledge_sources_cache", {})

            # Get dimension names mapping (lazy loaded)
            DIMENSION_NAMES = _get_dimension_names()

            # Pre-compute current layer from phase (efficiency: avoid repeated calls)
            current_layer_from_phase = _phase_to_layer(phase)

            for layer_num in [1, 2, 3]:
                # Filter by phase: skip layers that haven't been reached yet
                if current_layer_from_phase is not None and layer_num > current_layer_from_phase:
                    continue

                layer_key = f"layer{layer_num}"
                layer_completed = len(completed_dims.get(layer_key, [])) >= len(get_layer_dimensions(layer_num))

                if layer_completed:
                    dimension_reports = reports.get(layer_key, {})

                    # Use event factory for consistent event creation
                    event = create_layer_completed_event(
                        layer=layer_num,
                        phase=phase,
                        reports=reports,
                        pause_after_step=state.get("pause_after_step", False),
                        previous_layer=layer_num,
                        session_id=session_id,
                        knowledge_sources_cache=knowledge_sources_cache,
                    )
                    event["_rebuild"] = True
                    events.append(event)
                    logger.info(f"[CheckpointService] Session {session_id}: rebuilt layer_completed event Layer {layer_num}")

                    # Rebuild dimension_complete events for each completed dimension
                    for dim_key, dim_content in dimension_reports.items():
                        if dim_content and len(dim_content) > 50:
                            dim_name = DIMENSION_NAMES.get(dim_key, dim_key)
                            dim_event = {
                                "type": "dimension_complete",
                                "layer": layer_num,
                                "dimension_key": dim_key,
                                "dimension_name": dim_name,
                                "full_content": dim_content,
                                "knowledge_sources": knowledge_sources_cache.get(dim_key, []),
                                "session_id": session_id,
                                "timestamp": metadata.get("last_signal_timestamp", datetime.now().isoformat()),
                                "_rebuild": True,
                            }
                            events.append(dim_event)
                            logger.debug(f"[CheckpointService] Session {session_id}: rebuilt dimension_complete {dim_key}")

            if state.get("pause_after_step", False):
                previous_layer = state.get("previous_layer", 1)
                checkpoint_id = checkpoint_state.config.get("configurable", {}).get("checkpoint_id", "")
                pause_event = {
                    "type": "pause",
                    "session_id": session_id,
                    "current_layer": previous_layer,
                    "checkpoint_id": checkpoint_id,
                    "reason": "step_mode",
                    "timestamp": datetime.now().isoformat(),
                    "_rebuild": True,
                }
                events.append(pause_event)
                logger.info(f"[CheckpointService] Session {session_id}: rebuilt pause event Layer {previous_layer}")

            logger.info(f"[CheckpointService] Session {session_id}: rebuilt {len(events)} events total")

        except Exception as e:
            logger.error(f"[CheckpointService] Session {session_id}: rebuild failed - {e}", exc_info=True)

        return events

    @classmethod
    async def rebuild_session_from_db(
        cls,
        session_id: str,
        get_session_async_func,
        sse_manager,
    ) -> Optional[Dict[str, Any]]:
        """Rebuild memory session from database and checkpoint."""
        from backend.services.planning_runtime_service import PlanningRuntimeService
        from backend.services.sse_manager import sse_manager as sse_mgr

        db_session = await get_session_async_func(session_id)
        if not db_session:
            return None

        initial_state = {}
        try:
            initial_state = await PlanningRuntimeService.aget_state_values(session_id) or {}
            if initial_state:
                logger.info(f"[CheckpointService] [{session_id}] State restored from checkpoint")
        except Exception as e:
            logger.warning(f"[CheckpointService] [{session_id}] Checkpoint read failed: {e}")

        session_data = {
            "session_id": db_session["session_id"],
            "project_name": db_session["project_name"],
            "created_at": db_session["created_at"].isoformat() if isinstance(db_session["created_at"], datetime) else db_session["created_at"],
            "events": deque(maxlen=MAX_SESSION_EVENTS),
            "initial_state": initial_state,
        }
        sse_mgr.init_session(session_id, session_data)

        logger.info(f"[CheckpointService] [{session_id}] Memory session rebuilt from database (with initial_state)")
        return session_data


# Singleton instance for easy import
checkpoint_service = CheckpointService()


__all__ = ["CheckpointService", "checkpoint_service", "CheckpointPersistenceManager", "checkpoint_persistence_manager"]