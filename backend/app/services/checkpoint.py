"""Checkpoint-related application queries and write synchronization.

The LangGraph runtime owns checkpoint execution and resume.  This module only
provides small queries used by legacy report/session callers and the write
barrier used while a checkpoint is being persisted.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, Optional

from app.agent.bootstrap.phase_machine import get_layer_dimensions

logger = logging.getLogger(__name__)


class CheckpointPersistenceManager:
    """Coordinate asynchronous checkpoint writes without storing graph state."""

    _pending_writes: dict[str, tuple[asyncio.Future[bool], float]] = {}
    _lock = asyncio.Lock()
    MAX_TTL = 300.0

    @classmethod
    async def mark_write_complete(cls, session_id: str) -> None:
        async with cls._lock:
            now = time.time()
            stale = [
                key
                for key, (_, started) in cls._pending_writes.items()
                if now - started > cls.MAX_TTL
            ]
            for key in stale:
                future, _ = cls._pending_writes.pop(key)
                if not future.done():
                    future.set_exception(asyncio.TimeoutError("checkpoint write TTL expired"))
            entry = cls._pending_writes.pop(session_id, None)
            if entry and not entry[0].done():
                entry[0].set_result(True)

    @classmethod
    async def wait_for_write(cls, session_id: str, timeout: float = 5.0) -> bool:
        async with cls._lock:
            entry = cls._pending_writes.get(session_id)
            if entry is None:
                return True
            future, started = entry
            if future.done():
                return True
            if time.time() - started > cls.MAX_TTL:
                cls._pending_writes.pop(session_id, None)
                return False
        try:
            await asyncio.wait_for(future, timeout=timeout)
            return True
        except asyncio.TimeoutError:
            logger.warning("Checkpoint write wait timed out for %s", session_id)
            return False


checkpoint_persistence_manager = CheckpointPersistenceManager()


class CheckpointService:
    """Small checkpoint-derived queries; execution remains in the runtime."""

    @classmethod
    async def get_layer_reports(cls, session_id: str, layer: int) -> Dict[str, Any]:
        from app.services.runtime import PlanningRuntimeService
        from app.services.report_store import ReportStore

        state = await PlanningRuntimeService.aget_state_values(session_id)
        if not state:
            return {
                "layer": layer,
                "reports": {},
                "completed": False,
                "stats": {"dimension_count": 0, "total_chars": 0},
            }
        reports = await ReportStore.get_instance().get_layer_reports_with_sources(session_id, layer)
        completed = state.get("completed_dimensions", {}).get(f"layer{layer}", [])
        expected = get_layer_dimensions(layer)
        return {
            "layer": layer,
            "reports": reports,
            "completed": len(completed) >= len(expected),
            "stats": {
                "dimension_count": len(reports),
                "total_chars": sum(len(item.get("content", "")) for item in reports.values()),
            },
        }

    @classmethod
    async def get_completion_status(
        cls,
        session_id: str,
        state: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, bool]:
        from app.services.runtime import PlanningRuntimeService

        state = state or await PlanningRuntimeService.aget_state_values(session_id)
        if not state:
            return {"layer1": False, "layer2": False, "layer3": False}
        completed = state.get("completed_dimensions", {})
        return {
            f"layer{layer}": len(completed.get(f"layer{layer}", [])) >= len(get_layer_dimensions(layer))
            for layer in (1, 2, 3)
        }

    @classmethod
    async def get_phase(cls, session_id: str) -> str:
        from app.services.runtime import PlanningRuntimeService

        state = await PlanningRuntimeService.aget_state_values(session_id)
        return str((state or {}).get("phase", "init"))

    @classmethod
    async def validate_session(cls, session_id: str) -> Dict[str, Any]:
        from app.services.runtime import PlanningRuntimeService

        state = await PlanningRuntimeService.aget_state_values(session_id)
        if not state:
            raise ValueError(f"Session {session_id} not found in checkpoint")
        return state

    @classmethod
    async def get_project_name(cls, session_id: str) -> str:
        from app.services.runtime import PlanningRuntimeService

        state = await PlanningRuntimeService.aget_state_values(session_id)
        return str((state or {}).get("project_name", "村庄规划"))

    @classmethod
    async def calculate_next_layer(
        cls,
        session_id: str,
        state: Optional[Dict[str, Any]] = None,
    ) -> tuple[int, str]:
        from app.services.runtime import PlanningRuntimeService

        state = state or await PlanningRuntimeService.aget_state_values(session_id) or {}
        previous_layer = int(state.get("previous_layer", 0) or 0)
        if previous_layer:
            next_layer = previous_layer + 1
        else:
            completion = await cls.get_completion_status(session_id, state)
            next_layer = 2 if completion["layer1"] and not completion["layer2"] else 3 if completion["layer1"] else 1
        return next_layer, {1: "layer1", 2: "layer2", 3: "layer3"}.get(next_layer, "completed")


checkpoint_service = CheckpointService()

__all__ = ["CheckpointService", "checkpoint_service", "CheckpointPersistenceManager", "checkpoint_persistence_manager"]
