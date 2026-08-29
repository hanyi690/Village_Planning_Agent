"""Deterministic checks for delivery render inputs."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from app.workflow.delivery.geometry_lineage import validate_render_feature


def assess_render_quality(render_layers: list[dict[str, Any]]) -> dict[str, Any]:
    """Validate that current and complete planned layers are renderable."""

    feature_counts: dict[str, int] = {}
    feature_ids: list[str] = []
    empty_geometry = 0
    invalid_geometry = 0
    placeholder_geometry = 0
    missing_lineage = 0
    rejected_lineage = 0
    for layer in render_layers or []:
        layer_type = str(layer.get("layerType") or layer.get("layer_type") or "layer")
        features = list((layer.get("geojson") or layer.get("data") or {}).get("features") or [])
        feature_counts[layer_type] = len(features)
        for feature in features:
            lineage = validate_render_feature(
                feature,
                planned=layer_type not in {"current_landuse", "current_boundary"},
            )
            if lineage["status"] == "diagnostic_only":
                missing_lineage += 1
            elif lineage["status"] == "rejected":
                rejected_lineage += 1
            geometry = feature.get("geometry")
            if not geometry:
                empty_geometry += 1
            else:
                try:
                    from shapely.geometry import shape

                    parsed = shape(geometry)
                    if parsed.is_empty or not parsed.is_valid:
                        invalid_geometry += 1
                    if layer_type == "development_axis" and parsed.wkt == "POINT (0 0)":
                        placeholder_geometry += 1
                except Exception:
                    invalid_geometry += 1
            props = feature.get("properties") or {}
            bsm = str(props.get("BSM") or props.get("bsm") or "")
            if bsm:
                # BSM alone is not unique in the source land-use file. Keep
                # the classification and geometry in the display identity.
                code = str(props.get("DLBM") or props.get("dlbm") or props.get("GHYTBM") or "")
                geometry_digest = hashlib.sha256(
                    json.dumps(feature.get("geometry"), sort_keys=True).encode("utf-8")
                ).hexdigest()[:12]
                feature_ids.append(f"{layer_type}:{bsm}:{code}:{geometry_digest}")
    current_count = feature_counts.get("current_landuse", 0)
    planned_count = feature_counts.get("complete_planned_landuse", 0)
    duplicate_feature_ids = sorted({item for item in feature_ids if feature_ids.count(item) > 1})
    return {
        "status": "passed"
        if current_count > 0
        and planned_count > 0
        and not empty_geometry
        and not invalid_geometry
        and not placeholder_geometry
        and not rejected_lineage
        else "failed",
        "current_layer_present": current_count > 0,
        "complete_planned_layer_present": planned_count > 0,
        "current_feature_count": current_count,
        "complete_planned_feature_count": planned_count,
        "feature_counts": feature_counts,
        "empty_geometry_count": empty_geometry,
        "invalid_geometry_count": invalid_geometry,
        "placeholder_geometry_count": placeholder_geometry,
        "missing_lineage_count": missing_lineage,
        "rejected_lineage_count": rejected_lineage,
        "duplicate_feature_ids": duplicate_feature_ids,
    }


__all__ = ["assess_render_quality"]
