"""Parcel geometry operations — split, merge, modify, reclassify, create.

All geometry operations are stateless functions operating on typed features.
This is the only module where Shapely geometry mutations happen.

Design: 02_EXECUTION_PLAN.md Module D
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from .crs_engine import project_to_metric, project_to_wgs84

logger = logging.getLogger(__name__)


# ── Helper: attribute access for both objects and dicts ──


def _get_attr(obj: Any, key: str, default: Any = "") -> Any:
    """Get attribute from either typed object or dict."""
    if hasattr(obj, key):
        return getattr(obj, key, default)
    if isinstance(obj, dict):
        return obj.get(key, default)
    return default


# ── Reclassify (attribute change, geometry unchanged) ──


def reclassify_parcel(
    parcel: Any,
    new_land_use_code: str,
    new_land_use_name: str = "",
) -> Dict[str, Any]:
    """Reclassify a parcel by changing its land use code.

    Geometry unchanged — this is the most common planning operation
    (human planners use 'field calculator' for this).

    Args:
        parcel: CurrentLandUseParcel or dict with bsm/geometry/dlbm/area_ha
        new_land_use_code: New GHYTBM code (e.g. "2121" for 宅基地)
        new_land_use_name: New land use name (optional)

    Returns:
        PlannedParcel-compatible dict with derived_from_bsms populated
    """
    bsm = _get_attr(parcel, "bsm", "")
    geometry = _get_attr(parcel, "geometry", {})
    area_sqm = float(_get_attr(parcel, "area_sqm", 0) or _get_attr(parcel, "area_ha", 0) * 10000 or _get_attr(parcel, "area", 0) or 0)
    area_ha = area_sqm / 10000

    import json
    geom_str = json.dumps(geometry, ensure_ascii=False) if isinstance(geometry, dict) else str(geometry)

    return {
        "bsm": bsm,
        "planning_land_use": new_land_use_code,
        "zone_type": new_land_use_name,
        "area_ha": float(area_ha),
        "geometry": geom_str,
        "derived_from_bsms": [bsm],
        "derived_from_zone_target": "",
        "operation": "reclassify",
    }


# ── Modify (attribute change, geometry unchanged) ──


def modify_parcel(
    parcel: Any,
    field_changes: Dict[str, Any],
) -> Dict[str, Any]:
    bsm = _get_attr(parcel, "bsm", "")
    geometry = _get_attr(parcel, "geometry", {})
    area_sqm = float(_get_attr(parcel, "area_sqm", 0) or _get_attr(parcel, "area_ha", 0) * 10000 or _get_attr(parcel, "area", 0) or 0)
    area_ha = field_changes.get("area_ha", 0) or (area_sqm / 10000)

    import json
    geom_str = json.dumps(geometry, ensure_ascii=False) if isinstance(geometry, dict) else str(geometry)

    result = {
        "bsm": bsm,
        "area_ha": float(area_ha),
        "geometry": geom_str,
        "derived_from_bsms": [bsm],
        "derived_from_zone_target": "",
        "operation": "modify",
    }
    result.update(field_changes)
    return result


# ── Merge (geometry union) ──


def merge_parcels(
    parcels: List[Any],
    new_land_use_code: str = "",
    new_bsm: str = "",
) -> Optional[Dict[str, Any]]:
    """Merge multiple parcels into one by geometry union.

    Args:
        parcels: List of parcels (CurrentLandUseParcel or dict with geometry)
        new_land_use_code: New land use code for the merged parcel (optional)
        new_bsm: New BSM for the merged parcel (auto-generated if empty)

    Returns:
        PlannedParcel-compatible dict, or None if merge fails
    """
    if len(parcels) < 2:
        logger.warning("merge_parcels: need at least 2 parcels, got %d", len(parcels))
        return None

    try:
        from shapely.geometry import shape
        import geopandas as gpd

        geoms = []
        derived_bsms = []
        total_area = 0.0

        for p in parcels:
            geom = _get_attr(p, "geometry", None)
            bsm = _get_attr(p, "bsm", "")
            area_sqm = float(_get_attr(p, "area_sqm", 0) or _get_attr(p, "area_ha", 0) * 10000 or _get_attr(p, "area", 0) or 0)
            area = area_sqm / 10000

            if isinstance(geom, dict):
                shp = shape(geom)
            else:
                continue

            geoms.append(shp)
            derived_bsms.append(bsm)
            total_area += float(area)

        if len(geoms) < 2:
            return None

        from shapely.ops import unary_union
        merged = unary_union(geoms)

        if merged.is_empty:
            logger.warning("merge_parcels: union produced empty geometry")
            return None

        # Fix invalid
        if not merged.is_valid:
            merged = merged.buffer(0)

        import json
        merged_geom = json.loads(json.dumps(merged.__geo_interface__))

        merged_bsm = new_bsm or f"MERGED_{'_'.join(derived_bsms[:3])}"

        logger.info(
            "merge_parcels: %d parcels → 1 (bsm=%s, area=%.1fha)",
            len(parcels), merged_bsm, total_area,
        )

        return {
            "bsm": merged_bsm,
            "planning_land_use": new_land_use_code,
            "area_ha": total_area,
            "geometry": json.dumps(merged_geom, ensure_ascii=False),
            "derived_from_bsms": derived_bsms,
            "derived_from_zone_target": "",
            "operation": "merge",
        }

    except ImportError as e:
        logger.error("merge_parcels: missing dependency (%s)", e)
        return None
    except Exception as e:
        logger.error("merge_parcels failed: %s", e)
        return None


# ── Split (geometry division) ──


def split_parcel_by_geometry(
    parcel: Any,
    split_geometry: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Split a parcel using a provided split geometry (line or polygon).

    Args:
        parcel: Parcel with geometry
        split_geometry: GeoJSON geometry dict for the split boundary

    Returns:
        List of PlannedParcel-compatible dicts
    """
    try:
        from shapely.geometry import shape
        from shapely.ops import split as shapely_split

        geom = _get_attr(parcel, "geometry", None)
        bsm = _get_attr(parcel, "bsm", "")

        if isinstance(geom, dict):
            polygon = shape(geom)
        else:
            return []

        splitter = shape(split_geometry)
        result = shapely_split(polygon, splitter)

        parts = []
        if hasattr(result, "geoms"):
            for i, part in enumerate(result.geoms):
                if part.is_empty or part.area <= 0:
                    continue
                if not part.is_valid:
                    part = part.buffer(0)

                import json
                part_geom = json.loads(json.dumps(part.__geo_interface__))
                part_area = part.area / 10000

                parts.append({
                    "bsm": f"{bsm}_split_{i}",
                    "area_ha": round(part_area, 4),
                    "geometry": json.dumps(part_geom, ensure_ascii=False),
                    "derived_from_bsms": [bsm],
                    "derived_from_zone_target": "",
                    "operation": "split",
                })

        logger.info("split_parcel_by_geometry: %s → %d parts", bsm, len(parts))
        return parts

    except ImportError:
        return []
    except Exception as e:
        logger.error("split_parcel_by_geometry failed: %s", e)
        return []


# ── Create (new geometry from scratch) ──


def create_parcel(
    geometry: Dict[str, Any],
    bsm: str,
    land_use_code: str = "",
    area_ha: float = 0.0,
) -> Dict[str, Any]:
    """Create a new parcel from scratch (new geometry, no derived_from).

    Args:
        geometry: GeoJSON geometry dict
        bsm: New BSM identifier
        land_use_code: GHYTBM code
        area_ha: Area in hectares (computed from geometry if 0)

    Returns:
        PlannedParcel-compatible dict
    """
    import json

    if area_ha <= 0:
        try:
            from shapely.geometry import shape
            shp = shape(geometry)
            area_ha = shp.area / 10000
        except Exception:
            pass

    return {
        "bsm": bsm,
        "planning_land_use": land_use_code,
        "area_ha": round(area_ha, 4),
        "geometry": json.dumps(geometry, ensure_ascii=False),
        "derived_from_bsms": [],
        "derived_from_zone_target": "",
        "operation": "create",
    }


# ── Batch operation: apply operations to bundle ──


def apply_operations(
    operations: List[Dict[str, Any]],
    current_parcels: List[Any],
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Apply a list of operations to current parcels, producing planned parcels.

    This is the main entry point for EXECUTE's operation pipeline.
    Replaces the old _apply_operations (attribute-level fake operations).

    Args:
        operations: List of operation dicts with 'operation' key
                   (produced by reclassify_parcel, merge_parcels, etc.)
        current_parcels: List of CurrentLandUseParcel for reference

    Returns:
        (planned_parcels, warnings) where warnings explain any issues
    """
    planned = list(operations)  # Operations already produce planned-format dicts
    warnings: List[str] = []

    # For parcels not modified, keep as-is (reclassify to same code)
    modified_bsms = {p.get("bsm", "") for p in planned if p.get("bsm")}
    current_map = {}
    for p in current_parcels:
        bsm = _get_attr(p, "bsm", "")
        if bsm:
            current_map[bsm] = p

    for bsm, cp in current_map.items():
        if bsm not in modified_bsms:
            dlbm = _get_attr(cp, "dlbm", "")
            if not dlbm:
                warnings.append(f"parcel {bsm}: preserved without classification because source DLBM is missing")
                continue
            planned.append(reclassify_parcel(cp, dlbm))
            warnings.append(f"parcel {bsm}: kept current land use (unchanged)")

    logger.info(
        "apply_operations: %d operations + %d unchanged = %d planned parcels",
        len(operations), len(current_map) - len(modified_bsms), len(planned),
    )
    return planned, warnings


__all__ = [
    "reclassify_parcel",
    "modify_parcel",
    "merge_parcels",
    "split_parcel_by_geometry",
    "create_parcel",
    "apply_operations",
]
