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

from backend.schemas import TaskStatus, SessionStatusResponse
from backend.services.sse_manager import sse_manager
from backend.services.checkpoint_service import checkpoint_service
from backend.database.operations_async import (
    create_planning_session_async,
    get_planning_session_async,
    update_planning_session_async,
    delete_planning_session_async,
    delete_ui_messages_async,
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
    async def get_session_status(session_id: str) -> Optional[SessionStatusResponse]:
        """
        Get session status from checkpoint and database.

        Args:
            session_id: Session identifier

        Returns:
            SessionStatusResponse or None if not found
        """
        # Get from database for basic info
        db_session = await get_planning_session_async(session_id)
        if not db_session:
            return None

        # Get from checkpoint for execution state (single query)
        state = await checkpoint_service.get_state(session_id)
        completion_status = await checkpoint_service.get_completion_status(session_id, state)

        # Calculate progress
        from backend.utils.progress_helper import calculate_progress
        progress = calculate_progress(
            state.get("phase", "init") if state else "init",
            completion_status if state else {}
        )

        return SessionStatusResponse(
            session_id=session_id,
            status=db_session.get("status", TaskStatus.running),
            current_layer=state.get("current_layer") if state else None,
            previous_layer=state.get("previous_layer") if state else None,
            created_at=db_session.get("created_at"),
            progress=progress,
            layer_1_completed=completion_status.get("layer1", False),
            layer_2_completed=completion_status.get("layer2", False),
            layer_3_completed=completion_status.get("layer3", False),
            pause_after_step=state.get("pause_after_step", False) if state else False,
            execution_complete=state.get("phase") == "completed" if state else False,
            execution_error=db_session.get("execution_error"),
        )

    @staticmethod
    async def delete_session(session_id: str) -> Dict[str, bool]:
        """
        Delete a session completely.

        Removes session from:
        1. Memory (via SSEManager)
        2. Database (planning_sessions table)
        3. UI messages (ui_messages table)
        4. LangGraph checkpoints

        Args:
            session_id: Session identifier

        Returns:
            Dict with deletion status for each category
        """
        result = {
            "memory": False,
            "database": False,
            "ui_messages": False,
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

        # 3. Delete UI messages
        try:
            await delete_ui_messages_async(session_id)
            result["ui_messages"] = True
        except Exception as e:
            logger.warning(f"[SessionService] [{session_id}] Failed to delete UI messages: {e}")

        # 4. Delete LangGraph checkpoint
        if project_name:
            try:
                from src.orchestration.main_graph import create_unified_planning_graph
                from backend.database.engine import get_global_checkpointer

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


__all__ = ["SessionService", "session_service", "SessionStatusResponse", "LayerReportsResponse"]