"""Road planner — planned road network generation from intent + existing roads.

Consumes:
  - RoadTarget (from PARSE SpatialPlanningIntent)
  - CurrentRoad list (from bundle.lines.roads_current)
  - Allocated parcel geometry (for routing around planned zones)

Produces:
  - PlannedRoadEntry list (for KG L4)
  - Planned road GeoJSON layer (for export/render)

Design: 02_EXECUTION_PLAN.md Module E
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from app.utils.crs_engine import project_to_metric, project_to_wgs84

logger = logging.getLogger(__name__)


def plan_roads(
    road_targets: List[Any],
    current_roads: List[Any],
    parcel_geometries: Optional[List[Any]] = None,
) -> List[Dict[str, Any]]:
    """Generate planned road network from PARSE road targets.

    Strategy:
      1. Preserve existing roads that don't conflict with planned zones
      2. For new roads: find shortest path between anchors, avoiding constraints
      3. For road upgrades: modify existing road attributes (width, level)

    Args:
        road_targets: List of RoadTarget or dict with road_level/width_m/connects
        current_roads: List of CurrentRoad or dict with geometry/bsm/road_level
        parcel_geometries: Optional list of allocated parcel geometries for routing

    Returns:
        List of PlannedRoad-compatible dicts
    """
    planned_roads = []

    # Track existing roads by BSM to avoid duplicates
    existing_bsms = set()
    for r in current_roads:
        bsm = getattr(r, "bsm", None) or r.get("bsm", "")  # getattr intentional: r may be dict or typed
        if bsm:
            existing_bsms.add(bsm)

    for rt in road_targets:
        road_level = _get_attr(rt, "road_level", "村道")
        width_m = _get_attr(rt, "width_m", 0.0)
        connects = _get_attr(rt, "connects", [])
        start_anchor = _get_attr(rt, "start_anchor", None)
        end_anchor = _get_attr(rt, "end_anchor", None)
        name = _get_attr(rt, "name", f"规划道路_{road_level}")

        # Try to find an existing road that matches
        matched = _find_matching_road(current_roads, start_anchor, end_anchor, road_level)

        if matched:
            # Upgrade existing road
            bsm = _get_attr(matched, "bsm", "") or _get_attr(matched, "name", f"road_{len(planned_roads)}")
            planned_roads.append({
                "name": name,
                "road_level": road_level,
                "width_m": float(width_m),
                "bsm": bsm,
                "geometry": _get_geometry(matched),
                "derived_from_target": "",
                "operation": "upgrade",
            })
            existing_bsms.discard(bsm)
        elif start_anchor and end_anchor:
            # Generate new road between anchors
            road_geom = _generate_road_geometry(
                start_anchor, end_anchor, parcel_geometries,
            )
            bsm = f"planned_road_{len(planned_roads)}"
            planned_roads.append({
                "name": name,
                "road_level": road_level,
                "width_m": float(width_m),
                "bsm": bsm,
                "geometry": road_geom,
                "derived_from_target": "",
                "operation": "create",
            })
        else:
            # No spatial anchor — log as warning
            logger.warning(
                "road_planner: RoadTarget '%s' has no anchors, skipping",
                getattr(rt, "name", "") or getattr(rt, "road_level", "unknown"),
            )

    # Preserve existing roads as-is (if not explicitly replaced)
    for bsm in existing_bsms:
        for r in current_roads:
            r_bsm = _get_attr(r, "bsm", "") or _get_attr(r, "name", "")
            if r_bsm == bsm:
                planned_roads.append({
                    "name": _get_attr(r, "name", f"road_{bsm}"),
                    "road_level": _get_attr(r, "road_level", "村道"),
                    "width_m": float(_get_attr(r, "width_m", 3.0)),
                    "bsm": bsm,
                    "geometry": _get_geometry(r),
                    "derived_from_target": "",
                    "operation": "preserve",
                })
                break

    logger.info(
        "road_planner: %d targets + %d preserved = %d planned roads",
        len(road_targets), len(existing_bsms), len(planned_roads),
    )
    return planned_roads


def _get_attr(obj: Any, key: str, default: Any = "") -> Any:
    """Get attribute from either object or dict."""
    if hasattr(obj, key):
        return getattr(obj, key, default)
    if isinstance(obj, dict):
        return obj.get(key, default)
    return default


def _get_geometry(obj: Any) -> str:
    """Get geometry as WKT/JSON string from any entity."""
    geom = _get_attr(obj, "geometry", None)
    if geom is None:
        return ""

    import json
    if isinstance(geom, dict):
        return json.dumps(geom, ensure_ascii=False)
    if isinstance(geom, str):
        return geom
    return str(geom)


def _find_matching_road(
    current_roads: List[Any],
    start_anchor: Optional[Tuple[float, float]],
    end_anchor: Optional[Tuple[float, float]],
    road_level: str,
) -> Optional[Any]:
    """Find existing road that matches the target anchors and level.

    Simple heuristic: if anchors are provided, find the road whose
    geometry endpoints are closest to the anchors.
    """
    if not start_anchor or not end_anchor:
        return None

    best_match = None
    best_distance = float("inf")

    for r in current_roads:
        r_level = _get_attr(r, "road_level", "")
        if r_level and r_level != road_level:
            continue

        geom = _get_attr(r, "geometry", None)
        if not geom or isinstance(geom, str):
            continue

        try:
            from shapely.geometry import shape
            shp = shape(geom)
            if shp.is_empty:
                continue

            coords = list(shp.coords)
            if not coords:
                continue

            r_start = coords[0]
            r_end = coords[-1]

            d1 = (r_start[0] - start_anchor[0]) ** 2 + (r_start[1] - start_anchor[1]) ** 2
            d2 = (r_end[0] - end_anchor[0]) ** 2 + (r_end[1] - end_anchor[1]) ** 2
            total_d = d1 + d2

            if total_d < best_distance:
                best_distance = total_d
                best_match = r
        except Exception:
            continue

    return best_match if best_distance < 0.01 else None


def _generate_road_geometry(
    start_anchor: Tuple[float, float],
    end_anchor: Tuple[float, float],
    parcel_geometries: Optional[List[Any]] = None,
) -> str:
    """Generate a simple road geometry (straight line) between two anchors.

    Future enhancement: use shortest-path routing through parcel geometries
    to avoid obstacles and follow terrain.

    Args:
        start_anchor: (lon, lat) start point
        end_anchor: (lon, lat) end point
        parcel_geometries: Optional list of parcel geometries for routing

    Returns:
        GeoJSON geometry string (LineString)
    """
    import json

    line = {
        "type": "LineString",
        "coordinates": [
            [start_anchor[0], start_anchor[1]],
            [end_anchor[0], end_anchor[1]],
        ],
    }
    return json.dumps(line, ensure_ascii=False)


__all__ = ["plan_roads"]