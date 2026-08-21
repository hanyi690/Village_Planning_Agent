"""Persisted planning history transport."""

from __future__ import annotations

from collections import defaultdict

from fastapi import APIRouter

from app.api.v1.contracts import HistoryProject, HistoryProjectList, HistorySession
from app.database.operations import list_planning_sessions_async, list_projects_async


router = APIRouter(prefix="/api/v1", tags=["Stable v1"])


@router.get(
    "/projects",
    response_model=HistoryProjectList,
    summary="List persisted planning projects and sessions",
)
async def list_projects() -> HistoryProjectList:
    """Return small, restart-safe metadata for the planning history sidebar.

    The database layer already owns session persistence. This endpoint only
    exposes identifiers and timestamps; user-provided village text, task text,
    constraints, and uploaded content remain server-side.
    """

    project_rows = await list_projects_async()
    session_rows = await list_planning_sessions_async(limit=1000)
    sessions_by_project: dict[str, list[HistorySession]] = defaultdict(list)

    for row in session_rows:
        project_name = str(row.get("project_name") or "").strip()
        session_id = str(row.get("session_id") or "").strip()
        timestamp = str(row.get("created_at") or "").strip()
        if not project_name or not session_id or not timestamp:
            continue
        sessions_by_project[project_name].append(
            HistorySession(
                session_id=session_id,
                timestamp=timestamp,
                has_final_report=bool(row.get("completed_at")),
            )
        )

    projects: list[HistoryProject] = []
    for row in project_rows:
        project_name = str(row.get("name") or "").strip()
        if not project_name:
            continue
        sessions = sorted(
            sessions_by_project.get(project_name, []),
            key=lambda item: item.timestamp,
            reverse=True,
        )
        projects.append(
            HistoryProject(
                name=project_name,
                display_name=str(row.get("display_name") or project_name),
                session_count=len(sessions),
                sessions=sessions,
            )
        )

    return HistoryProjectList(projects=projects)


__all__ = ["list_projects", "router"]
