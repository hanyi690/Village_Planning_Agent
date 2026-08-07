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
import hashlib
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import quote
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field

from app.api.schemas import TaskStatus, ImageData, UploadedFileMeta
from app.services.runtime import PlanningRuntimeService
from app.services.report_store import ReportStore
from app.database.models import DimensionReport
from app.database.operations import (
    create_planning_session_async,
    update_planning_session_async,
    list_planning_sessions_async,
    list_projects_async,
    list_project_sessions_async,
)
from app.services.sse import sse_manager
from app.services.checkpoint import checkpoint_service
from app.agent.plan_state.state import state_to_ui_status
from app.agent.bootstrap.phase_machine import get_layer_dimensions, get_layer_name, get_next_phase, _phase_to_layer
from app.utils.sse_publisher import SSEPublisher
from app.core.events import SSEEventType

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

    # Check common field names in Chinese GIS data
    djzqmc = str(props.get("DJZQMC", "")).lower()
    ysdm = str(props.get("YSDM", "")).lower()
    if "村" in djzqmc or "委" in djzqmc:
        return "boundary"
    if "用地" in name or "landuse" in layer:
        return "landuse_current"

    return None


def _infer_data_type_from_filename(filename: str) -> Optional[str]:
    """Infer GIS data type from filename patterns."""
    lower = filename.lower()
    if "admin_boundary_line" in lower or "行政界线" in lower:
        return "admin_boundary_line"
    if "boundary" in lower or "边界" in lower:
        return "boundary"
    if "landuse" in lower or "用地" in lower or "现状" in lower:
        return "landuse_current"
    if "road" in lower or "道路" in lower:
        return "road"
    if "annotation" in lower or "注记" in lower:
        return "current_annotation"
    if "water" in lower or "水" in lower or "河流" in lower:
        return "water"
    if "residential" in lower or "住宅" in lower or "居民" in lower:
        return "residential"
    if "construction_zone" in lower or "建设区" in lower:
        return "construction_zone"
    if "farmland_protection" in lower or "基本农田" in lower:
        return "farmland_protection"
    if "ecological_protection" in lower or "生态保护" in lower:
        return "ecological_protection"
    if "historical_protection" in lower or "历史保护" in lower:
        return "historical_protection"
    if "geological_hazard" in lower or "地质灾害" in lower:
        return "geological_hazard_points"
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
        "geometry_audit": None,
    }

    try:
        if file_type == "geojson":
            # Parse GeoJSON directly from bytes
            try:
                geojson = json.loads(content.decode('utf-8'))
                if geojson.get("type") == "FeatureCollection":
                    result["gis_data"] = geojson
                    result["gis_data_type"] = _infer_geojson_data_type(geojson)
                    result["geometry_audit"] = _audit_geojson_geometry(geojson)
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


def _audit_geojson_geometry(geojson: Dict[str, Any]) -> Dict[str, Any]:
    """Record source geometry validity without mutating uploaded data.

    The raw upload remains the source of truth.  Spatial adapters may repair
    invalid shapes with Shapely ``make_valid`` at their boundary, but the
    upload audit must preserve the original feature index and reason so a
    later topology failure can be traced back to the input file.
    """
    audit = {"feature_count": 0, "invalid_count": 0, "null_geometry_count": 0, "samples": []}
    features = geojson.get("features") or []
    audit["feature_count"] = len(features)
    try:
        from shapely.geometry import shape
        from shapely.validation import explain_validity
    except Exception as exc:
        audit["status"] = "unavailable"
        audit["error"] = f"shapely unavailable: {type(exc).__name__}"
        return audit

    for index, feature in enumerate(features):
        geometry = (feature or {}).get("geometry") or {}
        if not geometry:
            audit["null_geometry_count"] += 1
            continue
        try:
            candidate = shape(geometry)
            if candidate.is_empty or not candidate.is_valid:
                audit["invalid_count"] += 1
                if len(audit["samples"]) < 10:
                    props = (feature or {}).get("properties") or {}
                    audit["samples"].append({
                        "feature_index": index,
                        "reason": "empty" if candidate.is_empty else explain_validity(candidate),
                        "bsm": str(props.get("BSM", props.get("bsm", "")) or ""),
                    })
        except Exception as exc:
            audit["invalid_count"] += 1
            if len(audit["samples"]) < 10:
                audit["samples"].append({
                    "feature_index": index,
                    "reason": f"parse_error:{type(exc).__name__}",
                    "bsm": "",
                })
    audit["status"] = "ok"
    return audit


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
    geometry_audit = parse_result.get("geometry_audit") or {}
    if geometry_audit.get("invalid_count"):
        logger.warning(
            "[SessionRoutes] Source geometry audit: %s invalid=%s samples=%s",
            filename,
            geometry_audit.get("invalid_count"),
            geometry_audit.get("samples", [])[:3],
        )
    # Prefer the explicit filename contract over weak first-feature property
    # inference.  This is required for uploaded layers such as
    # ``admin_boundary_line.geojson`` whose geometry type is enough to
    # distinguish them but whose properties may not carry a layer label.
    filename_dtype = _infer_data_type_from_filename(filename)
    dtype = filename_dtype or parse_result["gis_data_type"]
    if dtype in {"upload", "auto", "unknown"}:
        dtype = None
    if parse_result["gis_data"] and not dtype:
        dtype = _infer_data_type_from_filename(filename)
    parse_result["gis_data_type"] = dtype

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
        "checksum": hashlib.sha256(content).hexdigest(),
        "parse_status": parse_result["parse_status"],
        "parsed_text": parse_result["parsed_text"],
        "gis_data": parse_result["gis_data"],
        "gis_data_type": parse_result["gis_data_type"],
        "geometry_audit": parse_result.get("geometry_audit"),
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
                    event = await asyncio.wait_for(queue.get(), timeout=15.0)
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
    """提交反馈 — 使用 interrupt/resume 模式"""
    state = await PlanningRuntimeService.aget_state_values(session_id)
    if not state:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    if request.approve:
        current_phase = state.get("phase", "layer1")
        current_layer = _phase_to_layer(current_phase) or 1
        next_phase = get_next_phase(current_phase)
        logger.info("[feedback/approve] session=%s phase=%s", session_id, current_phase)

        # Resume from interrupt: approve action handled in layer_completion_check
        asyncio.create_task(PlanningRuntimeService.resume_from_interrupt(
            session_id,
            resume_data={"action": "approve"},
        ))
        return {
            "status": "approved",
            "next_phase": next_phase,
            "current_layer": current_layer,
            "review_layer": current_layer,
        }

    if request.dimensions and request.feedback:
        # Reject with feedback: compute impact tree and resume from interrupt
        from app.config.dependency import get_impact_tree_compat

        final_tree: Dict[int, List[str]] = {0: list(request.dimensions)}
        completed_dims = state.get("completed_dimensions", {})
        all_completed_keys = set(d for dims in completed_dims.values() for d in dims)

        for target_dim in request.dimensions:
            tree = get_impact_tree_compat(target_dim)
            for wave, dims in tree.items():
                already_executed = [d for d in dims if d in all_completed_keys]
                if already_executed:
                    final_tree.setdefault(wave, []).extend(already_executed)
        final_tree = {w: list(set(dims)) for w, d in final_tree.items() if d}

        asyncio.create_task(PlanningRuntimeService.resume_from_interrupt(
            session_id,
            resume_data={
                "action": "reject",
                "feedback": request.feedback,
                "dimensions": request.dimensions,
                "images": [],
            },
            state_updates={
                "revision_impact_tree": final_tree,
                "revision_completed_dims": {},
            },
        ))

        # Emit SSE events for immediate visual feedback
        try:
            all_impacted = set(d for dims in final_tree.values() for d in dims)
            for target_dim in request.dimensions:
                SSEPublisher.send_event(
                    session_id=session_id,
                    event_type=SSEEventType.CASCADE_IMPACT,
                    trigger_dim=target_dim,
                    impacted_dimensions=list(all_impacted),
                )
        except Exception as e:
            logger.warning(f"[feedback] SSE cascade events failed: {e}")

        return {"status": "revision_started", "dimensions": request.dimensions}

    if request.message:
        from langchain_core.messages import HumanMessage, AIMessage

        GIS_KEYWORDS = ["空间布局", "gis分析", "布局分析", "地图分析"]
        is_gis_request = any(kw in request.message.lower() for kw in GIS_KEYWORDS)

        # Check if graph is in interrupt state
        snapshot = await PlanningRuntimeService.aget_state(session_id)
        is_interrupted = snapshot and snapshot.next and len(snapshot.next) > 0

        if is_interrupted:
            # Graph paused at interrupt — resume with message
            if is_gis_request:
                synthetic_msg = AIMessage(
                    content="",
                    tool_calls=[{
                        "name": "gis_analysis",
                        "id": f"call_gis_{session_id[:8]}",
                        "args": {"reason": request.message}
                    }],
                )
                asyncio.create_task(PlanningRuntimeService.resume_from_interrupt(
                    session_id,
                    resume_data={"action": "message_injected", "message": request.message},
                    state_updates={"messages": [HumanMessage(content=request.message), synthetic_msg]},
                ))
                logger.info("[feedback] [%s] GIS intent detected, resumed from interrupt", session_id)
            else:
                asyncio.create_task(PlanningRuntimeService.resume_from_interrupt(
                    session_id,
                    resume_data={"action": "message_injected", "message": request.message},
                    state_updates={"messages": [HumanMessage(content=request.message)]},
                ))
        else:
            # Graph not interrupted — inject message via aupdate_state + resume
            # Official pattern: aupdate_state(as_node="__start__") sets checkpoint.next,
            # then _trigger_planning_execution() resumes with astream(None, config)
            if is_gis_request:
                synthetic_msg = AIMessage(
                    content="",
                    tool_calls=[{
                        "name": "gis_analysis",
                        "id": f"call_gis_{session_id[:8]}",
                        "args": {"reason": request.message}
                    }],
                )
                await PlanningRuntimeService.aupdate_state(
                    session_id,
                    {"messages": [HumanMessage(content=request.message), synthetic_msg]},
                    as_node="__start__",
                )
                asyncio.create_task(PlanningRuntimeService._trigger_planning_execution(session_id))
                logger.info("[feedback] [%s] GIS intent detected, new execution", session_id)
            else:
                await PlanningRuntimeService.aupdate_state(
                    session_id,
                    {"messages": [HumanMessage(content=request.message)]},
                    as_node="__start__",
                )
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
    if (values.get("is_interrupted")
            and values.get("previous_layer", 0) > 0):
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
        session_id, checkpoint_id=checkpoint_id, state_values=values
    ))
    return {"status": "resumed", "checkpoint_id": checkpoint_id, "layer": layer, "kind": kind}


@router.get("/api/sessions/{session_id}/positioning-trace")
async def get_positioning_trace(session_id: str):
    """获取全链定位追踪（L1/L3/EXPLORE/PARSE/EXECUTE 每步 Report）。

    按 session 聚合 StepReport，按 dimension_key + stage 索引，
    供前端下钻定位"文本与几何不一致"的断点。
    """
    from app.services.step_report import build_positioning_trace

    trace = await build_positioning_trace(session_id)
    if not trace["reports"]:
        # 会话不存在或尚无 step report（可能 L3 未完成）
        state = await PlanningRuntimeService.aget_state_values(session_id)
        if not state:
            raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")
    return trace


@router.get("/api/sessions/{session_id}/backend-run-report")
async def get_backend_run_report(session_id: str):
    """Return L1/L2/L3, KG, GIS output and render feasibility evidence."""
    from app.services.step_report import build_backend_run_report

    report = await build_backend_run_report(session_id)
    if not any(layer["available"] for layer in report["layers"].values()):
        state = await PlanningRuntimeService.aget_state_values(session_id)
        if not state:
            raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")
    return report


@router.get("/api/sessions/{session_id}/stage-report.md")
async def get_stage_report_markdown(session_id: str):
    """Return the full pipeline stage report as readable Markdown."""
    from app.services.stage_report import build_stage_report_markdown

    markdown = await build_stage_report_markdown(session_id)
    if not markdown:
        state = await PlanningRuntimeService.aget_state_values(session_id)
        if not state:
            raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")
    return Response(
        content=markdown or "# 无阶段报告\n\n该会话尚未产生任何 StepReport。\n",
        media_type="text/markdown; charset=utf-8",
    )


@router.get("/api/sessions/{session_id}/reports/{dim_key}")
async def get_dimension_report(session_id: str, dim_key: str, version: Optional[int] = None):
    """获取维度报告全文，支持历史版本查询（?version=N）"""
    if version is not None:
        store = ReportStore.get_instance()
        report = await store.get_report_by_version(session_id, dim_key, version)
        if report:
            return {
                "session_id": session_id,
                "dimension_key": dim_key,
                "layer": report["layer"],
                "content": report["content"],
                "version": version,
                "created_at": report["generated_at"],
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
    """列出指定维度所有版本"""
    store = ReportStore.get_instance()
    versions = await store.list_versions(session_id, dim_key)

    return {
        "session_id": session_id,
        "dimension_key": dim_key,
        "versions": versions,
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
            store = ReportStore.get_instance()
            report = await store.get_report_by_version(session_id, dim_key, version)
            if report:
                return {
                    "project_name": project_name,
                    "session_id": session_id,
                    "dimension_key": dim_key,
                    "layer": report["layer"],
                    "content": report["content"],
                    "version": version,
                    "created_at": report["generated_at"],
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
    }, as_node="conversation")

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
    }, as_node="conversation")

    logger.info(f"[step-mode] Updated {session_id}: step_mode={request.step_mode}")

    # If turning OFF step_mode while graph is interrupted, auto-approve
    if not request.step_mode:
        snapshot = await PlanningRuntimeService.aget_state(session_id)
        is_interrupted = snapshot and snapshot.next and len(snapshot.next) > 0
        if is_interrupted:
            asyncio.create_task(PlanningRuntimeService.resume_from_interrupt(
                session_id,
                resume_data={"action": "approve"},
            ))
            logger.info(f"[step-mode] Auto-approved interrupted session {session_id}")

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
# Session Export (V4.0)
# ============================================

from fastapi.responses import FileResponse

from app.modules.planning_text.layer_exporter import LayerExporter


def _content_disposition_header(filename: str) -> str:
    ascii_fallback = filename.encode('ascii', 'replace').decode('ascii').replace('?', '_')
    encoded = quote(filename, safe='')
    return f'attachment; filename="{ascii_fallback}"; filename*=UTF-8\'\'{encoded}'


async def _export_planning_text(session_id: str, project_name: str):
    """Export planning text as DOCX from the latest stored version."""
    from fastapi.responses import Response

    doc = await get_planning_text_document_async(session_id)
    if not doc:
        raise HTTPException(
            status_code=400,
            detail="尚未生成规划文本，请先点击「生成规划文本」",
        )

    markdown_content = doc.get("markdown_content", "")
    if not markdown_content:
        raise HTTPException(status_code=500, detail="规划文本内容为空")

    # Convert Markdown to DOCX via md_to_docx
    import sys
    import tempfile
    from pathlib import Path

    script_dir = Path(__file__).parent.parent.parent.parent / "scripts"
    if str(script_dir) not in sys.path:
        sys.path.insert(0, str(script_dir))

    try:
        from md_to_docx import create_docx_from_md
    except ImportError:
        raise HTTPException(status_code=500, detail="md_to_docx 模块不可用")

    with tempfile.TemporaryDirectory() as tmp_dir:
        md_tmp = Path(tmp_dir) / "planning_text.md"
        docx_tmp = Path(tmp_dir) / "planning_text.docx"
        md_tmp.write_text(markdown_content, encoding='utf-8')

        try:
            create_docx_from_md(md_tmp, docx_tmp)
            docx_bytes = docx_tmp.read_bytes()
        except Exception as e:
            logger.error(f"[Export] MD->DOCX conversion failed: {e}")
            raise HTTPException(status_code=500, detail="DOCX 转换失败")

    filename = f"{project_name}_规划文本.docx"
    return Response(
        content=docx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": _content_disposition_header(filename)}
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
        from app.modules.planning_text.layer_exporter import LayerExporter, LayerExportConfig

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
                headers={"Content-Disposition": _content_disposition_header(f"L{layer}_{layer_name}.json")}
            )
        elif format == "md":
            md_bytes = await exporter.export_layer_to_md_bytes(layer)
            if not md_bytes:
                raise HTTPException(status_code=500, detail=f"导出 Layer {layer} MD 失败")
            return Response(
                content=md_bytes,
                media_type="text/markdown; charset=utf-8",
                headers={"Content-Disposition": _content_disposition_header(f"L{layer}_{layer_name}.md")}
            )
        else:
            docx_bytes = await exporter.export_layer_to_bytes(layer)
            if not docx_bytes:
                raise HTTPException(status_code=500, detail=f"导出 Layer {layer} DOCX 失败")
            return Response(
                content=docx_bytes,
                media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                headers={"Content-Disposition": _content_disposition_header(f"L{layer}_{layer_name}.docx")}
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
    get_planning_session_async,
    create_planning_text_document_async,
    get_planning_text_document_async,
    list_planning_text_versions_async,
    update_planning_text_status_async,
)
from app.modules.planning_text.generator import PlanningTextGenerator
from app.modules.planning_text.config import PlanningTextConfig


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

    session = await get_planning_session_async(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    project_name = session.get("project_name", "村庄规划")
    village_name = session.get("village_name") or session.get("township", "")

    config = PlanningTextConfig(
        session_id=session_id,
        project_name=project_name,
        village_name=village_name,
        output_dir="",
        output_formats=(),
        append_rag=True,
        generate_tier3=True,
    )

    generator = PlanningTextGenerator(config)

    try:
        result = await generator.generate()
        duration = time.time() - start_time

        markdown_content = result.markdown
        article_count = len(result.build_report.articles) if result.build_report else 0

        doc = await create_planning_text_document_async(
            session_id=session_id,
            markdown_content=markdown_content,
            json_content=None,
            article_count=article_count,
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


@router.get("/api/sessions/{session_id}/geocode")
async def geocode_village(
    session_id: str,
    village_name: str = "",
    province: str = "",
    city: str = "",
    county: str = "",
    township: str = "",
):
    """Geocode village address to center coordinates + boundary.

    Uses DataCatalog for schema-driven data loading:
    1. Load boundary via DataCatalog (file_vector, no bbox needed)
    2. Derive center from boundary geometry
    3. Fallback: Tianditu geocode API
    """
    from app.modules.data.catalog.catalog import DataCatalog
    from app.modules.data.connections import ConnectionRegistry

    # Build full address from hierarchy
    parts = [p for p in [province, city, county, township, village_name] if p]
    location = "".join(parts)

    if not location:
        raise HTTPException(status_code=400, detail="No address provided")

    try:
        catalog = DataCatalog()
        bundle = catalog.load_village_bundle(location)

        center = None
        strategy = None

        # Derive center from boundary geometry
        if bundle.boundary and bundle.boundary.geometry:
            from app.modules.spatial_ops.geometry import _compute_centroid
            from app.modules.schema.types.canonical import _spatial_feature_to_geojson
            feat = _spatial_feature_to_geojson(bundle.boundary)
            boundary_fc = {
                "type": "FeatureCollection",
                "features": [feat],
            }
            center = _compute_centroid(boundary_fc)
            strategy = "boundary_geometry"
            # Also include boundary geojson for map display
            result_boundary = boundary_fc
        else:
            result_boundary = None

        # Fallback: geocode via Tianditu
        if center is None:
            conn = ConnectionRegistry.get("tianditu")
            if conn:
                geo = conn.geocode(location)
                if geo.success:
                    center = (geo.lon, geo.lat)
                    strategy = "geocode"

        result: Dict[str, Any] = {
            "location": location,
            "center": list(center) if center else None,
            "strategy": strategy,
            "metadata": {"village_name": location, "strategy": strategy},
        }

        if result_boundary:
            result["boundary_geojson"] = result_boundary

        if not result["center"]:
            raise HTTPException(status_code=404, detail=f"Cannot geocode: {location}")

        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[Geocode] Failed for {location}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Geocode failed: {e}")


@router.post("/api/sessions/{session_id}/gis-data")
async def upload_gis_data(
    session_id: str,
    file: UploadFile = File(...),
    data_type: Optional[str] = Form(None),
):
    """Upload GIS data (GeoJSON) to an existing session.

    Args:
        session_id: Session identifier
        file: GeoJSON file upload
        data_type: Optional data type hint (boundary/road/water/residential/landuse_current)
                   If not provided, will be auto-inferred from GeoJSON properties.

    Returns:
        Upload result with file ID and inferred data type.
    """
    # Read file content
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Empty file")

    # Parse file using existing helper
    parsed = await _parse_file_in_memory(file, content)

    if parsed["file_type"] != "geojson":
        raise HTTPException(
            status_code=400,
            detail=f"Only GeoJSON files are supported, got: {parsed['file_type']}"
        )

    if parsed["parse_status"] != "success":
        raise HTTPException(
            status_code=400,
            detail=f"GeoJSON parse failed: {parsed.get('parse_error', 'unknown error')}"
        )

    # Determine data type: user hint > auto-inferred from properties > from filename
    final_data_type = data_type or parsed.get("gis_data_type")
    if final_data_type in {"upload", "auto", "unknown"}:
        final_data_type = None
    if not final_data_type and file.filename:
        final_data_type = _infer_data_type_from_filename(file.filename)

    # Store in database
    try:
        file_id = await create_uploaded_file_async(
            session_id=session_id,
            file_category="gis_data",
            file_type="geojson",
            filename=file.filename or "upload.geojson",
            original_filename=file.filename,
            file_size=len(content),
            content_type=file.content_type or "application/geo+json",
            parsed_text=None,
            gis_data=parsed.get("gis_data"),
            gis_data_type=final_data_type,
            parse_status=parsed["parse_status"],
            parse_error=parsed.get("parse_error"),
        )
    except Exception as e:
        logger.error(f"[GIS Upload] Failed to store file: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to store file: {e}")

    # Note: uploaded GIS data is stored in DB via UploadedFile model.
    # The GIS agent will query it via get_uploaded_geojson_data_async() at execution time.

    # Push gis_layer_update SSE event so frontend renders uploaded data immediately
    try:
        from app.utils.sse_publisher import SSEPublisher

        gis_geojson = parsed.get("gis_data")
        if gis_geojson and final_data_type:
            _LAYER_TYPE_MAP = {
                "boundary": "boundary",
                "landuse_current": "function_zone",
                "road": "infrastructure",
                "water": "infrastructure",
                "residential": "function_zone",
            }
            _LAYER_NAME_MAP = {
                "boundary": "村庄边界",
                "landuse_current": "现状用地",
                "road": "道路网络",
                "water": "水系",
                "residential": "居民点",
            }
            frontend_layer_type = _LAYER_TYPE_MAP.get(final_data_type, "function_zone")
            layer_name = _LAYER_NAME_MAP.get(final_data_type, final_data_type)

            configs = [{
                "geojson": gis_geojson,
                "layerType": frontend_layer_type,
                "layerName": layer_name,
                "color": "#4ade80" if final_data_type == "boundary" else "#f59e0b",
            }]

            SSEPublisher.send_gis_layer_update(
                session_id=session_id,
                layer=1,
                dimension_key=f"upload_{final_data_type}",
                dimension_name="上传数据",
                layers=configs,
            )
    except Exception as e:
        logger.warning(f"[GIS Upload] SSE push failed: {e}")

    feature_count = len(parsed.get("gis_data", {}).get("features", []))

    return {
        "file_id": file_id,
        "filename": file.filename,
        "data_type": final_data_type,
        "feature_count": feature_count,
        "parse_status": parsed["parse_status"],
    }


__all__ = ["router"]
