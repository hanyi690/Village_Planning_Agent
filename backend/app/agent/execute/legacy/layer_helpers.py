"""Legacy layer helpers kept for zone/allocated/custom layer construction.

These helpers build GeoJSON layers from ParcelChange entries and remain used by
the zone worker. They are grouped here by responsibility (layer construction)
rather than inline in the graph builder.
"""

from __future__ import annotations

from typing import Any

from app.utils.logger import get_logger

logger = get_logger(__name__)


def _function_zone_layer(zone_changes: list) -> dict | None:
    """Build the function_zone layer from reclassified ParcelChange entries."""
    from shapely import wkt
    from shapely.geometry import mapping as geometry_mapping

    features = []
    for change in zone_changes:
        if getattr(change, "action", "") != "reclassify":
            continue
        geometry = {}
        after_wkt = getattr(change, "after_geometry_wkt", "") or ""
        if after_wkt:
            try:
                geom = wkt.loads(after_wkt)
                if not geom.is_empty:
                    geometry = geometry_mapping(geom)
            except Exception:
                geometry = {}
        if not geometry:
            continue
        cls = getattr(change, "after_classification", None)
        bsm = str(getattr(change, "bsm", ""))
        features.append({
            "type": "Feature",
            "properties": {
                "bsm": bsm,
                "planning_land_use": str(getattr(cls, "code", "") or ""),
                "zone_type": str(getattr(cls, "canonical_name", "") or ""),
                "action": getattr(change, "action", ""),
                "source_bsm": bsm,
                "area_ha": round(float(getattr(change, "new_area_ha", 0) or 0), 2),
            },
            "geometry": geometry,
        })
    if not features:
        return None
    return {
        "layerType": "function_zone",
        "layerName": "功能分区",
        "data": {"type": "FeatureCollection", "features": features},
    }


def _allocated_geojson_from_changes(landuse: dict, zone_changes: list) -> dict:
    """landuse features with reclassified parcels tagged with their planning land use."""
    assigned = {}
    for change in zone_changes:
        if getattr(change, "action", "") != "reclassify":
            continue
        cls = getattr(change, "after_classification", None)
        assigned[str(getattr(change, "bsm", ""))] = {
            "planning_land_use": str(getattr(cls, "code", "") or ""),
            "zone_type": str(getattr(cls, "canonical_name", "") or ""),
        }
    features = []
    for feature in landuse.get("features") or []:
        props = dict(feature.get("properties") or {})
        bsm = str(props.get("BSM") or props.get("bsm") or "")
        if bsm in assigned:
            props["planning_land_use"] = assigned[bsm]["planning_land_use"]
            props["zone_type"] = assigned[bsm]["zone_type"]
        new_feature = dict(feature)
        new_feature["properties"] = props
        features.append(new_feature)
    return {"type": "FeatureCollection", "features": features}


def _assign_custom_zone_features(landuse: dict, candidates: dict, pending_zone_name: str) -> dict:
    """Tag every landuse feature with its custom zone (pending for unclaimed parcels)."""
    bsm_to_zone = {}
    for zone_name, bsms in (candidates or {}).items():
        for bsm in bsms:
            bsm_to_zone[str(bsm)] = zone_name
    features = []
    for feature in landuse.get("features") or []:
        props = dict(feature.get("properties") or {})
        bsm = str(props.get("BSM") or props.get("bsm") or "")
        props["assigned_zone"] = bsm_to_zone.get(bsm, pending_zone_name)
        new_feature = dict(feature)
        new_feature["properties"] = props
        features.append(new_feature)
    return {"type": "FeatureCollection", "features": features}


def _build_custom_planning_layer(
    state: Any,
    landuse: dict,
    custom_targets: list,
) -> dict | None:
    """Build the custom_planning_zone layer via the vocabulary-driven generator (no MIP)."""
    from app.modules.spatial_ops.zoning.custom_planning import (
        PENDING_ZONE_NAME,
        build_custom_planning_zone_layer,
        build_custom_zone_allocation_inputs,
    )
    from app.modules.spatial_ops.zoning.custom_zone_generator import CustomZoningGenerator
    from shapely.geometry import shape

    gis_bundle = getattr(state, "gis_bundle", None)
    parcels = [
        {
            "bsm": str(f.get("properties", {}).get("BSM", "") or f.get("properties", {}).get("bsm", "")),
            "dlbm": str(f.get("properties", {}).get("DLBM", "") or f.get("properties", {}).get("dlbm", "")),
            "area_ha": float(f.get("properties", {}).get("area_sqm", 0) or 0) / 10000.0,
            "geometry": shape(f["geometry"]) if f.get("geometry") else None,
        }
        for f in (landuse.get("features") or [])
    ]
    parcels = [p for p in parcels if p["bsm"] and p["geometry"] is not None]

    try:
        from app.modules.spatial_ops.zoning.vocab_context import build_parcel_contexts

        ctxs = build_parcel_contexts(parcels, gis_bundle)
        for p in parcels:
            p.update(ctxs.get(str(p["bsm"]), {}))
    except Exception as e:
        logger.warning("[EXECUTE:layout] parcel context build failed: %s", e)

    three_lines = {}
    if gis_bundle is not None:
        for bundle_key, subtype in (
            ("ecological_redline", "ecological_redline"),
            ("farmland_protection", "farmland_redline"),
        ):
            geoms = [
                getattr(f, "geometry", None)
                for f in (gis_bundle.polygons.get(bundle_key) or [])
            ]
            three_lines[subtype] = [{"geometry": shape(g)} for g in geoms if g]
    for gis_key, subtype in (
        ("ecological_protection_geojson", "ecological_redline"),
        ("farmland_protection_geojson", "farmland_redline"),
    ):
        if three_lines.get(subtype):
            continue
        source = (state.gis_data or {}).get(gis_key) or {}
        three_lines[subtype] = [
            {"geometry": shape(feature["geometry"])}
            for feature in source.get("features") or []
            if feature.get("geometry")
        ]

    intent_dict = (
        state.intent.model_dump(exclude_none=True)
        if hasattr(state.intent, "model_dump")
        else dict(state.intent or {})
    )
    if intent_dict.get("custom_zone_targets") and not intent_dict.get("vocabulary_name"):
        intent_dict["vocabulary_name"] = intent_dict["custom_zone_targets"][0].get("vocabulary_name", "")
    if not intent_dict.get("vocabulary_name"):
        logger.warning("[EXECUTE:layout] custom targets present but no vocabulary_name - skipping custom layer")
        return None

    gen = CustomZoningGenerator(parcels, intent_dict, three_lines=three_lines)
    zones, _audit = gen.generate_with_validation()
    if not zones:
        return None
    _targets, candidates, metadata = build_custom_zone_allocation_inputs(landuse, zones)
    custom_allocated = _assign_custom_zone_features(landuse, candidates, PENDING_ZONE_NAME)
    custom_layer = build_custom_planning_zone_layer(custom_allocated, metadata)
    if not custom_layer.get("features"):
        return None
    return {
        "layerType": "custom_planning_zone",
        "layerName": "自定义规划分区",
        "data": custom_layer,
    }