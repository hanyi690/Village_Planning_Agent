"""Build all spatial delivery products from one authoritative snapshot."""

from __future__ import annotations

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
    gis_data: dict[str, Any],
    allocated_geojson: dict[str, Any],
    planned_changes: list[Any],
    planned_state: Any,
    validation_result: dict[str, Any],
) -> SpatialDeliveryProducts:
    """Build snapshot, renderer input and export from the same planned layer."""
    from app.agent.deliver.render_layers import build_delivery_render_layers
    from app.modules.spatial_ops.io import (
        build_delivery_spatial_snapshot_from_gis_data,
        load_complete_planned_geojson,
    )
    from app.modules.spatial_ops.output.export_package import export_gdb_package
    from app.services.run_paths import session_run_dir

    products = SpatialDeliveryProducts()
    try:
        products.snapshot = build_delivery_spatial_snapshot_from_gis_data(
            gis_data,
            planned_geojson=allocated_geojson,
            planned_changes=planned_changes,
            output_dir=session_run_dir(session_id) / "spatial_snapshot",
            output_artifact_ref=f"delivery-spatial-snapshot-{session_id}",
            provenance={"stage": "DELIVER"},
        )
        products.planned_geojson = load_complete_planned_geojson(products.snapshot)
        products.render_layers = build_delivery_render_layers(
            planned_state,
            products.planned_geojson,
            gis_data,
        )
        products.export_result = export_gdb_package(
            layout_configs=products.render_layers,
            allocated_geojson=products.planned_geojson,
            gis_data=gis_data,
            village_name=village_name,
            session_id=session_id,
            validation_result=validation_result,
        )
        products.export_result["planned_landuse_source"] = "delivery_spatial_snapshot"
    except Exception as exc:
        products.error = f"{type(exc).__name__}: {exc}"
    return products


__all__ = ["SpatialDeliveryProducts", "build_spatial_delivery_products"]
