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
from app.database.operations import create_planning_session_async
from app.services.sse import sse_manager
from app.services.checkpoint import checkpoint_service
from app.agent.state import get_layer_dimensions, get_layer_name, state_to_ui_status

logger = logging.getLogger(__name__)
router = APIRouter()


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

    from app.utils.sse_publisher import SSEPublisher
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

    if request.approve and state.get("pause_after_step", False):
        await PlanningRuntimeService.aupdate_state(session_id, {"pause_after_step": False, "previous_layer": 0})
        asyncio.create_task(PlanningRuntimeService._trigger_planning_execution(session_id))
        return {"status": "approved"}

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
    history = await checkpoint_service.get_checkpoint_history(session_id)
    checkpoints = []
    for entry in history:
        values = entry.get("values", {})
        checkpoints.append({
            "checkpoint_id": entry.get("checkpoint_id", ""),
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
async def get_dimension_report(session_id: str, dim_key: str):
    """获取维度报告全文"""
    state = await PlanningRuntimeService.aget_state_values(session_id)
    if not state:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    reports = state.get("reports", {})
    for layer_key in ["layer1", "layer2", "layer3"]:
        if dim_key in reports.get(layer_key, {}):
            return {"session_id": session_id, "dimension_key": dim_key,
                "layer": int(layer_key[-1]), "content": reports[layer_key][dim_key]}

    raise HTTPException(status_code=404, detail=f"Report not found: {dim_key}")


@router.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str):
    """删除会话"""
    from app.services.session import session_service
    result = await session_service.delete_session(session_id)
    return {"message": f"Session {session_id} deleted", "deleted_checkpoints": result.get("checkpoint", False)}


@router.get("/api/sessions/{session_id}/status")
async def get_session_status(session_id: str):
    """获取会话状态"""
    from app.database.operations import get_planning_session_async
    db_session = await get_planning_session_async(session_id)
    if not db_session:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    checkpoint_state = await PlanningRuntimeService.aget_state(session_id)
    state = dict(checkpoint_state.values) if checkpoint_state and checkpoint_state.values else {}
    return state_to_ui_status(state, db_session)


@router.get("/api/sessions/{session_id}/layer/{layer}/reports")
async def get_layer_reports(session_id: str, layer: int):
    """获取层级报告"""
    if layer not in [1, 2, 3]:
        raise HTTPException(status_code=400, detail=f"Invalid layer: {layer}")
    return await checkpoint_service.get_layer_reports(session_id, layer)


__all__ = ["router"]