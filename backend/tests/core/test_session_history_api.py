"""Tests for the persisted planning history transport."""

from __future__ import annotations

import pytest

from app.api.v1.routes import history


@pytest.mark.asyncio
async def test_list_projects_returns_minimal_grouped_session_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_projects() -> list[dict[str, object]]:
        return [
            {"name": "金田村规划", "display_name": "金田村", "session_count": 9},
        ]

    async def fake_sessions(*, limit: int) -> list[dict[str, object]]:
        assert limit == 1000
        return [
            {
                "project_name": "金田村规划",
                "session_id": "session-new",
                "created_at": "2026-08-19T12:00:00",
                "completed_at": "2026-08-19T12:30:00",
                "village_data": "must not be exposed",
                "task_description": "must not be exposed",
                "constraints": "must not be exposed",
            },
            {
                "project_name": "金田村规划",
                "session_id": "session-old",
                "created_at": "2026-08-18T12:00:00",
                "completed_at": None,
            },
        ]

    monkeypatch.setattr(history, "list_projects_async", fake_projects)
    monkeypatch.setattr(history, "list_planning_sessions_async", fake_sessions)

    response = await history.list_projects()

    assert response.schema_version == "1.0"
    assert response.projects[0].session_count == 2
    assert [item.session_id for item in response.projects[0].sessions] == [
        "session-new",
        "session-old",
    ]
    assert response.projects[0].sessions[0].has_final_report is True
    assert response.projects[0].sessions[1].has_final_report is False
    assert "village_data" not in response.projects[0].model_dump()


@pytest.mark.asyncio
async def test_list_projects_returns_empty_project_list(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_projects() -> list[dict[str, object]]:
        return []

    async def fake_sessions(*, limit: int) -> list[dict[str, object]]:
        return []

    monkeypatch.setattr(history, "list_projects_async", fake_projects)
    monkeypatch.setattr(history, "list_planning_sessions_async", fake_sessions)

    response = await history.list_projects()

    assert response.model_dump(mode="json") == {
        "schema_version": "1.0",
        "projects": [],
    }
