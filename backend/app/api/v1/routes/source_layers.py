"""Read-only projection of an admitted session DATA catalog."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from fastapi import APIRouter, Query

from app.api.v1.contracts import (
    CurrentSourceLayer,
    CurrentSourceLayerCollection,
    CurrentSourceRaster,
)


router = APIRouter(prefix="/api/v1", tags=["Stable v1"])


def _feature_geojson(feature: Any) -> dict[str, Any] | None:
    """Project one normalized executable feature without changing geometry."""

    geometry = getattr(feature, "normalized_geometry", None)
    if not isinstance(geometry, dict):
        return None
    normalized_kind = str(
        getattr(feature, "normalized_geometry_kind", "unknown") or "unknown"
    ).casefold()
    if normalized_kind not in {"point", "line", "polygon"}:
        return None
    properties = dict(getattr(feature, "raw_attributes", {}) or {})
    properties.update({
        "source_dataset_ref": str(getattr(feature, "dataset_ref", "") or ""),
        "source_feature_ref": str(getattr(feature, "source_feature_ref", "") or ""),
        "source_layer_ref": str(getattr(feature, "layer_ref", "") or ""),
        "source_feature_digest": str(
            getattr(feature, "source_feature_digest", "") or ""
        ),
        "geometry_authority": "data_resource_catalog",
    })
    return {"type": "Feature", "geometry": geometry, "properties": properties}


def _catalog_projection(catalog: Any) -> CurrentSourceLayerCollection:
    """Project only normalized executable features from an admitted catalog."""

    snapshot = getattr(catalog, "snapshot", catalog)
    if snapshot is None:
        return CurrentSourceLayerCollection(
            village_name="",
            diagnostics=["admitted DATA catalog is unavailable"],
        )

    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    raster_features: list[Any] = []
    skipped_read_only = 0
    for feature in getattr(snapshot, "features", ()) or ():
        if str(getattr(feature, "geometry_kind", "") or "").casefold() == "raster":
            raster_features.append(feature)
            continue
        projected = _feature_geojson(feature)
        if projected is None:
            if getattr(feature, "geometry", None) is not None:
                skipped_read_only += 1
            continue
        grouped[
            (
                str(getattr(feature, "dataset_ref", "") or ""),
                str(getattr(feature, "layer_ref", "") or ""),
            )
        ].append(projected)

    layers: list[CurrentSourceLayer] = []
    for (dataset_ref, layer_ref), features in sorted(grouped.items()):
        layer_name = layer_ref or dataset_ref or "unnamed-resource"
        layers.append(CurrentSourceLayer(
            source_name=dataset_ref or layer_name,
            source_layer_type=layer_ref,
            layer_type="generic",
            layer_name=layer_name,
            display_role="current",
            crs="EPSG:4326",
            feature_count=len(features),
            geojson={"type": "FeatureCollection", "features": features},
            metadata={
                "source": "data_catalog",
                "datasetRef": dataset_ref,
                "layerRef": layer_ref,
                "featureCount": len(features),
            },
        ))

    rasters: list[CurrentSourceRaster] = []
    for feature in raster_features:
        raw = dict(getattr(feature, "raw_attributes", {}) or {})
        layer_name = str(getattr(feature, "layer_ref", "") or "raster")
        valid = str(getattr(feature, "validity_status", "") or "") == "valid"
        rasters.append(CurrentSourceRaster(
            source_name=str(getattr(feature, "dataset_ref", "") or layer_name),
            layer_name=layer_name,
            layer_type="raster",
            format=str(raw.get("format") or ""),
            crs=str(
                getattr(feature, "normalized_crs", "")
                or getattr(feature, "source_crs", "")
                or ""
            ),
            available=valid,
            source_ref=(
                f"data:{getattr(feature, 'dataset_ref', '')}:"
                f"{getattr(feature, 'source_feature_ref', '')}"
            ),
            reason="" if valid else "raster resource is not admitted as valid",
        ))

    diagnostics = []
    if skipped_read_only:
        diagnostics.append(
            f"{skipped_read_only} read-only or non-executable feature(s) omitted from map projection"
        )
    return CurrentSourceLayerCollection(
        village_name="",
        center=None,
        layers=layers,
        rasters=rasters,
        diagnostics=diagnostics,
    )


@router.get("/source-layers", response_model=CurrentSourceLayerCollection)
async def get_current_source_layers(
    session_id: str = Query(..., min_length=1),
    village_name: str = Query(default=""),
) -> CurrentSourceLayerCollection:
    """Expose normalized features from one admitted session catalog.

    This endpoint is a presentation projection only. It never discovers a
    source by filename, initializes the YAML source registry, or reads a
    fixed village directory.
    """

    catalog = None
    try:
        from app.infrastructure.context_runtime.manager import get_cached_context

        context = get_cached_context(str(session_id))
        catalog = getattr(context, "data_resource_catalog", None)
    except Exception:
        catalog = None
    if catalog is None:
        try:
            from app.data.catalog.session_resource_catalog import load_session_data_catalog

            catalog = await load_session_data_catalog(
                str(session_id),
                village_name=village_name,
            )
        except Exception:
            catalog = None
    projection = _catalog_projection(catalog)
    return projection.model_copy(update={"village_name": village_name})


__all__ = ["get_current_source_layers", "router"]
