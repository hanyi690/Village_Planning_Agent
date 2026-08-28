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

from app.application.projections.models import TaskStatus
from app.infrastructure.events import EventRepository
from app.application.queries.checkpoint import checkpoint_service
from app.database.operations import (
    create_planning_session_async,
    get_planning_session_async,
    update_planning_session_async,
    delete_planning_session_async,
)

logger = logging.getLogger(__name__)


async def _cancel_session_tasks(session_id: str) -> bool:
    try:
        from app.bootstrap.composition import CompositionRoot
        sup = CompositionRoot.get_task_supervisor()
        await sup.cancel_session(session_id)
        return True
    except Exception as e:
        logger.warning(f"[SessionService] [{session_id}] task cancel failed: {e}")
        return False


async def _clear_session_context(session_id: str) -> bool:
    try:
        from app.infrastructure.context_runtime.manager import (
            _context_cache,
            invalidate_planning_context,
        )
        invalidate_planning_context(session_id)
        _context_cache.pop(session_id, None)
        return True
    except Exception as e:
        logger.warning(f"[SessionService] [{session_id}] context clear failed: {e}")
        return False


async def _delete_session_bundle(session_id: str) -> bool:
    try:
        from app.application.sessions.session_bundle import invalidate_session_bundle
        invalidate_session_bundle(session_id)
        return True
    except Exception as e:
        logger.warning(f"[SessionService] [{session_id}] bundle delete failed: {e}")
        return False


async def _delete_session_kg(session_id: str) -> bool:
    try:
        from app.infrastructure.kg.manager import get_kg_manager
        get_kg_manager().remove_session(session_id)
        from app.modules.evidence.application import clear_session_evidence_cache
        clear_session_evidence_cache(session_id)
        return True
    except Exception as e:
        logger.warning(f"[SessionService] [{session_id}] KG delete failed: {e}")
        return False


async def _delete_session_artifacts(session_id: str) -> bool:
    try:
        import shutil
        from app.infrastructure.paths import run_tmp_root

        root = run_tmp_root()
        artifact_dir = root / session_id
        if artifact_dir.exists():
            shutil.rmtree(artifact_dir)
        cas_refs_dir = root / "runs" / session_id
        if cas_refs_dir.exists():
            shutil.rmtree(cas_refs_dir)
        return True
    except Exception as e:
        logger.warning(f"[SessionService] [{session_id}] artifact delete failed: {e}")
        return False


async def _delete_session_checkpoint(session_id: str) -> bool:
    try:
        from app.database.engine import get_global_checkpointer
        checkpointer = await get_global_checkpointer()
        if hasattr(checkpointer, "adelete_thread"):
            await checkpointer.adelete_thread(session_id)
            return True
        return True
    except Exception as e:
        logger.warning(f"[SessionService] [{session_id}] checkpoint delete failed: {e}")
        return False


async def _clear_session_sse(session_id: str) -> bool:
    try:
        await EventRepository.clear(session_id)
        return True
    except Exception as e:
        logger.warning(f"[SessionService] [{session_id}] SSE clear failed: {e}")
        return False


async def _clear_session_evidence(session_id: str) -> bool:
    try:
        from app.modules.evidence.application import _EVIDENCE_CACHE
        for key in [k for k in _EVIDENCE_CACHE if k[0] == session_id]:
            _EVIDENCE_CACHE.pop(key, None)
        return True
    except Exception as e:
        logger.warning(f"[SessionService] [{session_id}] evidence cache clear failed: {e}")
        return False


async def _clear_provider_failures(session_id: str) -> bool:
    try:
        from app.infrastructure.evidence_runtime.dimension_runtime import reset_provider_failure
        reset_provider_failure(session_id)
        return True
    except Exception as e:
        logger.warning(f"[SessionService] [{session_id}] provider failure reset failed: {e}")
        return False


async def _delete_session_kg_memory(session_id: str) -> bool:
    try:
        import glob
        import os
        import shutil
        from app.infrastructure.kg.memory import get_memory_dir

        base = get_memory_dir()
        for f in glob.glob(str(base / f"{session_id}_round_*.json")):
            os.remove(f)
        subdir = base / session_id
        if subdir.exists():
            shutil.rmtree(subdir)
        return True
    except Exception as e:
        logger.warning(f"[SessionService] [{session_id}] kg_memory delete failed: {e}")
        return False


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
    async def delete_session(session_id: str, project_name: str = None) -> Dict[str, bool]:
        """
        Delete a session completely.

        Removes session from:
        1. Running planning tasks (TaskSupervisor)
        2. PlanningContext cache
        3. Session bundle cache
        4. Knowledge graph
        5. Artifact files on disk
        6. LangGraph checkpoint thread
        7. SSE session data
        8. Uploaded files
        9. Dimension reports
         10. UI sessions
         11. Database record
         12. Evidence cache
         13. Provider-failure circuit breaker
         14. kg_memory round files
         15. CAS named refs (runs/<session_id>)

        Args:
            session_id: Session identifier
            project_name: Kept for backward API compatibility (no longer used)

        Returns:
            Dict with deletion status for each category
        """
        result: Dict[str, bool] = {}

        for key, coro in [
            ("tasks", _cancel_session_tasks(session_id)),
            ("context", _clear_session_context(session_id)),
            ("bundle", _delete_session_bundle(session_id)),
            ("kg", _delete_session_kg(session_id)),
            ("artifacts", _delete_session_artifacts(session_id)),
            ("checkpoint", _delete_session_checkpoint(session_id)),
            ("sse", _clear_session_sse(session_id)),
            ("evidence_cache", _clear_session_evidence(session_id)),
            ("provider_failures", _clear_provider_failures(session_id)),
            ("kg_memory", _delete_session_kg_memory(session_id)),
        ]:
            try:
                result[key] = await coro
            except Exception as e:
                logger.warning(f"[SessionService] [{session_id}] {key} cleanup failed: {e}")
                result[key] = False

        try:
            from app.database.operations import delete_uploaded_files_async
            file_count = await delete_uploaded_files_async(session_id)
            result["uploaded_files"] = True
            logger.info(f"[SessionService] [{session_id}] Deleted {file_count} uploaded files")
        except Exception as e:
            logger.warning(f"[SessionService] [{session_id}] Uploaded files cleanup warning: {e}")
            result["uploaded_files"] = False

        try:
            from app.infrastructure.reports.report_store import ReportStore
            store = ReportStore.get_instance()
            report_count = await store.delete_session_reports(session_id)
            result["dimension_reports"] = True
            logger.info(f"[SessionService] [{session_id}] Deleted {report_count} dimension reports")
        except Exception as e:
            logger.warning(f"[SessionService] [{session_id}] Dimension reports cleanup warning: {e}")
            result["dimension_reports"] = False

        try:
            from app.database.operations import delete_ui_session_async, list_ui_sessions_async
            ui_sessions = await list_ui_sessions_async(task_id=session_id)
            for ui_session in ui_sessions:
                await delete_ui_session_async(ui_session["conversation_id"])
            result["ui_sessions"] = True
            logger.info(f"[SessionService] [{session_id}] Deleted {len(ui_sessions)} UI sessions")
        except Exception as e:
            logger.warning(f"[SessionService] [{session_id}] UI sessions cleanup warning: {e}")
            result["ui_sessions"] = False

        result["database"] = await delete_planning_session_async(session_id)

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
