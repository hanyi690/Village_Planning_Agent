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


def build_spatial_delivery_products(
    *,
    session_id: str,
    village_name: str,
    workspace: Any,
    planned_changes: list[Any],
    planned_state: Any,
    validation_result: dict[str, Any],
) -> SpatialDeliveryProducts:
    """Build snapshot, render layers and export from one data-layer workspace."""

    from app.domain.delivery.delivery_exporter import export_delivery_products
    from app.domain.delivery.render_layers import (
        build_delivery_render_layers,
        build_planned_overlay_layers,
    )
    from app.infrastructure.export.delivery_snapshot import (
        build_delivery_spatial_snapshot_from_gis_data,
        canonical_gis_data_from_workspace,
        load_complete_planned_geojson,
    )
    from app.infrastructure.paths import session_run_dir

    products = SpatialDeliveryProducts()
    try:
        effective_gis_data = canonical_gis_data_from_workspace(workspace)
        overlay_payloads = build_planned_overlay_layers(planned_state)
        effective_gis_data = dict(effective_gis_data)
        overlay_key_by_type = {
            "planned_project": "planned_project_geojson",
            "planned_project_point": "planned_project_point_geojson",
            "facility_point": "planned_facility_geojson",
            "planned_road": "planned_road_geojson",
            "development_axis": "planned_axis_geojson",
            "planning_zone": "planned_zone_geojson",
            "restoration_zone": "planned_restoration_geojson",
            "protection_zone": "planned_protection_geojson",
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
            provenance={"stage": "DELIVER"},
        )
        products.planned_geojson = load_complete_planned_geojson(products.snapshot)
        products.render_layers = build_delivery_render_layers(products.snapshot)
        from app.domain.delivery.delivery_validator import assess_render_quality

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
    except Exception as exc:
        products.error = f"{type(exc).__name__}: {exc}"
    return products


__all__ = ["SpatialDeliveryProducts", "build_spatial_delivery_products"]
