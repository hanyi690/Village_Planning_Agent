"""
Session Routes - 统一的会话 API (新架构)

7 个核心端点：
1. POST /api/sessions - 创建会话
2. GET /api/sessions/{id}/stream - SSE 流
3. GET /api/sessions/{id}/sync - 断线重连
4. POST /api/sessions/{id}/feedback - 反馈接口
5. GET /api/sessions/{id}/checkpoints - 检查点列表
6. POST /api/sessions/{id}/resume/{checkpoint_id} - 从检查点恢复
7. GET /api/sessions/{id}/reports/{dim_key} - 报告全文

架构原则：
- SSE 单通道：所有数据通过 SSE 流推送
- 状态极简：Checkpoint 为唯一数据源
- 配置驱动：维度配置从 YAML 加载
- 级联修复：反馈自动触发依赖维度重分析
"""

import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.api.schemas import TaskStatus, ImageData, UploadedFileMeta
from app.services.runtime import PlanningRuntimeService
from app.services.report_store import ReportStore
from app.database.models import DimensionReport
from app.database.operations import (
    create_planning_session_async,
    get_dimension_revisions_async,
    list_planning_sessions_async,
    list_projects_async,
    list_project_sessions_async,
)
from app.services.sse import sse_manager
from app.services.checkpoint import checkpoint_service
from app.agent.state import get_layer_dimensions, get_layer_name, state_to_ui_status, get_next_phase, _phase_to_layer
from app.utils.sse_publisher import SSEPublisher

logger = logging.getLogger(__name__)
router = APIRouter()


async def _get_report_from_db(session_id: str, dim_key: str) -> dict:
    """Helper to fetch full report from database.

    Returns:
        dict with layer, content, knowledge_sources or raises HTTPException
    """
    store = ReportStore.get_instance()
    report = await store.get_latest_report(session_id, dim_key)

    if not report:
        raise HTTPException(status_code=404, detail=f"Report not found: {dim_key}")

    return report


# ============================================
# Module-level file processing helpers
# ============================================

import tempfile
from app.database.operations import create_uploaded_file_async
from app.utils.document_loader import classify_file_type, MarkItDownLoader


def _infer_geojson_data_type(geojson: Dict[str, Any]) -> Optional[str]:
    """Infer GIS data type from GeoJSON properties."""
    if not geojson or geojson.get("type") != "FeatureCollection":
        return None

    features = geojson.get("features", [])
    if not features:
        return None

    # Check first feature properties
    props = features[0].get("properties", {})

    # Common property keys for data type inference
    name = props.get("name", "").lower()
    layer = props.get("layer", "").lower()

    if "边界" in name or "boundary" in layer:
        return "boundary"
    if "道路" in name or "road" in layer:
        return "road"
    if "水" in name or "water" in layer or "河流" in name:
        return "water"
    if "住宅" in name or "residential" in layer:
        return "residential"

    return None


async def _parse_file_in_memory(
    file: UploadFile,
    content: bytes,
) -> Dict[str, Any]:
    """Parse uploaded file content in memory without writing to disk.

    Returns:
        Dict with parsed_text, gis_data, gis_data_type, parse_status, parse_error
    """
    filename = file.filename or "unknown"
    file_type = classify_file_type(filename)

    result = {
        "file_type": file_type,
        "parsed_text": None,
        "gis_data": None,
        "gis_data_type": None,
        "parse_status": "pending",
        "parse_error": None,
    }

    try:
        if file_type == "geojson":
            # Parse GeoJSON directly from bytes
            try:
                geojson = json.loads(content.decode('utf-8'))
                if geojson.get("type") == "FeatureCollection":
                    result["gis_data"] = geojson
                    result["gis_data_type"] = _infer_geojson_data_type(geojson)
                    result["parse_status"] = "success"
                else:
                    result["parse_status"] = "failed"
                    result["parse_error"] = "Not a valid GeoJSON FeatureCollection"
            except (json.JSONDecodeError, UnicodeDecodeError) as e:
                result["parse_status"] = "failed"
                result["parse_error"] = f"GeoJSON parse error: {e}"

        elif file_type == "document":
            # Write to temporary file for MarkItDown parsing, then delete
            with tempfile.NamedTemporaryFile(suffix=Path(filename).suffix, delete=False) as tmp:
                tmp.write(content)
                tmp_path = Path(tmp.name)

            try:
                loader = MarkItDownLoader(tmp_path)
                docs = loader.load()
                if docs:
                    result["parsed_text"] = docs[0].page_content
                    result["parse_status"] = "success"
                else:
                    result["parse_status"] = "failed"
                    result["parse_error"] = "No content extracted"
            finally:
                # Immediately delete temp file
                tmp_path.unlink(missing_ok=True)
        else:
            # Other file types - mark as success (raw storage)
            result["parse_status"] = "success"

    except Exception as e:
        logger.warning(f"[SessionRoutes] File parse failed {filename}: {e}")
        result["parse_status"] = "failed"
        result["parse_error"] = str(e)

    return result


async def _process_uploaded_file_db(
    file: UploadFile,
    session_id: str,
    file_category: str,
) -> Dict[str, Any]:
    """Process single uploaded file: parse in memory, store to database.

    Args:
        file: FastAPI UploadFile object
        session_id: Session identifier
        file_category: "village_data", "task_description", or "constraint"

    Returns:
        Dict with file metadata and parsed content
    """
    filename = file.filename or "unknown"
    content = await file.read()

    # Parse file in memory
    parse_result = await _parse_file_in_memory(file, content)

    # Store to database
    file_id = await create_uploaded_file_async(
        session_id=session_id,
        file_category=file_category,
        file_type=parse_result["file_type"],
        filename=filename,
        original_filename=filename,
        file_size=len(content),
        content_type=file.content_type or "application/octet-stream",
        parsed_text=parse_result["parsed_text"],
        gis_data=parse_result["gis_data"],
        gis_data_type=parse_result["gis_data_type"],
        parse_status=parse_result["parse_status"],
        parse_error=parse_result["parse_error"],
    )

    logger.info(f"[SessionRoutes] Stored file {filename} (id={file_id}) in database")

    return {
        "id": file_id,
        "filename": filename,
        "file_category": file_category,
        "file_type": parse_result["file_type"],
        "size_bytes": len(content),
        "parse_status": parse_result["parse_status"],
        "parsed_text": parse_result["parsed_text"],
        "gis_data": parse_result["gis_data"],
        "gis_data_type": parse_result["gis_data_type"],
    }


class FeedbackRequest(BaseModel):
    """反馈请求"""
    feedback: Optional[str] = Field(None, description="反馈内容")
    dimensions: Optional[List[str]] = Field(None, description="需修订的维度列表")
    message: Optional[str] = Field(None, description="对话消息")
    approve: bool = Field(False, description="批准当前层级继续")


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

    # 验证数据
    if len(parsed_content.strip()) < 10:
        raise HTTPException(status_code=400, detail="村庄数据不能为空或过短")

    initial_state = PlanningRuntimeService.build_initial_state(
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
    )

    sse_manager.init_session(session_id, {
        "session_id": session_id,
        "project_name": project_name,
        "created_at": datetime.now().isoformat(),
    })
    sse_manager.set_execution_active(session_id, True)

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

    await PlanningRuntimeService.ensure_initialized()

    SSEPublisher.send_layer_start(session_id, 1, get_layer_name(1), len(get_layer_dimensions(1)))

    background_tasks.add_task(PlanningRuntimeService._trigger_planning_execution, session_id, initial_state)

    return SessionCreateResponse(session_id=session_id,
        stream_url=f"/api/sessions/{session_id}/stream", status=TaskStatus.running)


@router.get("/api/sessions/{session_id}/stream")
async def stream_events(session_id: str):
    """SSE 事件流端点"""
    if not sse_manager.session_exists(session_id):
        from app.database.operations import get_planning_session_async
        rebuilt = await checkpoint_service.rebuild_session_from_db(session_id, get_planning_session_async, sse_manager)
        if not rebuilt:
            raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    async def event_generator():
        queue = await PlanningRuntimeService.subscribe_with_history(session_id)
        try:
            yield sse_manager.format_sse({"type": "connected", "session_id": session_id, "timestamp": datetime.now().isoformat()})

            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=30.0)
                    if event.get("type") in ["completed", "error"]:
                        yield sse_manager.format_sse(event)
                        break
                    yield sse_manager.format_sse(event)
                except asyncio.TimeoutError:
                    yield sse_manager.format_sse({"type": "heartbeat", "timestamp": datetime.now().isoformat()})
        except asyncio.CancelledError:
            pass
        finally:
            await sse_manager.unsubscribe(session_id, queue)

    return StreamingResponse(event_generator(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"})


@router.get("/api/sessions/{session_id}/sync")
async def sync_events(session_id: str, from_seq: int = 0):
    """断线重连同步端点"""
    if not sse_manager.session_exists(session_id):
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    events = sse_manager.get_events_from_seq(session_id, from_seq)
    return {"events": events, "last_seq": sse_manager.get_last_seq(session_id), "from_seq": from_seq}


@router.post("/api/sessions/{session_id}/feedback")
async def submit_feedback(session_id: str, request: FeedbackRequest):
    """提交反馈"""
    state = await PlanningRuntimeService.aget_state_values(session_id)
    if not state:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    if request.approve:
        logger.info("[feedback/approve] session=%s execution_paused=%s phase=%s",
            session_id, state.get("execution_paused"), state.get("phase"))
        # Check if execution is paused (set by layer_completion_check node)
        if not state.get("execution_paused"):
            return {"status": "not_paused", "message": "Execution is not paused, nothing to approve"}

        current_phase = state.get("phase", "layer1")
        current_layer = _phase_to_layer(current_phase) or 1
        next_phase = get_next_phase(current_phase)

        # Single atomic state update: resume execution and advance phase
        await PlanningRuntimeService.aupdate_state(session_id, {
            "execution_paused": False,
            "pause_after_step": False,
            "previous_layer": 0,
            "phase": next_phase or current_phase,
            "need_revision": False,
            "human_feedback": None,
        })

        # Send execution_resumed SSE event before triggering execution
        SSEPublisher.send_execution_resumed(
            session_id=session_id,
            layer=current_layer,
        )

        # Send layer_started for the next layer
        if next_phase and next_phase != "completed":
            next_layer = _phase_to_layer(next_phase)
            if next_layer:
                SSEPublisher.send_layer_start(
                    session_id=session_id,
                    layer=next_layer,
                    layer_name=get_layer_name(next_layer),
                    dimension_count=len(get_layer_dimensions(next_layer))
                )
        asyncio.create_task(PlanningRuntimeService._trigger_planning_execution(session_id))
        return {"status": "approved", "next_phase": next_phase}

    if request.feedback and request.dimensions:
        await PlanningRuntimeService.aupdate_state(session_id, {
            "human_feedback": request.feedback,
            "need_revision": True,
            "revision_target_dimensions": request.dimensions,
            "is_revision": True,
            "revision_feedback": request.feedback,
        })
        asyncio.create_task(PlanningRuntimeService._trigger_planning_execution(session_id))
        return {"status": "revision_started", "dimensions": request.dimensions}

    if request.message:
        from langchain_core.messages import HumanMessage
        await PlanningRuntimeService.aupdate_state(session_id, {"messages": [HumanMessage(content=request.message)]})
        asyncio.create_task(PlanningRuntimeService._trigger_planning_execution(session_id))
        return {"status": "message_accepted"}

    return {"status": "no_action"}


def _is_stable_checkpoint(values: Dict[str, Any]) -> tuple:
    """判断检查点是否为稳定完成快照（非并行中间态）

    并行 Send API 每完成一个节点就保存检查点，这些中间检查点状态不完整。
    只有 layer_completion_check 执行后的检查点才是真正的完成快照。

    Returns:
        (is_stable: bool, kind: str)  kind ∈ {"layer", "revision", "completed", "intermediate"}
    """
    if not values:
        return False, "intermediate"
    if values.get("phase") == "completed":
        return True, "completed"
    if (values.get("last_revised_dimensions")
            and not values.get("is_revision", False)):
        return True, "revision"
    if (values.get("pause_after_step")
            and values.get("previous_layer", 0) > 0
            and values.get("execution_paused", False)):
        return True, "layer"
    return False, "intermediate"


@router.get("/api/sessions/{session_id}/checkpoints")
async def get_checkpoints(session_id: str):
    """获取检查点列表，标记稳定完成检查点"""
    checkpoints = []
    async for snapshot in PlanningRuntimeService.aget_state_history(session_id):
        checkpoint_id = snapshot.config.get("configurable", {}).get("checkpoint_id", "")
        values = dict(snapshot.values) if snapshot.values else {}
        is_stable, kind = _is_stable_checkpoint(values)
        checkpoints.append({
            "checkpoint_id": checkpoint_id,
            "phase": values.get("phase", "init"),
            "layer": values.get("previous_layer", 0),
            "stable": is_stable,
            "kind": kind,
        })
    return {"session_id": session_id, "checkpoints": checkpoints, "count": len(checkpoints)}


@router.post("/api/sessions/{session_id}/resume/{checkpoint_id}")
async def resume_from_checkpoint(session_id: str, checkpoint_id: str):
    """从检查点恢复 — 仅允许稳定完成检查点"""
    target_state = None
    async for snapshot in PlanningRuntimeService.aget_state_history(session_id):
        if snapshot.config.get("configurable", {}).get("checkpoint_id", "") == checkpoint_id:
            target_state = snapshot
            break

    if not target_state:
        raise HTTPException(status_code=404, detail=f"Checkpoint not found: {checkpoint_id}")

    values = dict(target_state.values) if target_state.values else {}
    is_stable, kind = _is_stable_checkpoint(values)
    if not is_stable:
        raise HTTPException(
            status_code=400,
            detail=f"Checkpoint {checkpoint_id} is an intermediate state (kind={kind}), "
                   f"not a stable completion checkpoint. Restore from a 'layer' or 'revision' checkpoint.",
        )

    layer = values.get("previous_layer", 1) or 1
    sse_manager.append_event(session_id, {"type": "resumed", "checkpoint_id": checkpoint_id, "layer": layer, "kind": kind})
    sse_manager.publish_sync(session_id, {"type": "resumed", "checkpoint_id": checkpoint_id})

    asyncio.create_task(PlanningRuntimeService._trigger_planning_execution(
        session_id, checkpoint_id=checkpoint_id
    ))
    return {"status": "resumed", "checkpoint_id": checkpoint_id, "layer": layer, "kind": kind}


@router.get("/api/sessions/{session_id}/reports/{dim_key}")
async def get_dimension_report(session_id: str, dim_key: str, version: Optional[int] = None):
    """获取维度报告全文，支持历史版本查询（?version=N）"""
    if version is not None:
        revisions = await get_dimension_revisions_async(
            session_id=session_id, dimension_key=dim_key, limit=100
        )
        for rev in revisions:
            if rev.get("version") == version:
                return {
                    "session_id": session_id,
                    "dimension_key": dim_key,
                    "layer": rev.get("layer"),
                    "content": rev.get("content"),
                    "version": version,
                    "created_at": rev.get("created_at"),
                }
        raise HTTPException(status_code=404, detail=f"Version {version} not found for dimension: {dim_key}")

    state = await PlanningRuntimeService.aget_state_values(session_id)
    if not state:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    # 从数据库获取报告
    report = await _get_report_from_db(session_id, dim_key)
    return {
        "session_id": session_id,
        "dimension_key": dim_key,
        "layer": report.layer,
        "content": report.content,
        "knowledge_sources": report.knowledge_sources or [],
    }


@router.get("/api/sessions/{session_id}/reports/{dim_key}/versions")
async def get_dimension_report_versions(session_id: str, dim_key: str):
    """列出指定维度所有版本（含当前版本），不再 404"""
    revisions = await get_dimension_revisions_async(
        session_id=session_id, dimension_key=dim_key
    )

    return {
        "session_id": session_id,
        "dimension_key": dim_key,
        "versions": [
            {
                "version": r["version"],
                "layer": r["layer"],
                "created_at": r["created_at"],
                "reason": r["reason"],
            }
            for r in revisions
        ],
    }


@router.get("/api/projects")
async def list_projects():
    """获取项目列表"""
    projects = await list_projects_async()
    return {"projects": projects}


@router.get("/api/projects/{project_name}/sessions")
async def list_project_sessions(project_name: str):
    """获取指定项目的所有会话"""
    sessions = await list_project_sessions_async(project_name)
    return {"sessions": sessions}


@router.get("/api/projects/{project_name}/reports/{dim_key}")
async def get_project_dimension_report(
    project_name: str,
    dim_key: str,
    session_id: Optional[str] = None,
    version: Optional[int] = None,
):
    """通过项目名跨会话查询维度报告，可选指定 session_id 和 version"""
    if version is not None and not session_id:
        raise HTTPException(status_code=400, detail="version parameter requires session_id")

    if session_id:
        if version is not None:
            revisions = await get_dimension_revisions_async(
                session_id=session_id, dimension_key=dim_key, limit=100
            )
            for rev in revisions:
                if rev.get("version") == version:
                    return {
                        "project_name": project_name,
                        "session_id": session_id,
                        "dimension_key": dim_key,
                        "layer": rev.get("layer"),
                        "content": rev.get("content"),
                        "version": version,
                        "created_at": rev.get("created_at"),
                    }
            raise HTTPException(status_code=404, detail=f"Version {version} not found for dimension: {dim_key}")

        state = await PlanningRuntimeService.aget_state_values(session_id)
        if not state:
            raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

        # 从数据库获取报告
        report = await _get_report_from_db(session_id, dim_key)
        return {
            "project_name": project_name,
            "session_id": session_id,
            "dimension_key": dim_key,
            **report,
        }

    sessions = await list_planning_sessions_async(project_name=project_name, limit=1)
    if not sessions:
        raise HTTPException(status_code=404, detail=f"No sessions found for project: {project_name}")

    latest_session_id = sessions[0]["session_id"]

    # 从数据库获取报告
    report = await _get_report_from_db(latest_session_id, dim_key)
    return {
        "project_name": project_name,
        "session_id": latest_session_id,
        "dimension_key": dim_key,
        **report,
    }


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
    return state_to_ui_status(state, db_session)


# ============================================
# RAG Configuration API
# ============================================

class RagConfigRequest(BaseModel):
    """RAG configuration request"""
    rag_layer_config: Optional[Dict[int, bool]] = Field(None, description="Layer-level RAG config")
    rag_enabled: Optional[bool] = Field(None, description="Global RAG switch")


class RagConfigResponse(BaseModel):
    """RAG configuration response"""
    session_id: str
    rag_enabled: bool
    rag_layer_config: Dict[int, bool]


class StepModeRequest(BaseModel):
    """Step mode configuration request"""
    step_mode: bool = Field(..., description="Enable/disable step mode")


class StepModeResponse(BaseModel):
    """Step mode configuration response"""
    session_id: str
    step_mode: bool


@router.get("/api/sessions/{session_id}/rag-config", response_model=RagConfigResponse)
async def get_rag_config(session_id: str):
    """Get current RAG configuration"""
    state = await PlanningRuntimeService.aget_state_values(session_id)
    if not state:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    config = state.get("config", {})
    return RagConfigResponse(
        session_id=session_id,
        rag_enabled=config.get("rag_enabled", True),
        rag_layer_config=config.get("rag_layer_config", {1: True, 2: False, 3: True}),
    )


@router.patch("/api/sessions/{session_id}/rag-config", response_model=RagConfigResponse)
async def update_rag_config(session_id: str, request: RagConfigRequest):
    """Update RAG configuration (runtime modification)

    Example:
        PATCH /api/sessions/{id}/rag-config
        {"rag_layer_config": {1: true, 2: false, 3: true}}
    """
    state = await PlanningRuntimeService.aget_state_values(session_id)
    if not state:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    config = state.get("config", {})
    current_rag_enabled = config.get("rag_enabled", True)
    current_layer_config = config.get("rag_layer_config", {1: True, 2: False, 3: True})

    new_rag_enabled = request.rag_enabled if request.rag_enabled is not None else current_rag_enabled
    new_layer_config = request.rag_layer_config if request.rag_layer_config is not None else current_layer_config

    for layer in [1, 2, 3]:
        if layer not in new_layer_config:
            new_layer_config[layer] = new_rag_enabled

    await PlanningRuntimeService.aupdate_state(session_id, {
        "config": {
            **config,
            "rag_enabled": new_rag_enabled,
            "rag_layer_config": new_layer_config,
        }
    })

    logger.info(f"[rag-config] Updated {session_id}: enabled={new_rag_enabled}, layers={new_layer_config}")

    await sse_manager.publish(session_id, {
        "type": "rag_config_updated",
        "session_id": session_id,
        "rag_enabled": new_rag_enabled,
        "rag_layer_config": new_layer_config,
    })

    return RagConfigResponse(
        session_id=session_id,
        rag_enabled=new_rag_enabled,
        rag_layer_config=new_layer_config,
    )


@router.patch("/api/sessions/{session_id}/step-mode", response_model=StepModeResponse)
async def update_step_mode(session_id: str, request: StepModeRequest):
    """Update step mode (runtime modification)"""
    state = await PlanningRuntimeService.aget_state_values(session_id)
    if not state:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    await PlanningRuntimeService.aupdate_state(session_id, {
        "step_mode": request.step_mode,
    })

    logger.info(f"[step-mode] Updated {session_id}: step_mode={request.step_mode}")

    await sse_manager.publish(session_id, {
        "type": "step_mode_updated",
        "session_id": session_id,
        "step_mode": request.step_mode,
    })

    return StepModeResponse(
        session_id=session_id,
        step_mode=request.step_mode,
    )


@router.get("/api/sessions/{session_id}/layer/{layer}/reports")
async def get_layer_reports(session_id: str, layer: int):
    """获取层级报告（包含知识来源）"""
    if layer not in [1, 2, 3]:
        raise HTTPException(status_code=400, detail=f"Invalid layer: {layer}")
    store = ReportStore.get_instance()
    return await store.get_layer_reports_with_sources(session_id, layer)


# ============================================
# Planning Document Export (V3.0)
# ============================================

@router.post("/api/sessions/{session_id}/export/planning-text")
async def export_planning_text_document(
    session_id: str,
    project_name: str = "村庄规划",
):
    """
    导出规划文本为 DOCX 文件 (V3.0 兼容端点)。

    直接返回文件流，不在服务器保存文件。
    """
    return await _export_planning_text(session_id, project_name)


# ============================================
# Session Export (V4.0)
# ============================================

from fastapi.responses import FileResponse

from app.services.modules.planning_text.export_service import (
    ExportFormat,
    ExportLayer,
    SessionExportRequest,
    SessionExportResponse,
    ExportService,
)
from app.services.modules.planning_text.layer_exporter import LayerExporter


async def _export_planning_text(session_id: str, project_name: str):
    """Shared logic for planning text DOCX export."""
    from fastapi.responses import Response
    from app.services.modules.planning_text.layer_exporter import LayerExporter, LayerExportConfig

    config = LayerExportConfig(session_id=session_id, output_dir="output/export")
    exporter = LayerExporter(config)
    docx_bytes = await exporter.export_planning_text_to_bytes(project_name=project_name)

    if not docx_bytes:
        raise HTTPException(status_code=500, detail="导出规划文本失败")

    filename = f"{project_name}_规划文本.docx"
    return Response(
        content=docx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


@router.post("/api/sessions/{session_id}/export")
async def export_session_document(
    session_id: str,
    layer: Optional[int] = None,
    planning_text: bool = False,
    format: str = "docx",
    project_name: str = "村庄规划",
    include_summaries: bool = False,
):
    """
    导出会话文档。

    直接返回文件流，不在服务器保存文件。

    Args:
        session_id: Session ID
        layer: 层级 (1/2/3)，与 planning_text 二选一
        planning_text: 是否导出规划文本
        format: 导出格式 (docx/json/md)，默认 docx
        project_name: 项目名称（用于规划文本标题）
        include_summaries: 是否包含摘要（仅用于分层报告）
    """
    if format not in ("docx", "json", "md"):
        raise HTTPException(status_code=400, detail="format 必须为 docx/json/md")

    if planning_text:
        return await _export_planning_text(session_id, project_name)

    elif layer in (1, 2, 3):
        from fastapi.responses import Response
        from app.services.modules.planning_text.layer_exporter import LayerExporter, LayerExportConfig

        config = LayerExportConfig(
            session_id=session_id,
            output_dir="output/export",
            include_summaries=include_summaries,
        )
        exporter = LayerExporter(config)

        layer_name = get_layer_name(layer)

        if format == "json":
            json_bytes = await exporter.export_layer_to_json_bytes(layer)
            if not json_bytes:
                raise HTTPException(status_code=500, detail=f"导出 Layer {layer} JSON 失败")
            return Response(
                content=json_bytes,
                media_type="application/json",
                headers={"Content-Disposition": f'attachment; filename="L{layer}_{layer_name}.json"'}
            )
        elif format == "md":
            md_bytes = await exporter.export_layer_to_md_bytes(layer)
            if not md_bytes:
                raise HTTPException(status_code=500, detail=f"导出 Layer {layer} MD 失败")
            return Response(
                content=md_bytes,
                media_type="text/markdown; charset=utf-8",
                headers={"Content-Disposition": f'attachment; filename="L{layer}_{layer_name}.md"'}
            )
        else:
            docx_bytes = await exporter.export_layer_to_bytes(layer)
            if not docx_bytes:
                raise HTTPException(status_code=500, detail=f"导出 Layer {layer} DOCX 失败")
            return Response(
                content=docx_bytes,
                media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                headers={"Content-Disposition": f'attachment; filename="L{layer}_{layer_name}.docx"'}
            )

    else:
        raise HTTPException(
            status_code=400,
            detail="请指定 layer (1/2/3) 或 planning_text=true"
        )


# ============================================
# Planning Text Document Endpoints
# ============================================

from app.database.operations import (
    create_planning_text_document_async,
    get_planning_text_document_async,
    list_planning_text_versions_async,
    update_planning_text_status_async,
)
from app.services.modules.planning_text.generator import PlanningTextGenerator
from app.services.modules.planning_text.config import PlanningTextConfig


class PlanningTextResponse(BaseModel):
    """Planning text document response."""
    session_id: str
    version: int
    document_id: str
    markdown_content: str
    json_content: Optional[Dict[str, Any]] = None
    article_count: int
    generated_at: str
    generation_duration_seconds: Optional[float] = None
    status: str
    trigger_reason: Optional[str] = None
    changed_dimensions: Optional[List[str]] = None


class PlanningTextVersion(BaseModel):
    """Planning text version metadata."""
    id: int
    version: int
    document_id: str
    article_count: int
    generated_at: str
    generation_duration_seconds: Optional[float] = None
    status: str
    trigger_reason: Optional[str] = None
    changed_dimensions: Optional[List[str]] = None


class PlanningTextVersionList(BaseModel):
    """List of planning text versions."""
    session_id: str
    versions: List[PlanningTextVersion]
    total: int


class GeneratePlanningTextRequest(BaseModel):
    """Request to generate planning text."""
    trigger_reason: Optional[str] = "initial"
    changed_dimensions: Optional[List[str]] = None


class GeneratePlanningTextResponse(BaseModel):
    """Response for planning text generation."""
    session_id: str
    version: int
    document_id: str
    markdown_content: str
    article_count: int
    generated_at: str
    generation_duration_seconds: float
    status: str
    trigger_reason: str


@router.get("/api/sessions/{session_id}/planning-text", response_model=Optional[PlanningTextResponse])
async def get_planning_text(session_id: str, version: Optional[int] = None):
    """
    Get planning text document.

    Args:
        session_id: Session ID
        version: Version number (optional, defaults to latest)

    Returns:
        Planning text document or None if not found
    """
    doc = await get_planning_text_document_async(session_id, version)

    if not doc:
        return None

    return PlanningTextResponse(**doc)


@router.get("/api/sessions/{session_id}/planning-text/versions", response_model=PlanningTextVersionList)
async def get_planning_text_versions(session_id: str, limit: int = 20):
    """
    Get all planning text versions for a session.

    Args:
        session_id: Session ID
        limit: Maximum number of versions to return

    Returns:
        List of version metadata
    """
    versions = await list_planning_text_versions_async(session_id, limit)

    return PlanningTextVersionList(
        session_id=session_id,
        versions=[PlanningTextVersion(**v) for v in versions],
        total=len(versions),
    )


@router.get("/api/sessions/{session_id}/planning-text/versions/{version}", response_model=Optional[PlanningTextResponse])
async def get_planning_text_version(session_id: str, version: int):
    """
    Get a specific version of planning text.

    Args:
        session_id: Session ID
        version: Version number

    Returns:
        Planning text document or None if not found
    """
    doc = await get_planning_text_document_async(session_id, version)

    if not doc:
        return None

    return PlanningTextResponse(**doc)


@router.post("/api/sessions/{session_id}/planning-text", response_model=GeneratePlanningTextResponse)
async def generate_planning_text(session_id: str, request: GeneratePlanningTextRequest):
    """
    Generate planning text document.

    This endpoint:
    1. Fetches all L3 reports from DimensionReport table
    2. Uses PlanningTextGenerator to assemble the document
    3. Stores the result in PlanningTextDocument table (new version)

    Args:
        session_id: Session ID
        request: Generation request with trigger_reason and changed_dimensions

    Returns:
        Generated document metadata and content
    """
    import time

    start_time = time.time()

    # Get session metadata
    session = await get_planning_session_async(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    project_name = session.get("project_name", "村庄规划")
    village_name = session.get("village_name") or session.get("township", "")

    # Create output directory
    output_dir = Path(f"output/export/{session_id}")  # 统一到项目根目录
    output_dir.mkdir(parents=True, exist_ok=True)

    # Configure generator
    config = PlanningTextConfig(
        session_id=session_id,
        project_name=project_name,
        village_name=village_name,
        output_dir=str(output_dir),
        output_formats=("md", "json"),
        append_rag=True,
        generate_tier3=False,  # Skip LLM generation, use existing reports
    )

    generator = PlanningTextGenerator(config)

    try:
        # Generate document
        result = await generator.generate()

        duration = time.time() - start_time

        # Read generated content
        markdown_content = ""
        json_content = None

        if result.md_path:
            with open(result.md_path, "r", encoding="utf-8") as f:
                markdown_content = f.read()

        if result.json_path:
            with open(result.json_path, "r", encoding="utf-8") as f:
                json_content = json.load(f)

        # Store in database
        doc = await create_planning_text_document_async(
            session_id=session_id,
            markdown_content=markdown_content,
            json_content=json_content,
            article_count=result.article_count or 0,
            generation_duration_seconds=duration,
            trigger_reason=request.trigger_reason,
            changed_dimensions=request.changed_dimensions,
        )

        return GeneratePlanningTextResponse(
            session_id=doc["session_id"],
            version=doc["version"],
            document_id=doc["document_id"],
            markdown_content=doc["markdown_content"],
            article_count=doc["article_count"],
            generated_at=doc["generated_at"],
            generation_duration_seconds=duration,
            status=doc["status"],
            trigger_reason=doc["trigger_reason"],
        )

    except Exception as e:
        logger.error(f"[Planning Text] Generation failed for {session_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Planning text generation failed: {e}")


__all__ = ["router"]