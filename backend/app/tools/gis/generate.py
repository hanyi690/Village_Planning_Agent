"""generate_layout tool — spatial layout generation via ZoneGenerator + FacilityPlacer + AxisBuilder.

Delegates to real layout components (no fallback):
  - ZoneGenerator: function_zone layer (merged by zone type)
  - FacilityPlacer: facility_point layer (4-strategy placement)
  - AxisBuilder: infrastructure layer (一核一带三区)
  - Planning zone: per-parcel DLBM → 4-zone classification (inline)
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Annotated

from langchain_core.tools import tool, InjectedToolCallId
from langgraph.prebuilt import InjectedState
from langgraph.types import Command

from app.utils.logger import get_logger

logger = get_logger(__name__)


from ._helpers import make_result, to_tool_message


def _intent_from_typed(intent: Any) -> Any:
    """Convert typed SpatialPlanningIntent to UnifiedSpatialIntent.

    Phase 4: replaces _intent_from_dict bridge. Now intent comes from PARSE
    as SpatialPlanningIntent — no dict conversion needed in the pipeline.
    """
    from app.modules.gis.schema.intent import (
        Direction, Density, ZoneIntent, FacilityIntent,
        AxisIntent, ConstraintIntent, UnifiedSpatialIntent,
    )

    # Typed path: SpatialPlanningIntent.zone_targets (List[ZoneTarget])
    if hasattr(intent, 'zone_targets'):
        zones = []
        for i, zt in enumerate(intent.zone_targets):
            pref_dir = zt.spatial_preference.direction if zt.spatial_preference else "center"
            density_str = zt.density if hasattr(zt, 'density') else "medium"
            zones.append(ZoneIntent(
                zone_id=f"Z{i + 1:02d}",
                land_use=zt.land_use if hasattr(zt, 'land_use') else "",
                dlbm=zt.dlbm if hasattr(zt, 'dlbm') else "",
                area_ratio=zt.area_ratio if hasattr(zt, 'area_ratio') else 0.0,
                direction=Direction(str(pref_dir)),
                density=Density(str(density_str)),
                preserve_existing=True,
            ))

        facilities = []
        if hasattr(intent, 'facilities'):
            for i, ft in enumerate(intent.facilities):
                facilities.append(FacilityIntent(
                    facility_id=f"F{i + 1:02d}",
                    facility_type=ft.type if hasattr(ft, 'type') else "",
                    target_zone="",
                    location_hint=ft.location_hint if hasattr(ft, 'location_hint') else "",
                    status=ft.status if hasattr(ft, 'status') else "existing",
                ))

        axes = []
        if hasattr(intent, 'development_axes'):
            for i, at in enumerate(intent.development_axes):
                axes.append(AxisIntent(
                    axis_id=f"A{i + 1:02d}",
                    axis_type="primary",
                    direction=Direction(str(at.direction if hasattr(at, 'direction') else "center")),
                    label="",
                ))

        return UnifiedSpatialIntent(
            zones=zones, facilities=facilities, axes=axes,
            constraints=[], metadata={},
        )

    # Legacy dict fallback (should be unreachable now)
    if isinstance(intent, dict):
        zones = []
        for z in intent.get("zones", []):
            zones.append(ZoneIntent(
                zone_id=z["zone_id"],
                land_use=z.get("land_use", ""),
                dlbm=z.get("dlbm", ""),
                area_ratio=z.get("area_ratio", 0.0),
                direction=Direction(z.get("direction", "center")),
                density=Density(z.get("density", "medium")),
                preserve_existing=z.get("preserve_existing", True),
            ))

        facilities = []
        for f in intent.get("facilities", []):
            facilities.append(FacilityIntent(
                facility_id=f.get("facility_id", f.get("name", "")),
                facility_type=f.get("facility_type", ""),
                target_zone=f.get("target_zone", ""),
                location_hint=f.get("location_hint", ""),
                status=f.get("status", "existing"),
            ))

        axes = []
        for a in intent.get("axes", []):
            axes.append(AxisIntent(
                axis_id=a.get("axis_id", ""),
                axis_type=a.get("axis_type", "primary"),
                direction=Direction(a.get("direction", "center")),
                label=a.get("label", ""),
            ))

        constraints = []
        for c in intent.get("constraints", []):
            constraints.append(ConstraintIntent(
                constraint_id=c.get("constraint_id", c.get("id", "")),
                constraint_type=c.get("type", c.get("constraint_type", "")),
                strict=c.get("strict", True),
            ))

        return UnifiedSpatialIntent(
            zones=zones, facilities=facilities, axes=axes,
            constraints=constraints, metadata=intent.get("metadata", {}),
        )
    return None


def _build_protection_zones(gis_data: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Extract protection zone dict from gis_data."""
    pz: Dict[str, Dict[str, Any]] = {}
    for key in ("farmland_protection_geojson", "ecological_protection_geojson",
                "historical_protection_geojson"):
        val = gis_data.get(key)
        if val and val.get("features"):
            name = key.replace("_geojson", "").replace("_protection", "")
            pz[name] = val
    return pz


# ── main tool ──────────────────────────────────────────────────────────

@tool
def generate_layout(
    intent: Annotated[Any, InjectedState("intent")],
    allocated_geojson: Annotated[Optional[Dict[str, Any]], InjectedState("allocated_geojson")],
    gis_data: Annotated[Dict[str, Optional[Dict[str, Any]]], InjectedState("gis_data")],
    village_name: Annotated[str, InjectedState("village_name")],
    kg_constraints: Annotated[Optional[List[Dict[str, Any]]], InjectedState("kg_constraints")] = None,
    tool_call_id: Annotated[str, InjectedToolCallId] = "",
) -> Command:
    """Generate multi-layer spatial layout: function zones, planning zones, facilities,
    axes, space control zones (510/520/530/540), and land use zones (V/N/E).

    Delegates to ZoneGenerator (merged zones), FacilityPlacer (4-strategy),
    AxisBuilder (spatial structure), SpaceControlZoneGenerator (4-class),
    and LandUseZoneGenerator (V/N/E classification).
    Intent and GIS data auto-injected.
    """
    t0 = time.time()
    layers: List[Dict[str, Any]] = []

    try:
        # ── Function zone layer (ZoneGenerator) ─────────────────────
        func_layer = _generate_function_zones(intent, gis_data)
        if func_layer:
            layers.append(func_layer)

        # ── Planning zone layer (per-parcel DLBM → 4-zone) ─────────
        plan_layer = _make_planning_zone_layer(allocated_geojson, gis_data)
        if plan_layer:
            layers.append(plan_layer)

        # ── Facility layer (FacilityPlacer) ─────────────────────────
        fac_layer = _generate_facilities(intent, gis_data)
        if fac_layer:
            layers.append(fac_layer)

        # ── Axis layer (AxisBuilder) ─────────────────────────────────
        axis_layer = _generate_axes(intent, gis_data)
        if axis_layer:
            layers.append(axis_layer)

        # ── Space Control Zone (510/520/530/540) ──────────────────
        space_ctrl_layer = _generate_space_control_zone(gis_data, allocated_geojson, intent)
        if space_ctrl_layer:
            layers.append(space_ctrl_layer)

        # ── Land Use Zone (V/N/E classification) ───────────────────
        land_use_layer = _generate_land_use_zone(allocated_geojson, gis_data)
        if land_use_layer:
            layers.append(land_use_layer)

        elapsed = round(time.time() - t0, 2)
        return Command(update={
            "layout_configs": layers,
            "messages": [to_tool_message(make_result(True, data={
                "layer_count": len(layers),
                "elapsed_s": elapsed,
                "layers": [lyr.get("layerType", "?") for lyr in layers],
            }), tool_call_id)],
        })

    except Exception as e:
        logger.error(f"Layout generation failed: {e}", exc_info=True)
        return Command(update={
            "messages": [to_tool_message(make_result(False, error=str(e)), tool_call_id)],
        })


# ── layer generators ───────────────────────────────────────────────────

def _generate_function_zones(
    intent: Any,
    gis_data: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """Generate function_zone layer via ZoneGenerator (merged by zone type)."""
    # Typed: SpatialPlanningIntent.zone_targets
    has_zones = hasattr(intent, 'zone_targets') and intent.zone_targets
    has_zones = has_zones or (isinstance(intent, dict) and intent.get("zones"))
    if not intent or not has_zones:
        return None

    landuse = gis_data.get("landuse_current_geojson") or gis_data.get("allocated_geojson")
    if not landuse or not landuse.get("features"):
        return None

    from app.modules.gis.generation.zone_generator import ZoneGenerator

    boundary = gis_data.get("boundary_geojson")
    protection = _build_protection_zones(gis_data)
    unified = _intent_from_typed(intent)

    generator = ZoneGenerator()
    geojson = generator.generate(
        intent=unified,
        boundary_geojson=boundary,
        landuse_current_geojson=landuse,
        protection_zones=protection if protection else None,
    )

    feat_count = len(geojson.get("features", []))
    logger.info(f"[generate_layout] function_zone: {feat_count} features (ZoneGenerator)")

    return {
        "layerType": "function_zone",
        "data": geojson,
    }


def _make_planning_zone_layer(
    allocated: Optional[Dict[str, Any]],
    gis_data: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """Generate planning_zone layer — per-parcel DLBM → 4 planning zones.

    After classifying parcels, merges adjacent same-type parcels via dissolve
    to reduce 600+ fragments to ~4-6 contiguous regions.
    """
    source = allocated or gis_data.get("landuse_current_geojson")
    if not source or not source.get("features"):
        return None

    from app.modules.gis.schema import dlbm_to_planning_zone, PLANNING_ZONE_COLORS

    features = []
    for feat in source["features"]:
        props = dict(feat.get("properties", {}))
        dlbm = str(props.get("DLBM", ""))
        assigned = props.get("assigned_zone", dlbm_to_planning_zone(dlbm))
        color = PLANNING_ZONE_COLORS.get(assigned, "#CCCCCC")

        features.append({
            "type": "Feature",
            "geometry": feat.get("geometry", {}),
            "properties": {**props, "zone_type": assigned, "color": color, "stroke": color},
        })

    # Merge adjacent same-type parcels via dissolve
    try:
        from app.modules.gis.generation.optimizer.procedural import merge_parcels
        from app.modules.gis.utils.geojson_utils import geojson_to_geodataframe, geodataframe_to_geojson
        fc = {"type": "FeatureCollection", "features": features}
        gdf = geojson_to_geodataframe(fc)
        if gdf is not None and not gdf.empty:
            merged_gdf = merge_parcels(gdf, group_column="zone_type")
            # Keep only needed columns to avoid dissolve-aggregated list values
            merged_gdf = merged_gdf[["zone_type", "area_ha", "geometry"]].copy()
            merged_geojson = geodataframe_to_geojson(merged_gdf)
            if merged_geojson and merged_geojson.get("features"):
                features = []
                for feat in merged_geojson["features"]:
                    props = feat.get("properties", {})
                    zt = str(props.get("zone_type", ""))
                    color = PLANNING_ZONE_COLORS.get(zt, "#CCCCCC")
                    area_ha = float(props.get("area_ha", 0))
                    features.append({
                        "type": "Feature",
                        "geometry": feat.get("geometry", {}),
                        "properties": {
                            "zone_type": zt,
                            "color": color,
                            "stroke": color,
                            "area_ha": round(area_ha, 2),
                        },
                    })
    except Exception as e:
        logger.warning(f"[generate_layout] merge_parcels failed: {e}, using per-parcel features")

    logger.info(f"[generate_layout] planning_zone: {len(features)} features")

    return {
        "layerType": "planning_zone",
        "data": {"type": "FeatureCollection", "features": features},
    }


def _generate_facilities(
    intent: Any,
    gis_data: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """Generate facility_point layer via FacilityPlacer (4 strategies)."""
    # Typed: SpatialPlanningIntent.facilities (List[FacilityTarget])
    facilities_raw: List[Dict[str, Any]] = []
    if hasattr(intent, 'facilities') and intent.facilities:
        for ft in intent.facilities:
            facilities_raw.append({
                "facility_id": f"F{len(facilities_raw) + 1:02d}",
                "facility_type": getattr(ft, 'type', ''),
                "type": getattr(ft, 'type', ''),
                "status": getattr(ft, 'status', 'existing_preserve'),
                "location_hint": getattr(ft, 'location_hint', ''),
                "anchor_village": getattr(ft, 'anchor_village', ''),
                "service_radius": getattr(ft, 'service_radius', None),
            })
    elif isinstance(intent, dict) and intent.get("facilities"):
        facilities_raw = intent["facilities"]
    if not facilities_raw:
        return None

    from app.modules.gis.generation.facility_placer import FacilityPlacer

    placer = FacilityPlacer()
    geojson = placer.place(
        facilities=facilities_raw,
        landuse_geojson=gis_data.get("landuse_current_geojson"),
        boundary_geojson=gis_data.get("boundary_geojson"),
        existing_pois=None,
        hazard_points_geojson=gis_data.get("geological_hazard_geojson"),
    )

    feat_count = len(geojson.get("features", []))
    logger.info(f"[generate_layout] facility_point: {feat_count} features (FacilityPlacer)")

    return {
        "layerType": "facility_point",
        "data": geojson,
    }


def _generate_axes(
    intent: Any,
    gis_data: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """Generate infrastructure/axis layer via AxisBuilder."""
    # Typed: SpatialPlanningIntent.development_axes
    has_axes = hasattr(intent, 'development_axes') and intent.development_axes
    has_axes = has_axes or (isinstance(intent, dict) and intent.get("axes"))
    if not intent or not has_axes:
        return None

    from app.modules.gis.generation.axis_builder import AxisBuilder

    unified = _intent_from_typed(intent)
    builder = AxisBuilder()
    geojson = builder.build(
        intent=unified,
        boundary_geojson=gis_data.get("boundary_geojson"),
        landuse_current_geojson=gis_data.get("landuse_current_geojson"),
    )

    if geojson is None or not geojson.get("features"):
        return None

    feat_count = len(geojson.get("features", []))
    logger.info(f"[generate_layout] infrastructure (axis): {feat_count} features (AxisBuilder)")

    return {
        "layerType": "infrastructure",
        "data": geojson,
    }


def _generate_space_control_zone(
    gis_data: Dict[str, Any],
    allocated_geojson: Optional[Dict[str, Any]] = None,
    intent: Any = None,
) -> Optional[Dict[str, Any]]:
    """Generate space_control_zone layer — 4-class construction control (510/520/530/540).

    Uses SpaceControlZoneGenerator to partition the village into:
      510 允许建设区 (permitted construction)
      520 限制建设区 (restricted)
      530 有条件建设区 (conditional, ≤20% current construction)
      540 禁止建设区 (prohibited: basic farmland + ecological redline)
    """
    boundary = gis_data.get("boundary_geojson")
    if not boundary:
        return None

    from app.modules.gis.generation.space_control_generator import SpaceControlZoneGenerator

    generator = SpaceControlZoneGenerator()
    geojson = generator.generate(
        boundary=boundary,
        construction_boundary=gis_data.get("construction_boundary_geojson"),
        planned_landuse=allocated_geojson,
        farmland_protection=gis_data.get("farmland_protection_geojson"),
        ecological_protection=gis_data.get("ecological_protection_geojson"),
        current_landuse=gis_data.get("landuse_current_geojson"),
    )

    feat_count = len(geojson.get("features", []))
    logger.info(f"[generate_layout] space_control_zone: {feat_count} features (SpaceControlZoneGenerator)")

    if feat_count == 0:
        return None

    return {
        "layerType": "space_control_zone",
        "data": geojson,
    }


def _generate_land_use_zone(
    allocated_geojson: Optional[Dict[str, Any]] = None,
    gis_data: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """Generate land_use_zone layer — V/N/E classification (3大类/10中类/15小类).

    Mapping chain: DLBM → GHYTBM → V/N/E code.
    Fallback: DLBM → zone_type → V/N/E heuristic.
    """
    geojson = allocated_geojson
    if not geojson:
        geojson = gis_data.get("landuse_current_geojson") if gis_data else None
    if not geojson or not geojson.get("features"):
        return None

    from app.modules.gis.generation.land_use_zone_generator import LandUseZoneGenerator

    generator = LandUseZoneGenerator()
    result = generator.generate(
        allocated_geojson=allocated_geojson,
        current_landuse=gis_data.get("landuse_current_geojson") if gis_data else None,
    )

    feat_count = len(result.get("features", []))
    logger.info(f"[generate_layout] land_use_zone: {feat_count} features (LandUseZoneGenerator)")

    if feat_count == 0:
        return None

    return {
        "layerType": "land_use_zone",
        "data": result,
    }
