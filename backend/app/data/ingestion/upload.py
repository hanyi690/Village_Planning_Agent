"""Upload parsing and persistence owned by the data layer."""

from __future__ import annotations

import asyncio
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
from app.infrastructure.paths import run_tmp_root

logger = logging.getLogger(__name__)
_MARKDOWN_MEDIA_RE = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")


async def _read_upload_with_budget(file: UploadFile, max_bytes: int) -> tuple[bytes, int, str, bool]:
    """Read a bounded prefix while hashing the complete upload stream."""

    hasher = hashlib.sha256()
    prefix = await file.read(max_bytes + 1)
    hasher.update(prefix)
    total = len(prefix)
    exceeded = len(prefix) > max_bytes
    while exceeded:
        chunk = await file.read(1024 * 1024)
        if not chunk:
            break
        hasher.update(chunk)
        total += len(chunk)
    return prefix[:max_bytes], total, "sha256:" + hasher.hexdigest(), exceeded


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


def _upload_declared_crs(parsed: dict[str, Any]) -> str:
    """Extract a declared CRS; only normalize the explicit CRS84 alias."""

    raw = parsed.get("gis_data")
    if not isinstance(raw, dict):
        return "non-spatial" if parsed.get("parsed_text") else ""
    value = raw.get("crs") or raw.get("source_crs") or raw.get("crs_name") or ""
    if isinstance(value, dict):
        value = (value.get("properties") or {}).get("name") or value.get("name") or ""
    text = str(value or "").strip()
    if text.casefold() in {"crs84", "urn:ogc:def:crs:ogc:1.3:crs84"}:
        return "EPSG:4326"
    return text


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


def _parse_upload(
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
            result["geometry_audit"] = audit_geojson_geometry(geojson)
        elif file_type in {"shapefile", "kml", "gis_file"}:
            geojson = parse_vector_file_bytes(content, filename)
            result["gis_data"] = geojson
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
    layer_ref: str = "",
    boundary_scope_mode: str = "",
) -> dict[str, Any]:
    from app.core.settings import (
        DATA_MAX_TABLE_ROWS,
        DATA_MAX_TEXT_CHARS,
        DATA_MAX_UPLOAD_BYTES,
        DATA_TEMPORAL_ADMISSION_LLM_ENABLED,
    )
    from app.data.ingestion.source_admission import (
        assess_uploaded_source_admission,
    )
    from app.modules.data.application import DataAdmissionFacade
    from app.contracts.data.admission_contracts import DataAdmissionRequest

    original_filename = file.filename or "unknown"
    filename = _normalized_upload_filename(original_filename)
    content, total_size, source_digest, budget_exceeded = await _read_upload_with_budget(
        file,
        DATA_MAX_UPLOAD_BYTES,
    )
    if budget_exceeded:
        parsed = {
            "file_type": classify_file_type(filename),
            "parsed_text": None,
            "gis_data": None,
            "gis_data_type": None,
            "parse_status": "failed",
            "parse_error": "upload_size_exceeded",
            "geometry_audit": None,
            "parsed_text_format": None,
            "text_parser": None,
            "media_refs": [],
            "source_format": Path(filename).suffix.lower().lstrip("."),
        }
    else:
        parsed = await asyncio.to_thread(
            _parse_upload,
            file,
            content,
            file_category=file_category,
        )
    # File suffix is a transport/decoder hint only.  Semantic layer identity
    # and boundary scope must be declared by the caller, never guessed from
    # an untrusted filename or business field.
    dtype = parsed.get("gis_data_type")
    parsed["gis_data_type"] = dtype
    table_rows = 0
    if isinstance(parsed.get("gis_data"), dict) and str(parsed["gis_data"].get("type") or "").casefold() == "tableresource":
        table_rows = sum(
            len(table.get("rows") or ())
            for table in parsed["gis_data"].get("tables") or ()
            if isinstance(table, dict)
        )
    text_exceeded = len(str(parsed.get("parsed_text") or "")) > DATA_MAX_TEXT_CHARS
    table_exceeded = table_rows > DATA_MAX_TABLE_ROWS
    budget_error = (
        "upload_size_exceeded"
        if budget_exceeded
        else "text_length_exceeded"
        if text_exceeded
        else "table_row_count_exceeded"
        if table_exceeded
        else ""
    )
    if budget_error:
        from app.data.ingestion.source_admission import SourceAdmissionAssessment

        assessment = SourceAdmissionAssessment(
            declared_role=input_role or "unclassified",
            input_role="unclassified",
            status="quarantined",
            reason=budget_error,
            signals=(
                f"budget:max_upload_bytes={DATA_MAX_UPLOAD_BYTES}",
                f"budget:max_text_chars={DATA_MAX_TEXT_CHARS}",
                f"budget:max_table_rows={DATA_MAX_TABLE_ROWS}",
            ),
        )
    else:
        assessment = await assess_uploaded_source_admission(
            input_role=input_role,
            category=file_category,
            filename=filename,
            parsed_text=str(parsed.get("parsed_text") or ""),
            gis_data=(
                parsed.get("gis_data")
                if isinstance(parsed.get("gis_data"), dict)
                else None
            ),
            gis_data_type=str(dtype or ""),
            parse_status=str(parsed.get("parse_status") or "failed"),
            temporal_llm_enabled=DATA_TEMPORAL_ADMISSION_LLM_ENABLED,
        )
    suffix = Path(filename).suffix.casefold()
    declared_media_type = {
        ".geojson": "application/geo+json",
        ".json": "application/geo+json",
        ".zip": "application/x-esri-shapefile",
        ".shp": "application/x-esri-shapefile",
        ".gpkg": "application/geopackage+sqlite3",
        ".gdb": "application/geopackage+sqlite3",
        ".kml": "application/vnd.google-earth.kml+xml",
        ".kmz": "application/vnd.google-earth.kml+xml",
        ".gml": "application/gml+xml",
        ".csv": "text/csv",
        ".tsv": "text/tab-separated-values",
        ".xls": "application/vnd.ms-excel",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".tif": "image/tiff",
        ".tiff": "image/tiff",
        ".img": "image/tiff",
        ".asc": "image/tiff",
        ".md": "text/markdown",
        ".markdown": "text/markdown",
    }.get(suffix, "text/markdown" if parsed.get("parsed_text") else "application/octet-stream")
    adapter_hint = (
        "file_vector"
        if declared_media_type in {
            "application/geo+json", "application/x-esri-shapefile",
            "application/geopackage+sqlite3", "application/vnd.google-earth.kml+xml",
            "application/gml+xml",
        }
        else "table"
        if declared_media_type in {
            "text/csv", "text/tab-separated-values", "application/vnd.ms-excel",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        }
        else "local_raster"
        if declared_media_type == "image/tiff"
        else "document"
        if declared_media_type == "text/markdown"
        else "unsupported"
    )
    raw_input = parsed.get("gis_data") or parsed.get("parsed_text")
    request = DataAdmissionRequest(
        session_id=session_id,
        source_ref=f"upload:{session_id}:{source_digest}",
        content_digest=source_digest,
        content=raw_input,
        normalized_input=raw_input,
        source_kind="upload",
        declared_media_type=declared_media_type,
        declared_encoding="UTF-8",
        declared_crs=_upload_declared_crs(parsed),
        adapter_hint=adapter_hint,
        expected_role=assessment.input_role,
        policy_context={
            "artifact_root": str(run_tmp_root()),
            "source_admission": assessment.reason,
            "classifier_ref": assessment.classifier_ref,
            "classifier_input_digest": assessment.classifier_input_digest,
            "classifier_output_digest": assessment.classifier_output_digest,
            "classifier_model": assessment.classifier_model,
            "classifier_confidence": assessment.classifier_confidence,
            "layer_ref": str(layer_ref or ""),
            "boundary_scope_mode": str(boundary_scope_mode or ""),
            "source_filename": filename,
            "content_size_bytes": total_size,
            "budget_state": {
                "max_upload_bytes": DATA_MAX_UPLOAD_BYTES,
                "observed_upload_bytes": total_size,
            },
            "budget_error": budget_error,
        },
    )
    facade = DataAdmissionFacade()
    if assessment.status == "admitted":
        admission_result = await asyncio.to_thread(
            DataAdmissionFacade._admit_in_worker,
            facade,
            request,
        )
    else:
        admission_result = facade.record_ingress_admission(request, assessment)
    if admission_result.receipt.state == "ADMITTED":
        persisted_role = "current_evidence"
        persisted_status = "admitted"
    elif assessment.status in {"control_only", "reference_only", "excluded"}:
        persisted_role = assessment.input_role
        persisted_status = assessment.status
    else:
        persisted_role = "unclassified"
        persisted_status = "quarantined"
    receipt_descriptor = admission_result.receipt_artifact_ref
    gap_descriptor = admission_result.gap_artifact_ref
    lifecycle = list(admission_result.receipt.lifecycle)
    artifact_refs = dict(admission_result.to_state_patch().get("artifact_refs") or {})
    artifact_root = str(request.policy_context.get("artifact_root") or run_tmp_root())
    file_id = await create_uploaded_file_async(
        session_id=session_id,
        file_category=file_category,
        input_role=persisted_role,
        admission_status=persisted_status,
        admission_reason=(
            assessment.reason
            if admission_result.receipt.state == "ADMITTED"
            else admission_result.receipt.reason_code
        ),
        admission_signals=list(assessment.signals),
        admission_attempt_ref=admission_result.receipt.attempt_ref,
        admission_receipt_ref=(
            receipt_descriptor.model_dump(mode="json")
            if receipt_descriptor is not None
            else None
        ),
        admission_gap_ref=(
            gap_descriptor.model_dump(mode="json")
            if gap_descriptor is not None
            else None
        ),
        admission_lifecycle=lifecycle,
        admission_artifact_refs=artifact_refs,
        admission_artifact_root=artifact_root,
        file_type=parsed["file_type"],
        filename=filename,
        original_filename=original_filename,
        file_size=total_size,
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
        "input_role": persisted_role,
        "admission_status": persisted_status,
        "admission_reason": (
            assessment.reason
            if admission_result.receipt.state == "ADMITTED"
            else admission_result.receipt.reason_code
        ),
        "admission_signals": list(assessment.signals),
        "admission_attempt_ref": admission_result.receipt.attempt_ref,
        "admission_receipt_ref": (
            receipt_descriptor.model_dump(mode="json")
            if receipt_descriptor is not None
            else None
        ),
        "admission_gap_ref": (
            gap_descriptor.model_dump(mode="json")
            if gap_descriptor is not None
            else None
        ),
        "admission_lifecycle": lifecycle,
        "admission_artifact_refs": artifact_refs,
        "admission_artifact_root": artifact_root,
        "file_type": parsed["file_type"],
        "size_bytes": total_size,
        "checksum": source_digest.removeprefix("sha256:"),
        "source_digest": source_digest,
        **parsed,
    }


__all__ = [
    "process_uploaded_file",
    "audit_geojson_geometry",
    "parse_vector_file_bytes",
    "parse_raster_file_bytes",
    "parse_table_file_bytes",
]
