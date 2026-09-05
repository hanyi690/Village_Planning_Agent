"""HTTP form adapter for the application create-session command."""

from __future__ import annotations

import json

from fastapi import File, Form, HTTPException, UploadFile

from app.api.v1.contracts import SessionCreated
from app.application.commands.create_session import (
    CreateSessionCommand,
    CreateSessionError,
    CreateSessionValidationError,
    create_session_service,
)


async def create_session(
    project_name: str = Form(...),
    village_name: str = Form(""),
    province: str = Form(""),
    city: str = Form(""),
    county: str = Form(""),
    township: str = Form(""),
    planning_period: str = Form("2022-2035年"),
    task_description: str = Form("制定村庄发展规划"),
    constraints: str = Form("无特殊约束"),
    step_mode: bool = Form(False),
    rag_enabled: bool | None = Form(None),
    rag_layer_config: str = Form(""),
    village_data: str = Form(""),
    village_data_files: list[UploadFile] | None = File(None),
    village_data_layer_refs: str = Form(""),
    boundary_scope_file_index: int | None = Form(None),
    boundary_scope_mode: str = Form(""),
    task_files: list[UploadFile] | None = File(None),
    constraint_files: list[UploadFile] | None = File(None),
) -> SessionCreated:
    try:
        raw_config = json.loads(rag_layer_config) if rag_layer_config.strip() else {}
        if not isinstance(raw_config, dict):
            raise ValueError("config must be an object")
        parsed_layer_config = {int(key): bool(value) for key, value in raw_config.items()}
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail="rag_layer_config 必须是 JSON 对象") from exc

    try:
        raw_layer_refs = json.loads(village_data_layer_refs) if village_data_layer_refs.strip() else []
        if not isinstance(raw_layer_refs, list) or not all(
            isinstance(value, str) and value.strip() for value in raw_layer_refs
        ):
            raise ValueError("village_data_layer_refs must be a non-empty-string array")
        parsed_layer_refs = tuple(value.strip() for value in raw_layer_refs)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail="village_data_layer_refs 必须是字符串数组") from exc
    if boundary_scope_mode and boundary_scope_file_index is None:
        raise HTTPException(status_code=400, detail="boundary_scope_file_index is required")
    if len(parsed_layer_refs) > len(village_data_files or ()):
        raise HTTPException(status_code=400, detail="village_data_layer_refs 超出 village_data_files 数量")
    if boundary_scope_file_index is not None and (
        boundary_scope_file_index < 0
        or boundary_scope_file_index >= len(village_data_files or ())
    ):
        raise HTTPException(status_code=400, detail="boundary_scope_file_index 超出 village_data_files 范围")

    command = CreateSessionCommand(
        project_name=project_name,
        village_name=village_name,
        province=province,
        city=city,
        county=county,
        township=township,
        planning_period=planning_period,
        task_description=task_description,
        constraints=constraints,
        step_mode=step_mode,
        rag_enabled=rag_enabled,
        rag_layer_config=parsed_layer_config,
        village_data=village_data,
        village_data_files=tuple(village_data_files or ()),
        village_data_layer_refs=parsed_layer_refs,
        boundary_scope_file_index=boundary_scope_file_index,
        boundary_scope_mode=boundary_scope_mode,
        task_files=tuple(task_files or ()),
        constraint_files=tuple(constraint_files or ()),
    )
    try:
        result = await create_session_service.execute(command)
    except CreateSessionValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except CreateSessionError as exc:
        raise HTTPException(status_code=500, detail="session startup failed") from exc
    return SessionCreated.model_validate(result.model_dump(mode="python"))


__all__ = ["create_session"]
