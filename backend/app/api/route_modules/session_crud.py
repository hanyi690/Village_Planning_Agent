"""Session CRUD routes - create, status, delete sessions."""

import asyncio
import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from app.api.schemas import TaskStatus, ImageData
from app.api.session_routes import _launch_background, _process_uploaded_file_db
from app.agent.plan_state.state import state_to_ui_status
from app.database.operations import (
    create_planning_session_async,
    update_planning_session_async,
)
from app.services.runtime import PlanningRuntimeService
from app.services.sse import sse_manager
from app.agent.bootstrap.phase_machine import get_layer_dimensions, get_layer_name
from app.utils.sse_publisher import SSEPublisher

logger = logging.getLogger(__name__)
router = APIRouter()


class SessionCreateRequest(BaseModel):
    """创建会话请求"""
    project_name: str = Field(..., description="项目名称")
    village_data: str = Field(..., description="村庄基础数据")
    village_name: str = Field("", description="村庄名称")
    task_description: str = Field(default="制定村庄发展规划", description="任务描述")
    constraints: str = Field(default="无特殊约束", description="约束条件")
    step_mode: bool = Field(default=False, description="分步执行模式")
    images: Optional[List[ImageData]] = Field(None, description="图片列表")


class SessionCreateResponse(BaseModel):
    """创建会话响应"""
    session_id: str
    stream_url: str
    status: str = "running"


@router.post("/api/sessions", response_model=SessionCreateResponse)
async def create_session(
    background_tasks: BackgroundTasks,
    project_name: str = Form(..., description="项目名称"),
    village_name: str = Form("", description="村庄名称"),
    province: str = Form("", description="省份"),
    city: str = Form("", description="地级市"),
    county: str = Form("", description="县/区"),
    township: str = Form("", description="乡镇"),
    planning_period: str = Form("2022-2035年", description="规划期限"),
    task_description: str = Form("制定村庄发展规划", description="任务描述"),
    constraints: str = Form("无特殊约束", description="约束条件"),
    step_mode: bool = Form(False, description="分步执行模式"),
    rag_enabled: bool = Form(True, description="启用 RAG 知识检索（实验对比用）"),
    rag_layer_config: str = Form("", description="Layer-level RAG config (JSON, e.g. '{\"1\":true,\"2\":false,\"3\":true}')"),
    village_data: str = Form("", description="村庄基础数据（文本）"),
    village_data_files: List[UploadFile] = File(None, description="村庄数据文件"),
    task_files: List[UploadFile] = File(None, description="任务描述文件"),
    constraint_files: List[UploadFile] = File(None, description="约束条件文件"),
):
    """创建新规划会话 - 支持 multipart/form-data 文件上传（按来源区分）"""
    if not project_name.strip():
        raise HTTPException(status_code=400, detail="项目名称不能为空")

    # 解析 rag_layer_config JSON
    parsed_rag_layer_config = None
    if rag_layer_config.strip():
        try:
            parsed_rag_layer_config = json.loads(rag_layer_config)
            # 转换 key 为 int
            parsed_rag_layer_config = {int(k): v for k, v in parsed_rag_layer_config.items()}
        except json.JSONDecodeError:
            logger.warning(f"[create_session] Invalid rag_layer_config JSON: {rag_layer_config}")

    session_id = str(uuid4())
    uploaded_files: List[Dict] = []
    parsed_content = village_data
    user_uploaded_gis_data: Dict[str, Any] = {}

    # Persist the parent row before uploaded_files because uploads carry an
    # enforced foreign key to planning_sessions.
    await create_planning_session_async({
        "session_id": session_id,
        "project_name": project_name,
        "village_name": village_name,
        "province": province,
        "city": city,
        "county": county,
        "township": township,
        "planning_period": planning_period,
        "village_data": parsed_content,
        "task_description": task_description,
        "constraints": constraints,
    })

    # Process uploaded files and store to database
    file_groups = [
        (village_data_files, "village_data"),
        (task_files, "task_description"),
        (constraint_files, "constraint"),
    ]

    for file_group, file_category in file_groups:
        if not file_group:
            continue
        results = await asyncio.gather(*[
            _process_uploaded_file_db(f, session_id, file_category) for f in file_group
        ])

        for r in results:
            uploaded_files.append({
                "id": r["id"],
                "filename": r["filename"],
                "file_category": r["file_category"],
                "file_type": r["file_type"],
                "size_bytes": r["size_bytes"],
                "geometry_audit": r.get("geometry_audit"),
            })

            # Merge parsed text into initial state
            if file_category == "village_data" and r.get("parsed_text"):
                parsed_content += f"\n\n--- 村庄数据: {r['filename']} ---\n{r['parsed_text']}"
            elif file_category == "task_description" and r.get("parsed_text"):
                if not task_description or task_description == "制定村庄发展规划":
                    task_description = r["parsed_text"].strip()
            elif file_category == "constraint" and r.get("parsed_text"):
                if not constraints or constraints == "无特殊约束":
                    constraints = r["parsed_text"].strip()

            # Collect GeoJSON data for GIS pipeline
            if r.get("gis_data"):
                dtype = r.get("gis_data_type")
                if dtype:
                    user_uploaded_gis_data[dtype] = r["gis_data"]
                else:
                    fname = r.get("filename", "").lower()
                    for target_type, keyword in [
                        ("boundary", "boundary"),
                        ("admin_boundary_line", "admin_boundary"),
                        ("landuse_current", "landuse"),
                        ("road", "road"),
                        ("annotation", "annotation"),
                        ("water", "water"),
                        ("construction_zone", "construction"),
                        ("farmland_protection", "farmland"),
                        ("ecological_protection", "ecological"),
                        ("historical_protection", "historical"),
                        ("geological_hazard_points", "geological_hazard"),
                    ]:
                        if keyword in fname:
                            user_uploaded_gis_data[target_type] = r["gis_data"]
                            break

    # 验证数据
    if len(parsed_content.strip()) < 10:
        raise HTTPException(status_code=400, detail="村庄数据不能为空或过短")

    await update_planning_session_async(
        session_id,
        {
            "village_data": parsed_content,
            "task_description": task_description,
            "constraints": constraints,
        },
    )

    from app.agent.plan_state.state_factory import StateFactory
    initial_state = StateFactory.create(
        project_name=project_name,
        village_data=parsed_content,
        village_name=village_name,
        province=province,
        city=city,
        county=county,
        township=township,
        planning_period=planning_period,
        task_description=task_description,
        constraints=constraints,
        session_id=session_id,
        stream_mode=True,
        step_mode=step_mode,
        rag_enabled=rag_enabled,
        rag_layer_config=parsed_rag_layer_config,
        uploaded_files=uploaded_files if uploaded_files else None,
        user_uploaded_gis_data=user_uploaded_gis_data if user_uploaded_gis_data else None,
    )

    sse_manager.init_session(session_id, {
        "session_id": session_id,
        "project_name": project_name,
        "created_at": datetime.now().isoformat(),
    })
    sse_manager.set_execution_active(session_id, True)

    await PlanningRuntimeService.ensure_initialized()

    SSEPublisher.send_layer_start(session_id, 1, get_layer_name(1), len(get_layer_dimensions(1)))

    background_tasks.add_task(PlanningRuntimeService._trigger_planning_execution, session_id, initial_state)

    return SessionCreateResponse(session_id=session_id,
        stream_url=f"/api/sessions/{session_id}/stream", status=TaskStatus.running)


@router.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str):
    """删除会话"""
    from app.services.session import session_service
    result = await session_service.delete_session(session_id)
    return {"message": f"Session {session_id} deleted", "deleted_checkpoints": result.get("checkpoint", False)}


@router.get("/api/sessions/{session_id}/status")
async def get_session_status(session_id: str):
    """Get session status"""
    from app.database.operations import get_planning_session_async
    db_session = await get_planning_session_async(session_id)
    if not db_session:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    checkpoint_state = await PlanningRuntimeService.aget_state(session_id)
    state = dict(checkpoint_state.values) if checkpoint_state and checkpoint_state.values else {}
    # Detect interrupt state from snapshot.tasks with non-empty interrupts.
    # snapshot.next is truthy after aupdate_state(as_node="__start__") —
    # it means nodes are scheduled, NOT that the graph is interrupted.
    # Correct check: any PregelTask with non-empty interrupts.
    is_interrupted = bool(
        checkpoint_state
        and checkpoint_state.tasks
        and any(getattr(t, 'interrupts', None) for t in checkpoint_state.tasks)
    )
    return state_to_ui_status(state, db_session, is_interrupted=is_interrupted)


__all__ = ["router"]