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


from app.tools.helpers import make_result, to_tool_message


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
    operation_sequence: Annotated[Optional[List[Dict[str, Any]]], InjectedState("operation_sequence")] = None,
    kg_session_ref: Annotated[Optional[str], InjectedState("kg_session_ref")] = "",
    kg_three_lines: Annotated[Optional[List[Dict[str, Any]]], InjectedState("kg_three_lines")] = None,
    tool_call_id: Annotated[str, InjectedToolCallId] = "",
) -> Command:
    """Generate multi-layer spatial layout: function zones, planning zones, facilities,
    axes, space control zones (510/520/530/540), and land use zones (V/N/E).

    Delegates to ZoneGenerator (merged zones), FacilityPlacer (4-strategy),
    AxisBuilder (spatial structure), SpaceControlZoneGenerator (4-class),
    and LandUseZoneGenerator (V/N/E classification).
    Step 2: operation_sequence applied to allocated_geojson.
    Intent and GIS data auto-injected.
    """
    t0 = time.time()
    layers: List[Dict[str, Any]] = []

    try:
        # ── Step 2: Apply PARSE operations to allocated_geojson ───────
        if operation_sequence and allocated_geojson:
            allocated_geojson = _apply_operations(allocated_geojson, operation_sequence)

        # ── Function zone layer (ZoneGenerator) ─────────────────────
        func_layer = _generate_function_zones(intent, gis_data)
        if func_layer:
            layers.append(func_layer)

        # ── Planning zone layer (per-parcel DLBM → 4-zone) ─────────
        plan_layer = _make_planning_zone_layer(allocated_geojson, gis_data)
        if plan_layer:
            layers.append(plan_layer)

        # ── Facility layer (FacilityPlacer) ─────────────────────────
        fac_layer = _generate_facilities(intent, gis_data, kg_session_ref=kg_session_ref or "")
        if fac_layer:
            layers.append(fac_layer)

        # ── Axis layer (AxisBuilder) ─────────────────────────────────
        axis_layer = _generate_axes(intent, gis_data)
        if axis_layer:
            layers.append(axis_layer)

        # ── Space Control Zone (510/520/530/540) ──────────────────
        space_ctrl_layer = _generate_space_control_zone(gis_data, allocated_geojson, intent, kg_three_lines)
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
    has_zones = hasattr(intent, 'zone_targets') and intent.zone_targets
    has_zones = has_zones or (isinstance(intent, dict) and intent.get("zones"))
    if not intent or not has_zones:
        return None

    landuse = gis_data.get("landuse_current_geojson") or gis_data.get("allocated_geojson")
    if not landuse or not landuse.get("features"):
        return None

    from ._generation.zone_generator import ZoneGenerator

    boundary = gis_data.get("boundary_geojson")
    protection = _build_protection_zones(gis_data)

    # adapter 产出 properties 键为小写 dlbm，ZoneGenerator 期望大写 DLBM — 归一化
    norm_features = []
    for f in (landuse.get("features") or []):
        props = dict(f.get("properties") or {})
        if "dlbm" in props and "DLBM" not in props:
            props["DLBM"] = props["dlbm"]
        f2 = dict(f)
        f2["properties"] = props
        norm_features.append(f2)
    landuse = {"type": "FeatureCollection", "features": norm_features}

    generator = ZoneGenerator()
    geojson = generator.generate(
        zones=list(intent.zone_targets),
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

    from app.modules.schema import dlbm_to_planning_zone, PLANNING_ZONE_COLORS
    from app.modules.schema.encodings.code_sets import GHYTMC_TO_PLANNING_ZONE

    features = []
    for feat in source["features"]:
        props = dict(feat.get("properties", {}))
        dlbm = str(props.get("DLBM", "") or props.get("dlbm", ""))
        assigned = props.get("assigned_zone", dlbm_to_planning_zone(dlbm))
        # assigned_zone may be a GHYTMC name (e.g. "商品林") — map to planning zone
        if assigned not in PLANNING_ZONE_COLORS:
            pz = GHYTMC_TO_PLANNING_ZONE.get(assigned)
            if pz:
                assigned = pz
        color = PLANNING_ZONE_COLORS.get(assigned, "#CCCCCC")

        features.append({
            "type": "Feature",
            "geometry": feat.get("geometry", {}),
            "properties": {**props, "zone_type": assigned, "color": color, "stroke": color},
        })

    # Merge adjacent same-type parcels via dissolve
    try:
        from ._generation.optimizer.procedural import merge_parcels
        from app.utils.geojson_utils import geojson_to_geodataframe, geodataframe_to_geojson
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
    kg_session_ref: str = "",
) -> Optional[Dict[str, Any]]:
    """Generate facility_point layer via FacilityPlacer (4 strategies + KG)."""
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
                "anchor_point": getattr(ft, 'anchor_point', None),
                "direction": getattr(ft, 'direction', 'center'),
                "service_radius": getattr(ft, 'service_radius', None),
                "candidate_bsms": list(getattr(ft, 'candidate_bsms', None) or []),
            })
    elif isinstance(intent, dict) and intent.get("facilities"):
        facilities_raw = intent["facilities"]
    if not facilities_raw:
        return None

    # Query KG for existing facility locations (precise coordinates from annotations)
    kg_facilities = None
    if kg_session_ref:
        try:
            from app.modules.kg.manager import get_kg_manager
            from app.modules.kg.queries import query_kg
            manager = get_kg_manager()
            kg = manager.get_session_kg(kg_session_ref)
            if kg:
                results = query_kg(kg, "get_facility_locations")
                # Convert SPARQL results to {name, type, lon, lat} format
                kg_facilities = []
                for row in results:
                    try:
                        kg_facilities.append({
                            "name": row.get("name", ""),
                            "type": row.get("type", ""),
                            "lon": float(row.get("lon", 0)),
                            "lat": float(row.get("lat", 0)),
                            "serves": row.get("serves", ""),
                        })
                    except (ValueError, TypeError):
                        continue
                logger.info("[generate_layout] KG facility locations: %d results", len(kg_facilities))
        except Exception as e:
            logger.debug("[generate_layout] KG facility query skipped: %s", e)

    from ._generation.facility_placer import FacilityPlacer

    placer = FacilityPlacer()
    geojson = placer.place(
        facilities=facilities_raw,
        landuse_geojson=gis_data.get("landuse_current_geojson"),
        boundary_geojson=gis_data.get("boundary_geojson"),
        existing_pois=None,
        hazard_points_geojson=gis_data.get("geological_hazard_geojson"),
        kg_facilities=kg_facilities,
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
    has_axes = hasattr(intent, 'development_axes') and intent.development_axes
    has_axes = has_axes or (isinstance(intent, dict) and intent.get("axes"))
    if not intent or not has_axes:
        return None

    from types import SimpleNamespace
    from ._generation.axis_builder import AxisBuilder

    axes_list = list(intent.development_axes) if hasattr(intent, 'development_axes') else list(intent.get("axes", []))
    builder = AxisBuilder()
    geojson = builder.build(
        intent=SimpleNamespace(axes=axes_list, metadata={}),
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
    kg_three_lines: Optional[List[Dict[str, Any]]] = None,
) -> Optional[Dict[str, Any]]:
    """Generate space_control_zone layer — 4-class construction control (510/520/530/540).

    Uses SpaceControlZoneGenerator to partition the village into:
      510 允许建设区 (permitted construction)
      520 限制建设区 (restricted)
      530 有条件建设区 (conditional, ≤20% current construction)
      540 禁止建设区 (prohibited: basic farmland + ecological redline)

    kg_three_lines: optional KG query results [{name, code, color, area_target_ha}].
    When available, validates generated zone areas against KG targets.
    """
    boundary = gis_data.get("boundary_geojson")
    if not boundary:
        return None

    from ._generation.space_control_generator import SpaceControlZoneGenerator

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

    # Phase 5: Validate against KG three-line area targets
    if kg_three_lines and feat_count > 0:
        _validate_space_control_against_kg(geojson, kg_three_lines)

    if feat_count == 0:
        return None

    return {
        "layerType": "space_control_zone",
        "data": geojson,
    }


def _validate_space_control_against_kg(
    geojson: Dict[str, Any],
    kg_three_lines: List[Dict[str, Any]],
) -> None:
    """Log info when space control zone areas deviate from KG three-line targets.

    Phase 6: MIP now enforces three-line area targets as hard constraints,
    so deviations should be 0. This function serves as a verification signal.
    """
    # Sum areas by zone code
    zone_areas: Dict[str, float] = {}
    for feat in geojson.get("features", []):
        props = feat.get("properties", {})
        code = str(props.get("TDKJGZFQDM", props.get("code", "")))
        area = float(props.get("area_ha", 0) or 0)
        if code:
            zone_areas[code] = zone_areas.get(code, 0) + area

    # Map KG three-line names to zone codes
    line_to_code = {
        "永久基本农田": "540",       # farmland protection → prohibited
        "生态保护红线": "540",       # ecological redline → prohibited
        "城镇开发边界": "510",       # construction boundary → permitted
        "村庄建设边界": "510",       # village construction → permitted
    }

    for tl in kg_three_lines:
        name = tl.get("name", "")
        target_ha = tl.get("area_target_ha")
        if not target_ha or not name:
            continue
        try:
            target_ha = float(target_ha)
        except (ValueError, TypeError):
            continue

        code = line_to_code.get(name)
        if code and code in zone_areas:
            actual = zone_areas[code]
            deviation = abs(actual - target_ha) / target_ha if target_ha > 0 else 0
            if deviation > 0.20:
                logger.info(
                    "[generate_layout] KG three-line deviation: %s target=%.1fha actual=%.1fha (%.0f%%)",
                    name, target_ha, actual, deviation * 100,
                )


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

    from ._generation.land_use_zone_generator import LandUseZoneGenerator

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


# ── Step 2: Apply PARSE operations to GeoJSON ──────────────────────────


def _apply_operations(
    allocated_geojson: Dict[str, Any],
    operation_sequence: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Apply SpatialOperation sequence to allocated GeoJSON (Step 2 — intent fidelity).

    Converts PARSE operations into GeoJSON mutations:
      - create: add new parcel feature
      - split: divide parcel by ratio
      - merge: combine parcels
      - modify: update feature properties
      - reclassify: change DLBM + assigned_zone

    Operations with target_parcels or spatial_anchor.candidate_parcels
    are applied directly. Operations without spatial reference are skipped
    (logged in trace).
    """
    from copy import deepcopy

    features = allocated_geojson.get("features", [])
    feature_index = {f.get("properties", {}).get("composite_key", ""): i
                     for i, f in enumerate(features) if f.get("properties")}

    applied = 0
    skipped = 0

    for op in operation_sequence:
        action = op.get("action", "")
        project_name = op.get("project_name", "")

        if action == "create":
            # Create requires spatial reference — use target_parcels or anchor
            target_parcels = op.get("target_parcels", [])
            anchor = op.get("spatial_anchor", {}) or {}
            candidate_parcels = anchor.get("candidate_parcels", []) if isinstance(anchor, dict) else []

            if target_parcels or candidate_parcels:
                # Modify existing parcels (reclassify them to new use)
                parcels_to_modify = target_parcels or candidate_parcels
                code = op.get("land_use_code", "")
                for parcel_key in parcels_to_modify[:1]:  # Apply to first match
                    idx = feature_index.get(parcel_key)
                    if idx is not None and idx < len(features):
                        props = features[idx].setdefault("properties", {})
                        if code:
                            props["DLBM"] = code
                        props["assigned_zone"] = "村庄建设区"
                        applied += 1
            else:
                # No spatial reference — skip
                skipped += 1
                logger.debug("[apply_ops] Skipped create '%s' — no spatial reference", project_name)

        elif action == "split":
            # Split parcel by ratio
            source_bsm = op.get("source_bsm", "")
            ratio = op.get("split_ratio", 0.5) or 0.5
            idx = feature_index.get(source_bsm)
            if idx is not None and idx < len(features):
                original = features[idx]
                new_feat = deepcopy(original)
                orig_area = original.get("properties", {}).get("area_ha", 0) or 0
                original.setdefault("properties", {})["area_ha"] = round(orig_area * ratio, 4)
                new_feat.setdefault("properties", {})["area_ha"] = round(orig_area * (1 - ratio), 4)
                new_feat["properties"]["composite_key"] = f"{source_bsm}_split"
                features.append(new_feat)
                applied += 1
            else:
                skipped += 1

        elif action == "merge":
            # Merge parcels
            source_bsms = op.get("source_bsms", [])
            if len(source_bsms) >= 2:
                indices = [feature_index.get(bsm) for bsm in source_bsms]
                indices = [i for i in indices if i is not None and i < len(features)]
                if indices:
                    # Keep first, mark others for removal
                    merged_area = sum(
                        features[i].get("properties", {}).get("area_ha", 0) or 0
                        for i in indices
                    )
                    features[indices[0]].setdefault("properties", {})["area_ha"] = round(merged_area, 4)
                    # Remove other features (reverse order to preserve indices)
                    for i in sorted(indices[1:], reverse=True):
                        features.pop(i)
                    applied += 1
                else:
                    skipped += 1
            else:
                skipped += 1

        elif action == "modify":
            # Update feature properties
            target_parcels = op.get("target_parcels", [])
            field_changes = op.get("field_changes", {}) or {}
            for parcel_key in target_parcels[:1]:
                idx = feature_index.get(parcel_key)
                if idx is not None and idx < len(features) and field_changes:
                    props = features[idx].setdefault("properties", {})
                    for k, v in field_changes.items():
                        props[k] = v
                    applied += 1

        elif action == "reclassify":
            # Change DLBM + assigned_zone
            target_parcels = op.get("target_parcels", [])
            new_code = op.get("land_use_code", "") or op.get("new_qmdlbm", "")
            for parcel_key in target_parcels[:1]:
                idx = feature_index.get(parcel_key)
                if idx is not None and idx < len(features):
                    props = features[idx].setdefault("properties", {})
                    if new_code:
                        props["DLBM"] = new_code
                    from app.modules.schema import dlbm_to_planning_zone
                    props["assigned_zone"] = dlbm_to_planning_zone(new_code)
                    applied += 1

    if applied or skipped:
        logger.info("[apply_ops] Applied %d operations, skipped %d (no spatial ref)", applied, skipped)

    return {**allocated_geojson, "features": features}
