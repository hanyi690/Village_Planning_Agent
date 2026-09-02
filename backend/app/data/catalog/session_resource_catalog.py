"""Build a normalized DATA catalog from session-owned uploads.

This adapter is deliberately DATA-owned.  It reads the persisted upload
records, preserves every source property, and assigns stable source refs from
the upload id plus feature ordinal.  It does not infer a planning layer or
construct a Bundle, KG entity, or geometry decision.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from app.data.resource_catalog import DataResourceCatalog


def _upload_ref(item: dict[str, Any], index: int) -> str:
    upload_id = str(item.get("id") or "").strip()
    filename = str(item.get("original_filename") or item.get("filename") or "").strip()
    token = upload_id or filename or f"{index}"
    return f"upload:{token}"


def _feature_ref(
    dataset_ref: str,
    *,
    layer_ref: str,
    source_record_id: str,
    layer_feature_index: int,
) -> str:
    """Create a stable, layer-scoped source-record identity."""

    record_identity = source_record_id or f"ordinal:{layer_feature_index}"
    material = json.dumps(
        {
            "dataset_ref": dataset_ref,
            "layer_ref": layer_ref,
            "source_record_id": record_identity,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]
    return f"{dataset_ref}:feature:{digest}"


def _source_digest(item: dict[str, Any]) -> str:
    persisted = str(item.get("source_digest") or "").strip()
    if persisted:
        return persisted
    material = item.get("gis_data")
    if material is None:
        material = str(item.get("parsed_text") or "")
    payload = json.dumps(
        material,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _admission_decision(
    *,
    source_ref: str,
    source_digest: str,
    input_role: str,
    status: str,
    resource_kind: str,
    reason: str = "",
) -> dict[str, Any]:
    material = {
        "source_ref": source_ref,
        "source_digest": source_digest,
        "input_role": input_role,
        "status": status,
        "resource_kind": resource_kind,
    }
    decision_ref = "data.admission." + hashlib.sha256(
        json.dumps(
            material,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()[:24]
    reasons = {
        "admitted": "explicit_current_evidence_channel",
        "control_only": "planning_control_channel_not_current_fact",
        "reference_only": "reference_plan_not_current_fact",
        "excluded": "planned_output_cannot_be_planning_input",
        "quarantined": "source_input_role_unclassified",
    }
    return {
        "decision_ref": decision_ref,
        **material,
        "reason": reason or reasons.get(status, "source_admission_unresolved"),
        "recovery_pointer": (
            f"source-admission:{source_ref}"
            if status == "quarantined"
            else ""
        ),
    }


async def load_session_data_catalog(
    session_id: str,
    *,
    village_name: str = "",
) -> DataResourceCatalog | None:
    """Load all persisted DATA uploads into one lossless catalog.

    ``None`` means the session has no spatial, table, Markdown, raster, or
    typed failure resource.  Callers in V2 modes must then fail closed; they
    must not fall back to a Bundle.
    """

    if not str(session_id or "").strip():
        return None
    try:
        from app.database.operations import get_uploaded_files_by_session_async

        uploads = await get_uploaded_files_by_session_async(str(session_id))
    except Exception:
        return None
    rows: list[dict[str, Any]] = []
    persisted_catalogs: list[DataResourceCatalog] = []
    admission_decisions: list[dict[str, Any]] = []
    for upload_index, item in enumerate(uploads or ()):
        if not isinstance(item, dict):
            continue
        dataset_ref = _upload_ref(item, upload_index)
        source_uri = f"upload://{dataset_ref}"
        persisted_role = str(item.get("input_role") or "unclassified").strip().casefold()
        persisted_status = str(
            item.get("admission_status") or ""
        ).strip().casefold()
        persisted_receipt = item.get("admission_receipt_ref")
        receipt_present = isinstance(persisted_receipt, dict) and bool(
            persisted_receipt.get("descriptor_digest")
        )
        if not receipt_present:
            input_role = "unclassified"
            admission_status = "quarantined"
            admission_reason = "admission_receipt_missing_or_legacy_upload"
        else:
            input_role = persisted_role
            admission_status = persisted_status or "quarantined"
            admission_reason = str(item.get("admission_reason") or "persisted_admission_receipt")
        admission_signals = [
            str(value)
            for value in item.get("admission_signals") or []
            if str(value).strip()
        ]
        if admission_status == "admitted":
            artifact_refs = item.get("admission_artifact_refs")
            catalog_ref = artifact_refs.get("data_catalog") if isinstance(artifact_refs, dict) else None
            if isinstance(catalog_ref, dict) and catalog_ref.get("descriptor_digest"):
                try:
                    from app.modules.data.application import DataApplication

                    catalog = DataApplication.load_catalog({
                        "run_id": str(catalog_ref.get("run_id") or ""),
                        "session_id": str(session_id),
                        "branch_id": str(catalog_ref.get("branch_id") or "main"),
                        "artifact_root": str(item.get("admission_artifact_root") or ""),
                        "artifact_refs": artifact_refs,
                    })
                    if catalog is not None:
                        persisted_catalogs.append(DataResourceCatalog(catalog))
                        continue
                except Exception:
                    pass
            input_role = "unclassified"
            admission_status = "quarantined"
            admission_reason = "admission_catalog_artifact_missing_or_unreadable"
        source_digest = _source_digest(item)
        resource_kind = str(
            item.get("file_type")
            or item.get("gis_data_type")
            or "upload"
        ).casefold()
        admission_decisions.append(_admission_decision(
            source_ref=dataset_ref,
            source_digest=source_digest,
            input_role=input_role,
            status=admission_status,
            resource_kind=resource_kind,
            reason=admission_reason,
        ))
        if admission_status == "quarantined":
            continue
        if admission_status != "admitted":
            continue
        geojson = item.get("gis_data")
        if not isinstance(geojson, dict):
            if str(item.get("parse_status") or "").casefold() == "failed":
                rows.append({
                    "source_dataset_ref": dataset_ref,
                    "source_feature_ref": f"{dataset_ref}:failed",
                    "layer_ref": str(item.get("file_category") or "upload"),
                    "source_uri": source_uri,
                    "geometry": None,
                    "properties": {
                        "source_dataset_ref": dataset_ref,
                        "source_uri": source_uri,
                        "source_digest": source_digest,
                        "resource_kind": "upload",
                        "input_role": input_role,
                        "admission_status": admission_status,
                        "admission_reason": admission_reason,
                        "admission_signals": admission_signals,
                        "parse_status": "failed",
                        "parse_error": str(item.get("parse_error") or "unknown_parse_failure"),
                        "upload_filename": str(item.get("original_filename") or item.get("filename") or ""),
                    },
                })
            continue
        features = geojson.get("features") if geojson.get("type") == "FeatureCollection" else None
        if geojson.get("type") == "RasterResource":
            rows.append({
                "source_dataset_ref": dataset_ref,
                "source_feature_ref": f"{dataset_ref}:raster",
                "layer_ref": str(item.get("file_category") or "raster"),
                "source_crs": str(geojson.get("crs") or ""),
                "source_uri": source_uri,
                "geometry": None,
                "properties": {
                    **dict(geojson),
                    "source_dataset_ref": dataset_ref,
                    "source_uri": source_uri,
                    "source_digest": source_digest,
                    "resource_kind": "raster",
                    "input_role": input_role,
                    "admission_status": admission_status,
                    "admission_reason": admission_reason,
                    "admission_signals": admission_signals,
                },
            })
            continue
        if geojson.get("type") == "TableResource":
            for table in list(geojson.get("tables") or []):
                if not isinstance(table, dict):
                    continue
                sheet_name = str(table.get("name") or "default")
                for row_index, table_row in enumerate(table.get("rows") or []):
                    if not isinstance(table_row, dict):
                        continue
                    rows.append({
                        "source_dataset_ref": dataset_ref,
                        "source_feature_ref": f"{dataset_ref}:table:{sheet_name}:row:{row_index}",
                        "layer_ref": sheet_name,
                        "source_uri": source_uri,
                        "geometry": None,
                        "properties": {
                            **dict(table_row),
                            "source_dataset_ref": dataset_ref,
                            "source_uri": source_uri,
                            "source_digest": source_digest,
                            "resource_kind": "table",
                            "input_role": input_role,
                            "admission_status": admission_status,
                            "admission_reason": admission_reason,
                            "admission_signals": admission_signals,
                            "table_name": sheet_name,
                            "table_row_index": row_index,
                        },
                    })
            continue
        if not isinstance(features, list):
            continue
        upload_crs = geojson.get("crs")
        filename = str(
            item.get("original_filename") or item.get("filename") or ""
        ).casefold()
        rfc7946_default = (
            "EPSG:4326"
            if str(item.get("file_type") or "").casefold() == "geojson"
            or filename.endswith((".geojson", ".json"))
            else ""
        )
        for feature_index, feature in enumerate(features):
            if not isinstance(feature, dict):
                continue
            properties = dict(feature.get("properties") or {})
            layer = str(
                properties.get("__source_layer")
                or item.get("file_category")
                or "upload"
            )
            source_record_id = str(
                properties.get("__source_record_id")
                or feature.get("id")
                or feature_index
            )
            try:
                layer_feature_index = int(
                    properties.get("__source_layer_feature_index", feature_index)
                )
            except (TypeError, ValueError):
                layer_feature_index = feature_index
            # These are source metadata, not semantic layer aliases.  Keeping
            # them alongside the original properties makes later cognition
            # and audit deterministic without requiring any fixed field.
            properties.update({
                "source_dataset_ref": dataset_ref,
                "source_uri": source_uri,
                "source_digest": source_digest,
                "upload_filename": str(item.get("original_filename") or item.get("filename") or ""),
                "input_role": input_role,
                "admission_status": admission_status,
                "admission_reason": admission_reason,
                "admission_signals": admission_signals,
            })
            properties.setdefault("source_record_id", source_record_id)
            rows.append({
                "source_dataset_ref": dataset_ref,
                "source_feature_ref": _feature_ref(
                    dataset_ref,
                    layer_ref=layer,
                    source_record_id=source_record_id,
                    layer_feature_index=layer_feature_index,
                ),
                "layer_ref": layer,
                "source_crs": (
                    properties.get("__source_crs")
                    or upload_crs
                    or rfc7946_default
                ),
                "source_uri": source_uri,
                "geometry": feature.get("geometry"),
                "properties": properties,
            })
    try:
        from app.data.catalog.session_documents import load_session_documents

        documents = await load_session_documents(
            str(session_id),
            str(village_name or ""),
            uploaded=list(uploads or ()),
        )
    except Exception:
        documents = []
    seen_document_refs: set[str] = set()
    for document_index, document in enumerate(documents):
        admission_status = str(
            document.get("admission_status") or "quarantined"
        ).strip().casefold()
        input_role = str(
            document.get("input_role") or "unclassified"
        ).strip().casefold()
        content_digest = str(document.get("content_digest") or "").strip()
        if not content_digest:
            continue
        record_id = str(document.get("record_id") or "").strip()
        document_source = str(document.get("source") or "document").casefold()
        source_ref = (
            f"document:{document_source}:"
            f"{record_id or content_digest.removeprefix('sha256:')[:24]}"
        )
        # Decisions bind exact DATA resource refs.  Make duplicate logical
        # document ids unique before emitting the decision, never afterwards.
        original_source_ref = source_ref
        duplicate_index = 2
        while source_ref in seen_document_refs:
            source_ref = f"{original_source_ref}:{duplicate_index}"
            duplicate_index += 1
        seen_document_refs.add(source_ref)
        document_dataset_ref = f"session:{session_id}:documents"
        admission_decisions.append(_admission_decision(
            source_ref=f"resource:{document_dataset_ref}:{source_ref}",
            source_digest=content_digest,
            input_role=input_role,
            status=admission_status,
            resource_kind="markdown",
            reason=(
                str(document.get("admission_reason") or "")
                + (
                    ";signals="
                    + "|".join(
                        str(value)
                        for value in document.get("admission_signals") or []
                    )
                    if document.get("admission_signals")
                    else ""
                )
            ),
        ))
        # Planning briefs/instructions stay in the workflow control channel;
        # reference plans and planned outputs stay outside the current-world
        # evidence catalog.  Unknown Markdown is represented only as a
        # quarantined descriptor so DATA can fail closed without exposing its
        # body to KG/EVIDENCE/RAG.
        if admission_status != "admitted":
            continue
        locator = str(document.get("locator") or "").strip()
        rows.append({
            "source_dataset_ref": document_dataset_ref,
            "source_feature_ref": source_ref,
            "layer_ref": str(document.get("category") or "documents"),
            "source_uri": locator,
            "geometry": None,
            "properties": {
                "source_dataset_ref": document_dataset_ref,
                "source_uri": locator,
                "resource_kind": "markdown",
                "content_format": "markdown",
                "content_digest": content_digest,
                "content_ref": locator if admission_status == "admitted" else "",
                "char_count": int(document.get("char_count") or 0),
                "parser": str(document.get("parser") or ""),
                "media_refs": list(document.get("media_refs") or []),
                "media_policy": str(document.get("media_policy") or "deferred"),
                "document_name": str(document.get("name") or ""),
                "document_source": str(document.get("source") or ""),
                "document_input_role": input_role,
                "admission_status": admission_status,
                "admission_reason": str(document.get("admission_reason") or ""),
                "admission_signals": list(document.get("admission_signals") or []),
            },
        })
    if not rows and not admission_decisions and not persisted_catalogs:
        return None
    catalog = None
    if rows:
        catalog = DataResourceCatalog.from_records(
            rows,
            dataset_ref=f"session:{session_id}:uploads",
            name=str(village_name or ""),
            source_uris=sorted({str(row.get("source_uri")) for row in rows if row.get("source_uri")}),
            admission_decisions=admission_decisions,
        )
    for persisted_catalog in persisted_catalogs:
        catalog = persisted_catalog if catalog is None else catalog.merge(
            persisted_catalog,
            snapshot_id=f"data-session:{session_id}",
        )
    if catalog is not None and admission_decisions:
        existing_decisions = {
            item.decision_ref: item
            for item in catalog.snapshot.admission_decisions
        }
        for decision in admission_decisions:
            existing_decisions[str(decision["decision_ref"])] = _admission_decision(
                source_ref=str(decision["source_ref"]),
                source_digest=str(decision.get("source_digest") or ""),
                input_role=str(decision.get("input_role") or "unclassified"),
                status=str(decision.get("status") or "quarantined"),
                resource_kind=str(decision.get("resource_kind") or ""),
                reason=str(decision.get("reason") or ""),
            )
        catalog = DataResourceCatalog(catalog.snapshot.model_copy(update={
            "admission_decisions": tuple(existing_decisions.values()),
        }))
    return catalog


async def load_session_boundary_scope(session_id: str) -> Any | None:
    """Reload the persisted boundary scope without rebuilding it from uploads."""

    if not str(session_id or "").strip():
        return None
    try:
        from app.database.operations import get_uploaded_files_by_session_async
        from app.modules.data.application import DataApplication

        uploads = await get_uploaded_files_by_session_async(str(session_id))
    except Exception:
        return None
    for item in uploads or ():
        if not isinstance(item, dict) or str(item.get("admission_status") or "").casefold() != "admitted":
            continue
        refs = item.get("admission_artifact_refs")
        if not isinstance(refs, dict) or not refs.get("boundary_scope"):
            continue
        try:
            return DataApplication.load_boundary_scope({
                "session_id": str(session_id),
                "run_id": str(refs["boundary_scope"].get("run_id") or ""),
                "branch_id": str(refs["boundary_scope"].get("branch_id") or "main"),
                "artifact_root": str(item.get("admission_artifact_root") or ""),
                "artifact_refs": refs,
            })
        except Exception:
            continue
    return None


__all__ = ["load_session_boundary_scope", "load_session_data_catalog"]
