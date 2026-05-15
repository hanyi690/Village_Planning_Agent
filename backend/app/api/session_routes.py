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


async def _get_report_from_db(session_id: str, dim_key: str) -> tuple[str, int, str]:
    """Helper to fetch report content and layer from database.

    Returns:
        tuple of (content, layer, report_id) or raises HTTPException
    """
    store = ReportStore.get_instance()
    report = await store.get_latest_report(session_id, dim_key)

    if not report:
        raise HTTPException(status_code=404, detail=f"Report not found: {dim_key}")

    return report.content, report.layer, report.report_id


# ============================================
# Module-level file processing helpers
# ============================================

def _save_uploaded_file(file: UploadFile, upload_dir: Path, subdir: str = "") -> Path:
    """Save uploaded file to disk, return saved path."""
    target_dir = upload_dir / subdir if subdir else upload_dir
    return target_dir / (file.filename or "unknown")


async def _parse_uploaded_document(saved_path: Path, filename: str) -> str:
    """Parse a saved document file, return extracted text."""
    from app.utils.document_loader import classify_file_type, MarkItDownLoader
    file_type = classify_file_type(filename)
    if file_type == "document":
        try:
            loader = MarkItDownLoader(saved_path)
            docs = loader.load()
            if docs:
                return docs[0].page_content
        except Exception as e:
            logger.warning(f"[SessionRoutes] 文档解析失败 {filename}: {e}")
    return ""


async def _process_uploaded_file(
    file: UploadFile,
    upload_dir: Path,
    subdir: str = "",
) -> Dict[str, Any]:
    """Process single uploaded file: save, return metadata dict."""
    filename = file.filename or "unknown"
    saved_path = _save_uploaded_file(file, upload_dir, subdir)
    content = await file.read()
    with open(saved_path, "wb") as f:
        f.write(content)
    doc_text = await _parse_uploaded_document(saved_path, filename)
    return {
        "filename": filename,
        "saved_path": saved_path,
        "content": content,
        "doc_text": doc_text,
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
    task_description: str = Form("制定村庄发展规划", description="任务描述"),
    constraints: str = Form("无特殊约束", description="约束条件"),
    step_mode: bool = Form(False, description="分步执行模式"),
    rag_enabled: bool = Form(True, description="启用 RAG 知识检索（实验对比用）"),
    village_data: str = Form("", description="村庄基础数据（文本）"),
    village_data_files: List[UploadFile] = File(None, description="村庄数据文件"),
    task_files: List[UploadFile] = File(None, description="任务描述文件"),
    constraint_files: List[UploadFile] = File(None, description="约束条件文件"),
):
    """创建新规划会话 - 支持 multipart/form-data 文件上传（按来源区分）"""
    if not project_name.strip():
        raise HTTPException(status_code=400, detail="项目名称不能为空")

    session_id = str(uuid4())
    upload_dir = Path(f"data/uploads/{session_id}")
    upload_dir.mkdir(parents=True, exist_ok=True)
    uploaded_files: List[Dict] = []
    parsed_content = village_data

    # 文件分组处理配置: (file_group, file_type_label, subdir)
    file_groups = [
        (village_data_files, "village_data", ""),
        (task_files, "task_description", ""),
        (constraint_files, "constraint", ""),
    ]

    for file_group, file_type, subdir in file_groups:
        if not file_group:
            continue
        results = await asyncio.gather(*[
            _process_uploaded_file(f, upload_dir, subdir) for f in file_group
        ])
        for r in results:
            meta = {
                "filename": r["filename"],
                "file_type": file_type,
                "path": str(r["saved_path"]),
                "size_bytes": len(r["content"]),
            }
            uploaded_files.append(meta)

            if file_type == "village_data" and r["doc_text"]:
                parsed_content += f"\n\n--- 村庄数据: {r['filename']} ---\n{r['doc_text']}"
            elif file_type == "task_description" and r["doc_text"]:
                if not task_description or task_description == "制定村庄发展规划":
                    task_description = r["doc_text"].strip()
            elif file_type == "constraint" and r["doc_text"]:
                if not constraints or constraints == "无特殊约束":
                    constraints = r["doc_text"].strip()

    # 验证数据
    if len(parsed_content.strip()) < 10:
        raise HTTPException(status_code=400, detail="村庄数据不能为空或过短")

    initial_state = PlanningRuntimeService.build_initial_state(
        project_name=project_name,
        village_data=parsed_content,
        village_name=village_name,
        task_description=task_description,
        constraints=constraints,
        session_id=session_id,
        stream_mode=True,
        step_mode=step_mode,
        rag_enabled=rag_enabled,
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
        })
        asyncio.create_task(PlanningRuntimeService._trigger_planning_execution(session_id))
        return {"status": "revision_started", "dimensions": request.dimensions}

    if request.message:
        from langchain_core.messages import HumanMessage
        await PlanningRuntimeService.aupdate_state(session_id, {"messages": [HumanMessage(content=request.message)]})
        asyncio.create_task(PlanningRuntimeService._trigger_planning_execution(session_id))
        return {"status": "message_accepted"}

    return {"status": "no_action"}


@router.get("/api/sessions/{session_id}/checkpoints")
async def get_checkpoints(session_id: str):
    """获取检查点列表"""
    checkpoints = []
    async for snapshot in PlanningRuntimeService.aget_state_history(session_id):
        checkpoint_id = snapshot.config.get("configurable", {}).get("checkpoint_id", "")
        values = dict(snapshot.values) if snapshot.values else {}
        checkpoints.append({
            "checkpoint_id": checkpoint_id,
            "phase": values.get("phase", "init"),
            "layer": values.get("previous_layer", 0),
        })
    return {"session_id": session_id, "checkpoints": checkpoints, "count": len(checkpoints)}


@router.post("/api/sessions/{session_id}/resume/{checkpoint_id}")
async def resume_from_checkpoint(session_id: str, checkpoint_id: str):
    """从检查点恢复"""
    target_state = None
    async for snapshot in PlanningRuntimeService.aget_state_history(session_id):
        if snapshot.config.get("configurable", {}).get("checkpoint_id", "") == checkpoint_id:
            target_state = snapshot
            break

    if not target_state:
        raise HTTPException(status_code=404, detail=f"Checkpoint not found: {checkpoint_id}")

    layer = target_state.values.get("previous_layer", 1) or 1
    sse_manager.append_event(session_id, {"type": "resumed", "checkpoint_id": checkpoint_id, "layer": layer})
    sse_manager.publish_sync(session_id, {"type": "resumed", "checkpoint_id": checkpoint_id})

    asyncio.create_task(PlanningRuntimeService._trigger_planning_execution(session_id))
    return {"status": "resumed", "checkpoint_id": checkpoint_id, "layer": layer}


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
    content, layer, _ = await _get_report_from_db(session_id, dim_key)
    return {
        "session_id": session_id,
        "dimension_key": dim_key,
        "layer": layer,
        "content": content
    }


@router.get("/api/sessions/{session_id}/reports/{dim_key}/versions")
async def get_dimension_report_versions(session_id: str, dim_key: str):
    """列出指定维度所有历史版本摘要（不含完整内容）"""
    revisions = await get_dimension_revisions_async(
        session_id=session_id, dimension_key=dim_key
    )
    if not revisions:
        raise HTTPException(status_code=404, detail=f"No revisions found for dimension: {dim_key}")

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
        content, layer, _ = await _get_report_from_db(session_id, dim_key)
        return {
            "project_name": project_name,
            "session_id": session_id,
            "dimension_key": dim_key,
            "layer": layer,
            "content": content,
        }

    sessions = await list_planning_sessions_async(project_name=project_name, limit=1)
    if not sessions:
        raise HTTPException(status_code=404, detail=f"No sessions found for project: {project_name}")

    latest_session_id = sessions[0]["session_id"]

    # 从数据库获取报告
    content, layer, _ = await _get_report_from_db(latest_session_id, dim_key)
    return {
        "project_name": project_name,
        "session_id": latest_session_id,
        "dimension_key": dim_key,
        "layer": layer,
        "content": content,
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
        rag_layer_config=config.get("rag_layer_config", {1: True, 2: True, 3: True}),
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
    current_layer_config = config.get("rag_layer_config", {1: True, 2: True, 3: True})

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


@router.get("/api/sessions/{session_id}/layer/{layer}/reports")
async def get_layer_reports(session_id: str, layer: int):
    """获取层级报告"""
    if layer not in [1, 2, 3]:
        raise HTTPException(status_code=400, detail=f"Invalid layer: {layer}")
    return await checkpoint_service.get_layer_reports(session_id, layer)


# ============================================
# Planning Document Export (V3.0)
# ============================================

class ExportRequest(BaseModel):
    """导出请求"""
    layer3_path: str = Field(..., description="Layer3 Markdown 文件路径")
    project_name: str = Field(default="金田村", description="项目名称")


class ExportResponse(BaseModel):
    """导出响应"""
    success: bool
    markdown_path: str
    article_count: int
    errors: List[str] = []


@router.post("/api/planning/export", response_model=ExportResponse)
async def export_planning_document(request: ExportRequest):
    """
    导出法定规划文档（简化版）

    直接从 Layer3 Markdown 提取内容，按条文编号组织输出。
    不使用 LLM，保留原始表格和列表结构。
    """
    import sys
    project_root = Path(__file__).parent.parent.parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    from scripts.llm_assisted.simple_export import export_planning_document

    output_dir = Path("docs/planning_export/output")
    output_dir.mkdir(parents=True, exist_ok=True)

    result = export_planning_document(
        layer3_path=request.layer3_path,
        output_dir=str(output_dir),
        project_name=request.project_name
    )

    return ExportResponse(
        success=result.success,
        markdown_path=result.markdown_path,
        article_count=result.article_count,
        errors=result.errors
    )


@router.get("/api/planning/export/{project_name}")
async def get_exported_document(project_name: str):
    """
    获取已导出的规划文档

    返回 Markdown 文件内容。
    """
    markdown_path = Path(f"docs/planning_export/output/{project_name}_规划文本.md")
    if not markdown_path.exists():
        raise HTTPException(status_code=404, detail=f"Document not found: {project_name}")

    with open(markdown_path, "r", encoding="utf-8") as f:
        content = f.read()

    return {
        "project_name": project_name,
        "content": content,
        "path": str(markdown_path),
    }


__all__ = ["router"]