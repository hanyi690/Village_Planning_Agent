"""Session history routes - reports, projects, planning-text documents."""

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel

from app.services.report_store import ReportStore
from app.services.runtime import PlanningRuntimeService
from app.database.operations import (
    list_planning_sessions_async,
    list_projects_async,
    list_project_sessions_async,
    get_planning_session_async,
    create_planning_text_document_async,
    get_planning_text_document_async,
    list_planning_text_versions_async,
)

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


@router.get("/api/sessions/{session_id}/layer/{layer}/reports")
async def get_layer_reports(session_id: str, layer: int):
    """获取层级报告（包含知识来源）"""
    if layer not in [1, 2, 3]:
        raise HTTPException(status_code=400, detail=f"Invalid layer: {layer}")
    store = ReportStore.get_instance()
    return await store.get_layer_reports_with_sources(session_id, layer)


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

    from app.modules.planning_text.generator import PlanningTextGenerator
    from app.modules.planning_text.config import PlanningTextConfig

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


__all__ = ["router"]