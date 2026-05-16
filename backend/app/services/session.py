"""
Session Service - Session Lifecycle Management

This service handles session-related operations:
- Creating sessions
- Getting session status
- Deleting sessions
- Getting layer reports
"""

import logging
from datetime import datetime
from typing import Any, Dict, Optional

from app.api.schemas import TaskStatus
from app.services.sse import sse_manager
from app.services.checkpoint import checkpoint_service
from app.database.operations import (
    create_planning_session_async,
    get_planning_session_async,
    update_planning_session_async,
    delete_planning_session_async,
)

logger = logging.getLogger(__name__)


class LayerReportsResponse:
    """Response model for layer reports."""
    def __init__(
        self,
        layer: int,
        reports: Dict[str, str],
        completed: bool,
        stats: Dict[str, int],
    ):
        self.layer = layer
        self.reports = reports
        self.completed = completed
        self.stats = stats

    def to_dict(self) -> Dict[str, Any]:
        return {
            "layer": self.layer,
            "reports": self.reports,
            "completed": self.completed,
            "stats": self.stats,
        }


class SessionService:
    """
    Session lifecycle management service.

    Provides:
    - Session creation and initialization
    - Session status retrieval
    - Session deletion
    - Layer report access
    """

    @staticmethod
    async def create_session(
        session_id: str,
        project_name: str,
        request_data: Dict[str, Any],
    ) -> bool:
        """
        Create a new session in database and memory.

        Args:
            session_id: Unique session identifier
            project_name: Project/village name
            request_data: Full request data for the session

        Returns:
            True if successful, False otherwise
        """
        session_state = {
            "session_id": session_id,
            "project_name": project_name,
            "status": TaskStatus.running,
            "created_at": datetime.now().isoformat(),
            "request": request_data,
        }

        try:
            await create_planning_session_async(session_state)
            logger.info(f"[SessionService] [{session_id}] Session created in database")
            return True
        except Exception as e:
            logger.error(f"[SessionService] [{session_id}] Failed to create session: {e}")
            return False

    @staticmethod
    async def delete_session(session_id: str) -> Dict[str, bool]:
        """
        Delete a session completely.

        Removes session from:
        1. Memory (via SSEManager)
        2. Database (planning_sessions table)
        3. LangGraph checkpoints

        Args:
            session_id: Session identifier

        Returns:
            Dict with deletion status for each category
        """
        result = {
            "memory": False,
            "database": False,
            "checkpoint": False,
        }

        # Get session info for checkpoint deletion
        session_info = sse_manager.get_session(session_id)
        project_name = session_info.get("project_name") if session_info else None

        # 1. Delete memory states via SSEManager
        memory_result = sse_manager.delete_session_all_states(session_id)
        result["memory"] = any(memory_result.values())

        # 2. Delete database record
        db_deleted = await delete_planning_session_async(session_id)
        result["database"] = db_deleted

        # 3. Delete LangGraph checkpoint
        if project_name:
            try:
                from app.agent.graph import create_unified_planning_graph
                from app.database.engine import get_global_checkpointer

                checkpointer = await get_global_checkpointer()
                graph = create_unified_planning_graph(checkpointer=checkpointer)
                config = {"configurable": {"thread_id": session_id}}

                # Get all checkpoints and delete them
                checkpoints = [c async for c in checkpointer.aget_tuple(config)]
                for checkpoint in checkpoints:
                    await checkpointer.adelete(config)

                result["checkpoint"] = True
                logger.info(f"[SessionService] [{session_id}] Checkpoint deleted")
            except Exception as e:
                logger.warning(f"[SessionService] [{session_id}] Failed to delete checkpoint: {e}")

        logger.info(f"[SessionService] [{session_id}] Session deleted: {result}")
        return result

    @staticmethod
    async def get_layer_reports(session_id: str, layer: int) -> LayerReportsResponse:
        """
        Get reports for a specific layer.

        Args:
            session_id: Session identifier
            layer: Layer number (1, 2, or 3)

        Returns:
            LayerReportsResponse with reports data
        """
        data = await checkpoint_service.get_layer_reports(session_id, layer)
        return LayerReportsResponse(
            layer=data["layer"],
            reports=data["reports"],
            completed=data["completed"],
            stats=data["stats"],
        )


# Singleton instance
session_service = SessionService()


__all__ = ["SessionService", "session_service", "LayerReportsResponse"]