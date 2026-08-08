"""P1: session creation must roll back DB + files on downstream failure."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

# Import session_routes first to resolve the circular import between
# session_routes (imports router at line 313) and session_crud (imports
# _process_uploaded_file_db at line 14). Loading session_routes first
# ensures session_crud is fully initialized.
import app.api.session_routes  # noqa: F401


@pytest.mark.asyncio
async def test_create_session_rolls_back_db_on_validation_failure(monkeypatch):
    """When validation fails after DB insert, the DB record must be deleted."""
    from app.api.route_modules import session_crud

    deleted = {"db": False}

    async def fake_create_db(data):
        return True

    async def fake_delete_db(session_id):
        deleted["db"] = True
        return True

    async def fake_update_db(session_id, data):
        return True

    monkeypatch.setattr(session_crud, "create_planning_session_async", fake_create_db)
    monkeypatch.setattr(session_crud, "delete_planning_session_async", fake_delete_db)
    monkeypatch.setattr(session_crud, "update_planning_session_async", fake_update_db)

    monkeypatch.setattr(
        "app.api.route_modules.session_crud._process_uploaded_file_db",
        AsyncMock(return_value={"id": "f1", "filename": "test.txt", "file_category": "village_data", "file_type": "text/plain", "size_bytes": 100, "parsed_text": "", "gis_data": None, "gis_data_type": None, "geometry_audit": None}),
    )

    from fastapi import HTTPException
    from fastapi.background import BackgroundTasks

    bt = BackgroundTasks()

    with pytest.raises(HTTPException) as exc_info:
        await session_crud.create_session(
            background_tasks=bt,
            project_name="test",
            village_name="",
            province="",
            city="",
            county="",
            township="",
            planning_period="2022-2035",
            task_description="test",
            constraints="test",
            step_mode=False,
            rag_enabled=True,
            rag_layer_config="",
            village_data="short",
            village_data_files=None,
            task_files=None,
            constraint_files=None,
        )

    assert exc_info.value.status_code == 400
    assert deleted["db"] is True, "DB record must be deleted on validation failure"


@pytest.mark.asyncio
async def test_create_session_rolls_back_db_on_upload_failure(monkeypatch):
    """When file upload fails after DB insert, the DB record must be deleted."""
    from app.api.route_modules import session_crud

    deleted = {"db": False}

    async def fake_create_db(data):
        return True

    async def fake_delete_db(session_id):
        deleted["db"] = True
        return True

    async def fake_update_db(session_id, data):
        return True

    monkeypatch.setattr(session_crud, "create_planning_session_async", fake_create_db)
    monkeypatch.setattr(session_crud, "delete_planning_session_async", fake_delete_db)
    monkeypatch.setattr(session_crud, "update_planning_session_async", fake_update_db)

    async def boom_upload(f, session_id, file_category):
        raise RuntimeError("upload failed")

    monkeypatch.setattr(
        "app.api.route_modules.session_crud._process_uploaded_file_db",
        boom_upload,
    )

    from fastapi import BackgroundTasks
    from unittest.mock import MagicMock

    mock_file = MagicMock()
    mock_file.filename = "test.geojson"

    bt = BackgroundTasks()

    with pytest.raises(RuntimeError, match="upload failed"):
        await session_crud.create_session(
            background_tasks=bt,
            project_name="test",
            village_name="",
            province="",
            city="",
            county="",
            township="",
            planning_period="2022-2035",
            task_description="test",
            constraints="test",
            step_mode=False,
            rag_enabled=True,
            rag_layer_config="",
            village_data="long enough data to pass validation",
            village_data_files=[mock_file],
            task_files=None,
            constraint_files=None,
        )

    assert deleted["db"] is True, "DB record must be deleted on upload failure"
