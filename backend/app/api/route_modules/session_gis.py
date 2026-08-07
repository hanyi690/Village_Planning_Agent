"""Session GIS routes - geocode, GIS data upload, and document export."""

import logging
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import quote

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import Response

from app.api.session_routes import _parse_file_in_memory, _infer_data_type_from_filename
from app.agent.bootstrap.phase_machine import get_layer_name
from app.modules.planning_text.layer_exporter import LayerExporter, LayerExportConfig
from app.database.operations import create_uploaded_file_async

logger = logging.getLogger(__name__)
router = APIRouter()


def _content_disposition_header(filename: str) -> str:
    ascii_fallback = filename.encode('ascii', 'replace').decode('ascii').replace('?', '_')
    encoded = quote(filename, safe='')
    return f'attachment; filename="{ascii_fallback}"; filename*=UTF-8\'\'{encoded}'


async def _export_planning_text(session_id: str, project_name: str):
    """Export planning text as DOCX from the latest stored version."""
    from app.database.operations import get_planning_text_document_async

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


__all__ = ["router"]