"""
Checkpoint Service - Shared LangGraph Checkpoint Access

This service provides centralized access to LangGraph checkpoints,
eliminating duplicate checkpoint access code across the codebase.
"""

import logging
from typing import Dict, List, Any, Optional
from langgraph.checkpoint.base import BaseCheckpointSaver

from src.orchestration.main_graph import create_unified_planning_graph
from src.orchestration.state import get_layer_dimensions

logger = logging.getLogger(__name__)


class CheckpointService:
    """
    Centralized checkpoint access service.

    Provides a single point of access for:
    - Getting checkpoint state
    - Extracting layer reports
    - Checking layer completion status
    """

    _checkpointer: Optional[BaseCheckpointSaver] = None

    @classmethod
    async def get_checkpointer(cls) -> BaseCheckpointSaver:
        """Get or initialize the global checkpointer."""
        if cls._checkpointer is None:
            from backend.database.engine import get_global_checkpointer
            cls._checkpointer = await get_global_checkpointer()
        return cls._checkpointer

    @classmethod
    async def get_state(cls, session_id: str) -> Optional[Dict[str, Any]]:
        """
        Get the full checkpoint state for a session.

        Args:
            session_id: The session/thread ID

        Returns:
            The checkpoint state values, or None if not found
        """
        try:
            checkpointer = await cls.get_checkpointer()
            graph = create_unified_planning_graph(checkpointer=checkpointer)
            config = {"configurable": {"thread_id": session_id}}
            checkpoint_state = await graph.aget_state(config)

            if checkpoint_state and checkpoint_state.values:
                return checkpoint_state.values
            return None
        except Exception as e:
            logger.error(f"[CheckpointService] Failed to get state for {session_id}: {e}")
            return None

    @classmethod
    async def get_layer_reports(
        cls,
        session_id: str,
        layer: int
    ) -> Dict[str, Any]:
        """
        Get reports for a specific layer using NEW UnifiedPlanningState schema.

        Args:
            session_id: The session/thread ID
            layer: Layer number (1, 2, or 3)

        Returns:
            {
                "layer": int,
                "reports": Dict[str, str],
                "completed": bool,
                "stats": {"dimension_count": int, "total_chars": int}
            }
        """
        state = await cls.get_state(session_id)
        if not state:
            return {
                "layer": layer,
                "reports": {},
                "completed": False,
                "stats": {"dimension_count": 0, "total_chars": 0}
            }

        # Read from NEW UnifiedPlanningState schema
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
        """
        Get the completion status for all layers.

        Args:
            session_id: The session/thread ID
            state: Optional pre-fetched state to avoid redundant queries

        Returns:
            {"layer1": bool, "layer2": bool, "layer3": bool}
        """
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
        """
        Get the current phase for a session.

        Args:
            session_id: The session/thread ID

        Returns:
            Phase string (init, layer1, layer2, layer3, completed)
        """
        state = await cls.get_state(session_id)
        if not state:
            return "init"
        return state.get("phase", "init")

    @classmethod
    async def get_project_name(cls, session_id: str) -> str:
        """
        Get the project name for a session.

        Args:
            session_id: The session/thread ID

        Returns:
            Project name or default
        """
        state = await cls.get_state(session_id)
        if not state:
            return "村庄规划"
        return state.get("project_name", state.get("config", {}).get("village_data", "村庄规划")[:50])

    @classmethod
    async def update_state(cls, session_id: str, updates: Dict[str, Any]) -> bool:
        """
        Update the checkpoint state for a session.

        Args:
            session_id: The session/thread ID
            updates: State updates to apply

        Returns:
            True if successful, False otherwise
        """
        try:
            checkpointer = await cls.get_checkpointer()
            graph = create_unified_planning_graph(checkpointer=checkpointer)
            config = {"configurable": {"thread_id": session_id}}

            await graph.aupdate_state(config, updates)
            return True
        except Exception as e:
            logger.error(f"[CheckpointService] Failed to update state for {session_id}: {e}")
            return False


# Singleton instance for easy import
checkpoint_service = CheckpointService()


__all__ = ["CheckpointService", "checkpoint_service"]