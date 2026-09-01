"""Project immutable DATA and EXECUTE artifacts into one spatial snapshot.

This module is deliberately outside the DELIVER workflow stage.  EXECUTE uses
it before the atomic commit so renderers never need to reopen DATA, KG,
Evidence, provider caches, or mutable workspace state.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from app.contracts.delivery.spatial_delivery_contracts import DeliverySpatialSnapshot


_WGS84_NAMES = {
    "4326",
    "crs84",
    "epsg:4326",
    "urn:ogc:def:crs:ogc:1.3:crs84",
}


def data_catalog_geojson(snapshot: Any) -> dict[str, Any] | None:
    """Copy normalized, available DATA geometry into a baseline FeatureCollection."""

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
        crs = str(getattr(item, "normalized_crs", "") or "").strip()
        source_ref = str(getattr(item, "source_feature_ref", "") or "").strip()
        if not isinstance(geometry, dict) or not geometry.get("type") or not crs:
            continue
        if crs.casefold() not in _WGS84_NAMES:
            raise ValueError(
                "delivery baseline requires a normalized WGS84 DATA representation"
            )
        rows = representations.get(source_ref, [])
        representation_refs = sorted({
            str(getattr(row, "representation_ref", "") or "")
            for row in rows
            if str(getattr(row, "representation_ref", "") or "").strip()
        })
        resource_refs = sorted({
            str(getattr(row, "resource_ref", "") or "")
            for row in rows
            if str(getattr(row, "resource_ref", "") or "").strip()
        })
        if not source_ref or not representation_refs or not resource_refs:
            raise ValueError(
                "delivery baseline feature lacks DATA representation/resource lineage"
            )
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
            "representation_refs": representation_refs,
            "resource_refs": resource_refs,
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
    return {
        "type": "FeatureCollection",
        "features": sorted(
            features,
            key=lambda feature: str(feature.get("id") or ""),
        ),
    }


def _checksum_snapshot(snapshot: DeliverySpatialSnapshot) -> DeliverySpatialSnapshot:
    payload = snapshot.model_dump(mode="json")
    payload["checksum"] = ""
    checksum = hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return snapshot.model_copy(update={"checksum": checksum})


def build_execution_delivery_snapshot(
    *,
    data_catalog_snapshot: Any,
    spatial_changeset: Any,
    planned_state: Any,
    planned_changes: list[Any],
    output_dir: str | Path,
    output_artifact_ref: str,
    parent_digests: dict[str, str] | None = None,
) -> DeliverySpatialSnapshot:
    """Freeze the exact render input before EXECUTE commits.

    No geometry is invented here.  The baseline comes from normalized DATA;
    every planned overlay is a direct projection of ``PlannedState`` and is
    cross-checked against the authoritative ``SpatialChangeSet``.
    """

    from app.infrastructure.export.delivery_snapshot import (
        build_delivery_spatial_snapshot_from_gis_data,
    )
    from app.workflow.delivery.delivery_validator import assess_render_quality
    from app.workflow.delivery.render_layers import (
        build_delivery_render_layers,
        build_planned_overlay_layers,
    )

    change_features = {
        str(item.feature_id): item
        for item in list(getattr(spatial_changeset, "features", None) or [])
    }
    planned_features = {
        str(item.feature_id): item
        for item in list(getattr(planned_state, "features", None) or [])
    }
    has_planned_geometry = bool(
        change_features
        or planned_changes
        or any(
            list(getattr(planned_state, field, None) or [])
            for field in (
                "features",
                "parcels",
                "zones",
                "overlays",
                "facilities",
                "roads",
                "axes",
            )
        )
    )
    catalog_geojson = data_catalog_geojson(data_catalog_snapshot)
    if catalog_geojson is None:
        if has_planned_geometry:
            raise ValueError(
                "planned geometry cannot be committed without a normalized DATA baseline"
            )
        return _checksum_snapshot(DeliverySpatialSnapshot(
            parent_digests={
                str(key): str(value)
                for key, value in dict(parent_digests or {}).items()
                if str(key).strip() and str(value).strip()
            },
            quality_report={
                "status": "failed",
                "reason": "no_normalized_spatial_data",
                "current_feature_count": 0,
                "complete_planned_feature_count": 0,
            },
            provenance={
                "stage": "EXECUTE",
                "projection": "approval_bound_delivery_snapshot",
                "diagnostic_reason": "no_normalized_spatial_data",
                "data_catalog_snapshot_ref": str(
                    getattr(data_catalog_snapshot, "snapshot_id", "") or ""
                ),
                "data_catalog_digest": str(
                    getattr(data_catalog_snapshot, "digest", "") or ""
                ),
            },
            delivery_status="diagnostic_only",
            statutory_complete=False,
        ))
    if change_features != planned_features:
        if set(change_features) != set(planned_features):
            raise ValueError(
                "PlannedState features do not match the committed SpatialChangeSet"
            )
        for feature_id, change in change_features.items():
            planned = planned_features[feature_id]
            if (
                str(getattr(change, "geometry_digest", "") or "")
                != str(getattr(planned, "geometry_digest", "") or "")
                or str(getattr(change, "geometry_wkt", "") or "")
                != str(getattr(planned, "geometry_wkt", "") or "")
            ):
                raise ValueError(
                    "PlannedState geometry differs from SpatialChangeSet: "
                    f"{feature_id}"
                )

    effective_gis_data: dict[str, Any] = {
        "data_catalog_geojson": catalog_geojson,
        "current_source_kind": "immutable_data_catalog",
    }
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
    for layer in build_planned_overlay_layers(planned_state):
        layer_type = str(layer.get("layerType") or "")
        payload = layer.get("data") or layer.get("geojson")
        overlay_key = overlay_key_by_type.get(layer_type)
        if overlay_key and isinstance(payload, dict):
            effective_gis_data[overlay_key] = payload

    generic_overlay = effective_gis_data.get("planned_features_geojson") or {}
    overlay_features = {
        str((item.get("properties") or {}).get("feature_id") or ""): item
        for item in list(generic_overlay.get("features") or [])
    }
    if set(overlay_features) != set(change_features):
        raise ValueError(
            "delivery planned overlay does not cover the SpatialChangeSet exactly"
        )
    for feature_id, change in change_features.items():
        properties = overlay_features[feature_id].get("properties") or {}
        if (
            str(properties.get("geometry_digest") or "")
            != str(getattr(change, "geometry_digest", "") or "")
        ):
            raise ValueError(
                "delivery planned overlay geometry digest drift: " + feature_id
            )

    snapshot = build_delivery_spatial_snapshot_from_gis_data(
        effective_gis_data,
        planned_changes=planned_changes,
        output_dir=Path(output_dir),
        output_artifact_ref=output_artifact_ref,
        provenance={
            "stage": "EXECUTE",
            "projection": "approval_bound_delivery_snapshot",
        },
    )
    snapshot = snapshot.model_copy(update={
        "parent_digests": {
            **dict(snapshot.parent_digests or {}),
            **{
                str(key): str(value)
                for key, value in dict(parent_digests or {}).items()
                if str(key).strip() and str(value).strip()
            },
        },
        "provenance": {
            **dict(snapshot.provenance or {}),
            "data_catalog_snapshot_ref": str(
                getattr(data_catalog_snapshot, "snapshot_id", "") or ""
            ),
            "data_catalog_digest": str(
                getattr(data_catalog_snapshot, "digest", "") or ""
            ),
            "spatial_changeset_scenario_id": str(
                getattr(spatial_changeset, "scenario_id", "") or ""
            ),
        },
    })
    render_layers = build_delivery_render_layers(snapshot)
    quality_report = assess_render_quality(render_layers)
    if has_planned_geometry and quality_report.get("status") != "passed":
        raise ValueError(
            "delivery snapshot render quality failed before atomic commit: "
            + json.dumps(quality_report, ensure_ascii=False, sort_keys=True)
        )
    return _checksum_snapshot(
        snapshot.model_copy(update={"quality_report": quality_report})
    )


__all__ = [
    "build_execution_delivery_snapshot",
    "data_catalog_geojson",
]
