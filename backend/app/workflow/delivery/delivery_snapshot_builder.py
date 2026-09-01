"""Build the authoritative DELIVER spatial snapshot and its projections."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any


@dataclass
class SpatialDeliveryProducts:
    snapshot: Any = None
    planned_geojson: dict[str, Any] | None = None
    render_layers: list[dict[str, Any]] = field(default_factory=list)
    export_result: dict[str, Any] | None = None
    error: str = ""
    spatial_context_unavailable: bool = False
    spatial_context_reason: str = ""


def _catalog_geojson(snapshot: Any) -> dict[str, Any] | None:
    """Copy only normalized DATA geometry into the immutable baseline."""

    if snapshot is None:
        return None
    representations: dict[str, list[Any]] = {}
    for item in list(getattr(snapshot, "representations", None) or []):
        if str(getattr(item, "status", "") or "") != "available":
            continue
        source_ref = str(getattr(item, "source_feature_ref", "") or "")
        if source_ref:
            representations.setdefault(source_ref, []).append(item)
    features: list[dict[str, Any]] = []
    for item in list(getattr(snapshot, "features", None) or []):
        geometry = getattr(item, "normalized_geometry", None)
        crs = str(getattr(item, "normalized_crs", "") or "")
        source_ref = str(getattr(item, "source_feature_ref", "") or "")
        if not isinstance(geometry, dict) or not geometry.get("type") or not crs:
            continue
        rows = representations.get(source_ref, [])
        properties = {
            "source_feature_ref": source_ref,
            "dataset_ref": str(getattr(item, "dataset_ref", "") or ""),
            "layer_ref": str(getattr(item, "layer_ref", "") or ""),
            "geometry_kind": str(getattr(item, "geometry_kind", "") or ""),
            "source_crs": str(getattr(item, "source_crs", "") or ""),
            "normalized_crs": crs,
            "source_snapshot_ref": str(getattr(snapshot, "snapshot_id", "") or ""),
            "source_feature_digest": str(
                getattr(item, "source_feature_digest", "") or ""
            ),
            "representation_refs": sorted({
                str(getattr(row, "representation_ref", "") or "")
                for row in rows
                if str(getattr(row, "representation_ref", "") or "")
            }),
            "resource_refs": sorted({
                str(getattr(row, "resource_ref", "") or "")
                for row in rows
                if str(getattr(row, "resource_ref", "") or "")
            }),
            "source_attributes": json.loads(json.dumps(
                dict(getattr(item, "raw_attributes", None) or {}),
                ensure_ascii=False,
                default=str,
            )),
            "layer_role": "baseline",
            "status": "observed",
        }
        features.append({
            "type": "Feature",
            "id": source_ref,
            "properties": properties,
            "geometry": geometry,
        })
    if not features:
        return None
    return {"type": "FeatureCollection", "features": features}


def build_spatial_delivery_products(
    *,
    session_id: str,
    village_name: str,
    data_catalog_snapshot: Any = None,
    spatial_changeset: Any = None,
    parent_digests: dict[str, str] | None = None,
    planned_changes: list[Any],
    planned_state: Any,
    validation_result: dict[str, Any],
) -> SpatialDeliveryProducts:
    """Build products from persisted DATA and EXECUTE artifacts."""

    from app.workflow.delivery.delivery_exporter import export_delivery_products
    from app.workflow.delivery.render_layers import (
        build_delivery_render_layers,
        build_planned_overlay_layers,
    )
    from app.infrastructure.export.delivery_snapshot import (
        build_delivery_spatial_snapshot_from_gis_data,
        load_complete_planned_geojson,
    )
    from app.infrastructure.paths import session_run_dir

    products = SpatialDeliveryProducts()
    catalog_geojson = _catalog_geojson(data_catalog_snapshot)
    workspace_unavailable = catalog_geojson is None
    spatial_context_reason = ""
    try:
        if catalog_geojson is None:
            raise ValueError(
                "persisted DATA catalog has no normalized spatial baseline"
            )
        change_feature_ids = {
            str(item.feature_id)
            for item in list(getattr(spatial_changeset, "features", None) or [])
        }
        planned_feature_ids = {
            str(item.feature_id)
            for item in list(getattr(planned_state, "features", None) or [])
        }
        if change_feature_ids != planned_feature_ids:
            raise ValueError(
                "PlannedState features do not match the validated SpatialChangeSet"
            )
        effective_gis_data = {
            "data_catalog_geojson": catalog_geojson,
            "current_source_kind": "immutable_data_catalog",
        }
        overlay_payloads = build_planned_overlay_layers(planned_state)
        effective_gis_data = dict(effective_gis_data)
        overlay_key_by_type = {
            "planned_project": "planned_project_geojson",
            "facility_point": "planned_facility_geojson",
            "planned_road": "planned_road_geojson",
            "development_axis": "planned_axis_geojson",
            "planning_zone": "planned_zone_geojson",
            "restoration_zone": "planned_restoration_geojson",
            "protection_zone": "planned_protection_geojson",
            "planned_features": "planned_features_geojson",
        }
        for layer in overlay_payloads:
            layer_type = str(layer.get("layerType") or "")
            payload = layer.get("data") or layer.get("geojson")
            overlay_key = overlay_key_by_type.get(layer_type)
            if overlay_key and isinstance(payload, dict):
                effective_gis_data[overlay_key] = payload
        products.snapshot = build_delivery_spatial_snapshot_from_gis_data(
            effective_gis_data,
            planned_changes=planned_changes,
            output_dir=session_run_dir(session_id) / "spatial_snapshot",
            output_artifact_ref=f"delivery-spatial-snapshot-{session_id}",
            provenance={
                "stage": "DELIVER",
                **(
                    {
                        "spatial_context": "unavailable",
                        "spatial_context_reason": spatial_context_reason,
                    }
                    if workspace_unavailable
                    else {}
                ),
            },
        )
        products.snapshot = products.snapshot.model_copy(update={
            "parent_digests": {
                **dict(products.snapshot.parent_digests or {}),
                **{
                    str(key): str(value)
                    for key, value in dict(parent_digests or {}).items()
                    if str(key).strip() and str(value).strip()
                },
            },
            "provenance": {
                **dict(products.snapshot.provenance or {}),
                "data_catalog_snapshot_ref": str(
                    getattr(data_catalog_snapshot, "snapshot_id", "") or ""
                ),
                "data_catalog_digest": str(
                    getattr(data_catalog_snapshot, "digest", "") or ""
                ),
                "spatial_changeset_ref": str(
                    getattr(spatial_changeset, "artifact_id", "") or ""
                ),
            },
        })
        products.planned_geojson = load_complete_planned_geojson(products.snapshot)
        products.render_layers = build_delivery_render_layers(products.snapshot)
        if workspace_unavailable:
            # The renderer may emit an empty baseline layer for an empty
            # FeatureCollection.  Do not expose that placeholder as a map
            # layer: the public projection must say that no spatial output
            # exists, rather than showing a zero-feature pseudo-layer.
            products.render_layers = []
        from app.workflow.delivery.delivery_validator import assess_render_quality

        quality_report = assess_render_quality(products.render_layers)
        products.snapshot = products.snapshot.model_copy(update={"quality_report": quality_report})
        checksum_payload = products.snapshot.model_dump(mode="json")
        checksum_payload["checksum"] = ""
        snapshot_checksum = hashlib.sha256(
            json.dumps(
                checksum_payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        products.snapshot = products.snapshot.model_copy(update={"checksum": snapshot_checksum})
        products.export_result = export_delivery_products(
            products.render_layers,
            snapshot=products.snapshot,
            village_name=village_name,
            session_id=session_id,
            validation_result=validation_result,
        )
        products.export_result["planned_landuse_source"] = "delivery_spatial_snapshot"
        if workspace_unavailable:
            products.error = (
                "SpatialWorkspace unavailable; delivery contains no spatial "
                "layers and remains diagnostic-only"
            )
        products.spatial_context_unavailable = workspace_unavailable
        products.spatial_context_reason = spatial_context_reason
    except Exception as exc:
        products.error = f"{type(exc).__name__}: {exc}"
    return products


__all__ = ["SpatialDeliveryProducts", "build_spatial_delivery_products"]
