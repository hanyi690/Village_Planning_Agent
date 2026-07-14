"""generate_layout tool — spatial layout generation via ZoneGenerator + FacilityPlacer + AxisBuilder.

Delegates to real layout components (no fallback):
  - ZoneGenerator: function_zone layer (merged by zone type)
  - FacilityPlacer: facility_point layer (4-strategy placement)
  - AxisBuilder: infrastructure layer (一核一带三区)
  - Planning zone: per-parcel DLBM → 4-zone classification (inline)
"""

from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Optional, Annotated

from langchain_core.tools import tool, InjectedToolCallId
from langchain_core.messages import ToolMessage
from langgraph.prebuilt import InjectedState
from langgraph.types import Command

from app.utils.logger import get_logger

logger = get_logger(__name__)


# ── helpers ────────────────────────────────────────────────────────────

def _make_result(success: bool, data: Any = None, error: str = "") -> Dict[str, Any]:
    payload: Dict[str, Any] = {"success": success}
    if data is not None:
        payload["data"] = data
    if error:
        payload["error"] = error
    return payload


def _to_tool_message(result: Dict[str, Any], tool_call_id: str) -> ToolMessage:
    return ToolMessage(
        content=json.dumps(result, ensure_ascii=False, default=str),
        tool_call_id=tool_call_id,
    )


def _intent_from_dict(d: Dict[str, Any]) -> Any:
    """Convert dict intent to UnifiedSpatialIntent (dataclass instance)."""
    from app.services.modules.gis.planning_intent import (
        Direction, Density, ZoneIntent, FacilityIntent,
        AxisIntent, ConstraintIntent, UnifiedSpatialIntent,
    )

    zones = []
    for z in d.get("zones", []):
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
    for f in d.get("facilities", []):
        facilities.append(FacilityIntent(
            facility_id=f["facility_id"],
            facility_type=f.get("facility_type", ""),
            target_zone=f.get("target_zone", ""),
            location_hint=f.get("location_hint", ""),
            status=f.get("status", "existing"),
        ))

    axes = []
    for a in d.get("axes", []):
        axes.append(AxisIntent(
            axis_id=a["axis_id"],
            axis_type=a.get("axis_type", "primary"),
            direction=Direction(a.get("direction", "center")),
            label=a.get("label", ""),
        ))

    constraints = []
    for c in d.get("constraints", []):
        constraints.append(ConstraintIntent(
            constraint_id=c.get("constraint_id", c.get("id", "")),
            constraint_type=c.get("type", c.get("constraint_type", "")),
            strict=c.get("strict", True),
        ))

    return UnifiedSpatialIntent(
        zones=zones,
        facilities=facilities,
        axes=axes,
        constraints=constraints,
        metadata=d.get("metadata", {}),
    )


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
    intent: Annotated[Optional[Dict[str, Any]], InjectedState("intent")],
    allocated_geojson: Annotated[Optional[Dict[str, Any]], InjectedState("allocated_geojson")],
    gis_data: Annotated[Dict[str, Optional[Dict[str, Any]]], InjectedState("gis_data")],
    village_name: Annotated[str, InjectedState("village_name")],
    kg_constraints: Annotated[Optional[List[Dict[str, Any]]], InjectedState("kg_constraints")] = None,
    tool_call_id: Annotated[str, InjectedToolCallId] = "",
) -> Command:
    """Generate multi-layer spatial layout: function zones, planning zones, facilities, axes.

    Delegates to ZoneGenerator (merged zones), FacilityPlacer (4-strategy),
    and AxisBuilder (spatial structure). Intent and GIS data auto-injected.
    """
    t0 = time.time()
    layers: List[Dict[str, Any]] = []

    try:
        # ── Function zone layer (ZoneGenerator) ─────────────────────
        func_layer = _generate_function_zones(intent, gis_data)
        if func_layer:
            layers.append(func_layer)

        # ── Planning zone layer (per-parcel DLBM → 4-zone) ─────────
        plan_layer = _generate_planning_zones(allocated_geojson, gis_data, intent)
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

        elapsed = round(time.time() - t0, 2)
        return Command(update={
            "layout_configs": layers,
            "messages": [_to_tool_message(_make_result(True, data={
                "layer_count": len(layers),
                "elapsed_s": elapsed,
                "layers": [lyr.get("layerType", "?") for lyr in layers],
            }), tool_call_id)],
        })

    except Exception as e:
        logger.error(f"Layout generation failed: {e}", exc_info=True)
        return Command(update={
            "messages": [_to_tool_message(_make_result(False, error=str(e)), tool_call_id)],
        })


# ── layer generators ───────────────────────────────────────────────────

def _generate_function_zones(
    intent: Optional[Dict[str, Any]],
    gis_data: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """Generate function_zone layer via ZoneGenerator (merged by zone type).

    ZoneGenerator reclassifies landuse_current parcels by DLBM, merges
    same-type parcels, applies area ratios from intent, clips protection
    zones, and runs CA refinement.
    """
    if not intent or not intent.get("zones"):
        return None

    landuse = gis_data.get("landuse_current_geojson") or gis_data.get("allocated_geojson")
    if not landuse or not landuse.get("features"):
        return None

    from app.services.modules.gis.layout.zone_generator import ZoneGenerator

    boundary = gis_data.get("boundary_geojson")
    protection = _build_protection_zones(gis_data)
    unified = _intent_from_dict(intent)

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


def _generate_planning_zones(
    allocated: Optional[Dict[str, Any]],
    gis_data: Dict[str, Any],
    intent: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Generate planning_zone layer — per-parcel DLBM → 4 planning zones."""
    source = allocated or gis_data.get("landuse_current_geojson")
    if not source or not source.get("features"):
        return None

    from app.services.modules.gis.zone_schema import dlbm_to_planning_zone, PLANNING_ZONE_COLORS

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

    logger.info(f"[generate_layout] planning_zone: {len(features)} features (per-parcel)")

    return {
        "layerType": "planning_zone",
        "data": {"type": "FeatureCollection", "features": features},
    }


def _generate_facilities(
    intent: Optional[Dict[str, Any]],
    gis_data: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """Generate facility_point layer via FacilityPlacer (4 strategies).

    FacilityPlacer handles:
      - 现状保留: keep existing POI location
      - 规划新建: place at preferred DLBM parcel centroid + direction offset
      - 规划改扩建: keep location, expand radius
      - 规划迁建: find nearest suitable parcel
    """
    if not intent or not intent.get("facilities"):
        return None

    from app.services.modules.gis.layout.facility_placer import FacilityPlacer

    placer = FacilityPlacer()
    geojson = placer.place(
        facilities=intent["facilities"],
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
    intent: Optional[Dict[str, Any]],
    gis_data: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """Generate infrastructure/axis layer via AxisBuilder.

    AxisBuilder auto-generates 一核一带三区 from landuse parcels
    or uses explicit AxisIntent definitions from LLM parse.
    """
    if not intent or not intent.get("axes"):
        return None

    from app.services.modules.gis.layout.axis_builder import AxisBuilder

    unified = _intent_from_dict(intent)
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
