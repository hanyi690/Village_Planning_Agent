"""Upload parsing and persistence owned by the data layer."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import tempfile
from email.header import decode_header
from pathlib import Path
from typing import Any

from fastapi import UploadFile

from app.database.operations import create_uploaded_file_async
from app.data.ingestion.documents.document_loader import classify_file_type
from app.data.ingestion.documents.mineru_loader import MinerULoader

logger = logging.getLogger(__name__)
_MARKDOWN_MEDIA_RE = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")


def _normalized_upload_filename(value: str | None) -> str:
    """Decode transport encoding and return one safe source basename.

    Some multipart clients encode non-ASCII filenames as an RFC 2047 encoded
    word.  Starlette intentionally preserves the header value, so an already
    normalized ``.md`` source otherwise loses its suffix and is needlessly
    sent to MinerU.  DATA stores the original header separately; parsing and
    source classification use this deterministic Unicode basename.
    """

    raw = str(value or "").strip()
    if not raw:
        return "unknown"
    try:
        decoded = "".join(
            part.decode(charset or "utf-8") if isinstance(part, bytes) else part
            for part, charset in decode_header(raw)
        )
    except (LookupError, UnicodeDecodeError, ValueError):
        decoded = raw
    basename = Path(decoded.replace("\\", "/")).name.replace("\x00", "").strip()
    return basename or "unknown"


def infer_data_type_from_filename(filename: str) -> str | None:
    lower = str(filename or "").lower()
    mapping = (
        (("planned_landuse", "planning_landuse", "规划用地", "目标年用地"), "landuse_planned"),
        (("planned_road", "planning_road", "规划道路"), "planned_road"),
        (("planned_annotation", "planning_annotation", "规划注记"), "planned_annotation"),
        (("planned_facility", "planning_facility", "规划设施"), "planned_facility"),
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


def parse_vector_file_bytes(content: bytes, filename: str) -> dict[str, Any]:
    """Decode a supported vector file into a lossless GeoJSON collection.

    The DATA boundary uses GeoJSON as an interchange envelope only; it does
    not assign a planning layer or rename source attributes.  GeoPandas/Fiona
    are optional runtime dependencies, so callers receive a typed parse error
    when the environment cannot decode the file.
    """

    import json as _json
    import tempfile as _tempfile
    from pathlib import Path as _Path

    try:
        import geopandas as gpd
    except Exception as exc:  # pragma: no cover - environment dependent
        raise RuntimeError(f"vector decoder unavailable: {type(exc).__name__}") from exc

    suffix = _Path(str(filename or "upload")).suffix.lower() or ".bin"
    with _tempfile.TemporaryDirectory(prefix="planning-vector-") as temp_dir:
        path = _Path(temp_dir) / ("source" + suffix)
        path.write_bytes(content)
        zip_extract_dir = None
        if suffix == ".zip":
            import zipfile

            extract_dir = _Path(temp_dir) / "unzipped"
            zip_extract_dir = extract_dir
            with zipfile.ZipFile(path) as archive:
                members = archive.namelist()
                if any(
                    _Path(member).is_absolute()
                    or ".." in _Path(member).parts
                    for member in members
                ):
                    raise RuntimeError("unsafe shapefile archive path")
                archive.extractall(extract_dir)
            shapefiles = sorted(extract_dir.rglob("*.shp"))
            if not shapefiles:
                raise RuntimeError("shapefile archive contains no .shp layer")
            source_paths = shapefiles
            suffix = ".shp"
        else:
            source_paths = [path]
        sources: list[tuple[Any, str | None, str | None]] = []
        for source_path in source_paths:
            layers: list[str | None] = [None]
            if suffix in {".gpkg", ".gdb"}:
                try:
                    listed = gpd.list_layers(source_path)
                    if hasattr(listed, "columns") and "name" in listed.columns:
                        layers = [
                            str(value)
                            for value in listed["name"].tolist()
                            if str(value).strip()
                        ]
                    else:
                        layers = [
                            str(row[0])
                            for row in listed
                            if row is not None and len(row) > 0
                        ]
                    if not layers:
                        layers = [None]
                except Exception:
                    layers = [None]
                sources.extend((source_path, layer, layer) for layer in layers)
            elif suffix == ".shp":
                # A Shapefile is itself one source layer.  ZIP archives may
                # contain several files with identical stems in subfolders,
                # so retain the relative path as the stable layer hint.
                layer_ref = source_path.stem
                if zip_extract_dir is not None:
                    try:
                        layer_ref = source_path.relative_to(zip_extract_dir).with_suffix("").as_posix()
                    except ValueError:
                        pass
                sources.append((source_path, None, layer_ref))
            else:
                sources.append((source_path, None, None))
        all_features: list[dict[str, Any]] = []
        crs_names: set[str] = set()
        for source_path, read_layer, layer_ref in sources:
            frame = None
            errors: list[Exception] = []
            read_attempts = [{}]
            for kwargs in read_attempts:
                try:
                    frame = (
                        gpd.read_file(source_path, layer=read_layer, **kwargs)
                        if read_layer
                        else gpd.read_file(source_path, **kwargs)
                    )
                    break
                except Exception as exc:
                    errors.append(exc)
            if frame is None:
                if len(sources) > 1:
                    error = errors[-1] if errors else RuntimeError("unknown vector error")
                    all_features.append({
                        "type": "Feature",
                        "geometry": None,
                        "properties": {
                            "__source_layer": str(layer_ref or read_layer or source_path.stem),
                            "__source_record_id": "layer-read-failure",
                            "resource_kind": "vector_layer_failure",
                            "parse_status": "failed",
                            "parse_error": f"vector_layer_decode_failed:{type(error).__name__}",
                        },
                    })
                    continue
                error = errors[-1] if errors else RuntimeError("unknown vector error")
                raise RuntimeError(f"vector decode failed: {type(error).__name__}") from error
            if frame.crs is not None:
                crs_name = str(
                    getattr(frame.crs, "to_string", lambda: frame.crs)()
                )
                if crs_name:
                    crs_names.add(crs_name)
            else:
                crs_name = ""
            payload = _json.loads(frame.to_json(drop_id=False))
            for layer_feature_index, feature in enumerate(payload.get("features", [])):
                props = dict(feature.get("properties") or {})
                # Preserve source attributes; this metadata is namespaced and
                # is never interpreted as a planning layer by DATA.  CRS is
                # attached per feature because a mixed archive can contain
                # layers with different coordinate systems.
                if layer_ref:
                    props.setdefault("__source_layer", layer_ref)
                props.setdefault(
                    "__source_record_id",
                    str(feature.get("id") or layer_feature_index),
                )
                props.setdefault("__source_layer_feature_index", layer_feature_index)
                if crs_name:
                    props.setdefault("__source_crs", crs_name)
                feature["properties"] = props
                all_features.append(feature)
        if not all_features and len(sources) > 1:
            raise RuntimeError("vector file contains no readable layers")
        result: dict[str, Any] = {
            "type": "FeatureCollection",
            "features": all_features,
        }
        if len(crs_names) == 1:
            crs_name = next(iter(crs_names))
            result["crs"] = {"type": "name", "properties": {"name": crs_name}}
        return result


def parse_raster_file_bytes(content: bytes, filename: str) -> dict[str, Any]:
    """Read raster metadata without pretending a raster is a vector geometry."""

    try:
        import rasterio
        from rasterio.io import MemoryFile
    except Exception as exc:  # pragma: no cover - environment dependent
        raise RuntimeError(f"raster decoder unavailable: {type(exc).__name__}") from exc
    try:
        with MemoryFile(content) as memory_file:
            with memory_file.open() as dataset:
                bounds = dataset.bounds
                return {
                    "type": "RasterResource",
                    "resource_kind": "raster",
                    "filename": str(filename or ""),
                    "crs": str(dataset.crs or ""),
                    "width": int(dataset.width),
                    "height": int(dataset.height),
                    "band_count": int(dataset.count),
                    "bounds": [float(bounds.left), float(bounds.bottom), float(bounds.right), float(bounds.top)],
                    "transform": [float(value) for value in dataset.transform[:6]],
                }
    except Exception as exc:
        raise RuntimeError(f"raster decode failed: {type(exc).__name__}") from exc


def parse_table_file_bytes(content: bytes, filename: str) -> dict[str, Any]:
    """Decode CSV/TSV/Excel sheets while preserving arbitrary column names."""

    import io
    from pathlib import Path as _Path

    try:
        import pandas as pd
    except Exception as exc:  # pragma: no cover - environment dependent
        raise RuntimeError(f"table decoder unavailable: {type(exc).__name__}") from exc

    suffix = _Path(str(filename or "upload")).suffix.lower()
    frames: list[tuple[str, Any]] = []
    try:
        if suffix in {".xlsx", ".xls"}:
            workbook = pd.ExcelFile(io.BytesIO(content))
            for sheet in workbook.sheet_names:
                frames.append((str(sheet), pd.read_excel(workbook, sheet_name=sheet, dtype=object)))
        else:
            separator = "\t" if suffix == ".tsv" else None
            frame = pd.read_csv(
                io.BytesIO(content),
                sep=separator or None,
                engine="python" if separator is None else "c",
                encoding="utf-8-sig",
                dtype=object,
            )
            frames.append(("default", frame))
    except Exception as exc:
        raise RuntimeError(f"table decode failed: {type(exc).__name__}") from exc

    def json_value(value: Any) -> Any:
        if value is None:
            return None
        try:
            missing = pd.isna(value)
            if isinstance(missing, bool) and missing:
                return None
        except Exception:
            pass
        if hasattr(value, "item"):
            try:
                return json_value(value.item())
            except Exception:
                pass
        if hasattr(value, "isoformat"):
            try:
                return value.isoformat()
            except Exception:
                pass
        if isinstance(value, (str, int, float, bool, list, tuple, dict)):
            return value
        return str(value)

    tables: list[dict[str, Any]] = []
    for sheet_name, frame in frames:
        columns = [str(column) for column in frame.columns]
        rows = [
            {
                column: json_value(value)
                for column, value in zip(columns, row, strict=False)
            }
            for row in frame.itertuples(index=False, name=None)
        ]
        tables.append({"name": sheet_name, "columns": columns, "rows": rows})
    return {
        "type": "TableResource",
        "filename": str(filename or ""),
        "tables": tables,
        "row_count": sum(len(table["rows"]) for table in tables),
    }


async def _parse_upload(
    file: UploadFile,
    content: bytes,
    *,
    file_category: str,
) -> dict[str, Any]:
    filename = _normalized_upload_filename(file.filename)
    file_type = classify_file_type(filename)
    result: dict[str, Any] = {
        "file_type": file_type,
        "parsed_text": None,
        "gis_data": None,
        "gis_data_type": None,
        "parse_status": "pending",
        "parse_error": None,
        "geometry_audit": None,
        "parsed_text_format": None,
        "text_parser": None,
        "media_refs": [],
        "source_format": Path(filename).suffix.lower().lstrip("."),
    }
    try:
        if file_type == "geojson":
            geojson = json.loads(content.decode("utf-8"))
            if geojson.get("type") != "FeatureCollection":
                raise ValueError("Not a valid GeoJSON FeatureCollection")
            result["gis_data"] = geojson
            result["gis_data_type"] = infer_data_type_from_filename(filename)
            result["geometry_audit"] = audit_geojson_geometry(geojson)
        elif file_type in {"shapefile", "kml", "gis_file"}:
            geojson = parse_vector_file_bytes(content, filename)
            result["gis_data"] = geojson
            result["gis_data_type"] = infer_data_type_from_filename(filename)
            result["geometry_audit"] = audit_geojson_geometry(geojson)
        elif file_type == "raster":
            result["gis_data"] = parse_raster_file_bytes(content, filename)
            result["gis_data_type"] = "raster"
        elif file_type == "table":
            # Non-GIS uploads must pass through MinerU first.  Keep the
            # lossless table resource as a parallel DATA representation, but
            # the text channel is always MinerU-produced Markdown.
            with tempfile.NamedTemporaryFile(suffix=Path(filename).suffix, delete=False) as tmp:
                tmp.write(content)
                temp_path = Path(tmp.name)
            try:
                documents = MinerULoader(
                    temp_path,
                    category=file_category,
                    allow_fallback=False,
                ).load()
                result["parsed_text"] = documents[0].page_content if documents else None
                result["parsed_text_format"] = "markdown" if result["parsed_text"] else None
                result["media_refs"] = _MARKDOWN_MEDIA_RE.findall(result["parsed_text"] or "")
                result["text_parser"] = "mineru"
                if not result["parsed_text"]:
                    raise ValueError("MinerU produced no Markdown content")
            finally:
                temp_path.unlink(missing_ok=True)
            result["gis_data"] = parse_table_file_bytes(content, filename)
            result["gis_data_type"] = "table"
        elif file_type == "document":
            suffix = Path(filename).suffix.casefold()
            if suffix in {".md", ".markdown"}:
                result["parsed_text"] = content.decode("utf-8-sig")
                result["text_parser"] = "markdown_passthrough"
            else:
                with tempfile.NamedTemporaryFile(suffix=Path(filename).suffix, delete=False) as tmp:
                    tmp.write(content)
                    temp_path = Path(tmp.name)
                try:
                    documents = MinerULoader(
                        temp_path,
                        category=file_category,
                        allow_fallback=False,
                    ).load()
                    result["parsed_text"] = documents[0].page_content if documents else None
                    result["text_parser"] = "mineru"
                finally:
                    temp_path.unlink(missing_ok=True)
            result["parsed_text_format"] = "markdown" if result["parsed_text"] else None
            result["media_refs"] = _MARKDOWN_MEDIA_RE.findall(result["parsed_text"] or "")
            if not result["parsed_text"]:
                raise ValueError("MinerU produced no Markdown content")
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
    input_role: str = "",
) -> dict[str, Any]:
    from app.data.ingestion.source_admission import assess_source_admission

    original_filename = file.filename or "unknown"
    filename = _normalized_upload_filename(original_filename)
    content = await file.read()
    source_digest = "sha256:" + hashlib.sha256(content).hexdigest()
    parsed = await _parse_upload(file, content, file_category=file_category)
    dtype = infer_data_type_from_filename(filename) or parsed.get("gis_data_type")
    parsed["gis_data_type"] = dtype
    assessment = assess_source_admission(
        input_role=input_role,
        source="upload",
        category=file_category,
        filename=filename,
        parsed_text=str(parsed.get("parsed_text") or ""),
        gis_data=(
            parsed.get("gis_data")
            if isinstance(parsed.get("gis_data"), dict)
            else None
        ),
        gis_data_type=str(dtype or ""),
    )
    file_id = await create_uploaded_file_async(
        session_id=session_id,
        file_category=file_category,
        input_role=assessment.input_role,
        admission_status=assessment.status,
        admission_reason=assessment.reason,
        admission_signals=list(assessment.signals),
        file_type=parsed["file_type"],
        filename=filename,
        original_filename=original_filename,
        file_size=len(content),
        content_type=file.content_type or "application/octet-stream",
        source_digest=source_digest,
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
        "input_role": assessment.input_role,
        "admission_status": assessment.status,
        "admission_reason": assessment.reason,
        "admission_signals": list(assessment.signals),
        "file_type": parsed["file_type"],
        "size_bytes": len(content),
        "checksum": source_digest.removeprefix("sha256:"),
        "source_digest": source_digest,
        **parsed,
    }


__all__ = [
    "process_uploaded_file",
    "infer_data_type_from_filename",
    "audit_geojson_geometry",
    "parse_vector_file_bytes",
    "parse_raster_file_bytes",
    "parse_table_file_bytes",
]
