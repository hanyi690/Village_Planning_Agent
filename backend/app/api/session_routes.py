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
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, UploadFile

from app.services.composition import CompositionRoot
from app.database.operations import create_uploaded_file_async
from app.utils.document_loader import classify_file_type, MarkItDownLoader

logger = logging.getLogger(__name__)
router = APIRouter()


def _launch_background(session_id: str, coro) -> None:
    """Launch a fire-and-forget graph execution task for a session.

    Routes through the composition root's TaskSupervisor so at most one
    execution per session runs at a time (a newer submission cancels an
    in-flight one) and tasks are tracked for clean shutdown.
    """
    supervisor = CompositionRoot.get_task_supervisor()
    supervisor.create_task(session_id, coro)


# ============================================
# Module-level file processing helpers
# ============================================


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


# ============================================
# Router aggregation (split by responsibility)
# ============================================

from app.api.route_modules.session_crud import router as crud_router
from app.api.route_modules.session_sse import router as sse_router
from app.api.route_modules.session_hitl import router as hitl_router
from app.api.route_modules.session_gis import router as gis_router
from app.api.route_modules.session_checkpoints import router as checkpoints_router
from app.api.route_modules.session_history import router as history_router

router.include_router(crud_router)
router.include_router(sse_router)
router.include_router(hitl_router)
router.include_router(gis_router)
router.include_router(checkpoints_router)
router.include_router(history_router)


__all__ = ["router"]