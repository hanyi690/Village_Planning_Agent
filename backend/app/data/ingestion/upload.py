"""Upload parsing and persistence owned by the data layer."""

from __future__ import annotations

import hashlib
import json
import logging
import tempfile
from pathlib import Path
from typing import Any

from fastapi import UploadFile

from app.database.operations import create_uploaded_file_async
from app.utils.document_loader import MarkItDownLoader, classify_file_type

logger = logging.getLogger(__name__)


def infer_data_type_from_filename(filename: str) -> str | None:
    lower = str(filename or "").lower()
    mapping = (
        (("admin_boundary_line", "行政界线"), "admin_boundary_line"),
        (("boundary", "边界"), "boundary"),
        (("landuse", "用地", "现状"), "landuse_current"),
        (("road", "道路"), "road"),
        (("annotation", "注记"), "current_annotation"),
        (("water", "水", "河流"), "water"),
        (("residential", "住宅", "居民"), "residential"),
        (("construction_zone", "建设区"), "construction_zone"),
        (("farmland_protection", "基本农田"), "farmland_protection"),
        (("ecological_protection", "生态保护"), "ecological_protection"),
        (("historical_protection", "历史保护"), "historical_protection"),
        (("geological_hazard", "地质灾害"), "geological_hazard_points"),
    )
    for needles, layer in mapping:
        if any(needle in lower for needle in needles):
            return layer
    return None


def audit_geojson_geometry(geojson: dict[str, Any]) -> dict[str, Any]:
    audit = {"feature_count": 0, "invalid_count": 0, "null_geometry_count": 0, "samples": []}
    features = geojson.get("features") or []
    audit["feature_count"] = len(features)
    try:
        from shapely.geometry import shape
        from shapely.validation import explain_validity
    except Exception as exc:
        audit.update(status="unavailable", error=f"shapely unavailable: {type(exc).__name__}")
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


async def _parse_upload(file: UploadFile, content: bytes) -> dict[str, Any]:
    filename = file.filename or "unknown"
    file_type = classify_file_type(filename)
    result: dict[str, Any] = {
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
            geojson = json.loads(content.decode("utf-8"))
            if geojson.get("type") != "FeatureCollection":
                raise ValueError("Not a valid GeoJSON FeatureCollection")
            result["gis_data"] = geojson
            result["gis_data_type"] = infer_data_type_from_filename(filename)
            result["geometry_audit"] = audit_geojson_geometry(geojson)
        elif file_type == "document":
            with tempfile.NamedTemporaryFile(suffix=Path(filename).suffix, delete=False) as tmp:
                tmp.write(content)
                temp_path = Path(tmp.name)
            try:
                documents = MarkItDownLoader(temp_path).load()
                result["parsed_text"] = documents[0].page_content if documents else None
                if not result["parsed_text"]:
                    raise ValueError("No content extracted")
            finally:
                temp_path.unlink(missing_ok=True)
        result["parse_status"] = "success"
    except Exception as exc:
        result["parse_status"] = "failed"
        result["parse_error"] = str(exc)
        logger.warning("[DataIngestion] upload parse failed for %s: %s", filename, exc)
    return result


async def process_uploaded_file(
    file: UploadFile,
    session_id: str,
    file_category: str,
) -> dict[str, Any]:
    filename = file.filename or "unknown"
    content = await file.read()
    parsed = await _parse_upload(file, content)
    dtype = infer_data_type_from_filename(filename) or parsed.get("gis_data_type")
    parsed["gis_data_type"] = dtype
    file_id = await create_uploaded_file_async(
        session_id=session_id,
        file_category=file_category,
        file_type=parsed["file_type"],
        filename=filename,
        original_filename=filename,
        file_size=len(content),
        content_type=file.content_type or "application/octet-stream",
        parsed_text=parsed.get("parsed_text"),
        gis_data=parsed.get("gis_data"),
        gis_data_type=dtype,
        parse_status=parsed.get("parse_status"),
        parse_error=parsed.get("parse_error"),
    )
    return {
        "id": file_id,
        "filename": filename,
        "file_category": file_category,
        "file_type": parsed["file_type"],
        "size_bytes": len(content),
        "checksum": hashlib.sha256(content).hexdigest(),
        **parsed,
    }


__all__ = ["process_uploaded_file", "infer_data_type_from_filename", "audit_geojson_geometry"]
