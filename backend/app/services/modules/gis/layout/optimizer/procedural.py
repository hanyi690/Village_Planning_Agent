"""Geometry procedural utilities — merge, split, simplify, buffer.

Shared geometry operations used by zone_generator, engine, and axis_builder.
Eliminates inline GeoPandas/Shapely code duplication.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple

from app.utils.logger import get_logger

logger = get_logger(__name__)


def merge_parcels(
    gdf: "geopandas.GeoDataFrame",
    group_column: str = "assigned_zone",
) -> "geopandas.GeoDataFrame":
    """Merge adjacent parcels with the same group value into single polygons.

    Args:
        gdf: GeoDataFrame with parcel geometries
        group_column: Column to group by (e.g., "assigned_zone", "zone_type")

    Returns:
        GeoDataFrame with one row per group (dissolved geometry)
    """
    if gdf.empty:
        return gdf

    dissolved = gdf.dissolve(by=group_column, as_index=False)
    dissolved["area_ha"] = dissolved.geometry.area / 10000
    dissolved = dissolved[dissolved.geometry.notna() & ~dissolved.geometry.is_empty]

    logger.info(
        f"[procedural] merge_parcels: {len(gdf)} → {len(dissolved)} features "
        f"(grouped by {group_column})"
    )
    return dissolved


def split_by_area(
    polygon: "shapely.geometry.Polygon",
    target_area_ha: float,
    crs: str = "EPSG:3857",
) -> List["shapely.geometry.Polygon"]:
    """Split a large polygon into sub-polygons by target area.

    Uses a simple grid-based approach: divide the bounding box into
    a grid and intersect with the original polygon.

    Args:
        polygon: Polygon to split
        target_area_ha: Target area per sub-polygon (hectares)
        crs: CRS for area calculation (must be metric, e.g., EPSG:3857)

    Returns:
        List of sub-polygons
    """
    area_ha = polygon.area / 10000
    if area_ha <= target_area_ha:
        return [polygon]

    n_parts = max(2, int(area_ha / target_area_ha))
    minx, miny, maxx, maxy = polygon.bounds

    # Square grid approximation
    n_cols = int(n_parts ** 0.5) + 1
    n_rows = (n_parts + n_cols - 1) // n_cols

    dx = (maxx - minx) / n_cols
    dy = (maxy - miny) / n_rows

    from shapely.geometry import box

    parts = []
    for i in range(n_cols):
        for j in range(n_rows):
            cell = box(
                minx + i * dx, miny + j * dy,
                minx + (i + 1) * dx, miny + (j + 1) * dy,
            )
            intersection = polygon.intersection(cell)
            if not intersection.is_empty and intersection.area > 0:
                parts.append(intersection)

    logger.info(
        f"[procedural] split_by_area: {area_ha:.1f}ha → {len(parts)} parts "
        f"(target={target_area_ha:.1f}ha)"
    )
    return parts


def simplify_boundary(
    geojson: Dict[str, Any],
    tolerance_m: float = 50.0,
) -> Dict[str, Any]:
    """Simplify polygon boundaries for cleaner rendering.

    Args:
        geojson: FeatureCollection with polygon features
        tolerance_m: Simplification tolerance in meters (EPSG:3857 units)

    Returns:
        Simplified FeatureCollection
    """
    try:
        import geopandas as gpd
        from shapely import from_geojson
    except ImportError:
        return geojson

    features = geojson.get("features", [])
    if not features:
        return geojson

    simplified_features = []
    for ft in features:
        g = ft.get("geometry", {})
        if not g or not g.get("coordinates"):
            simplified_features.append(ft)
            continue

        try:
            geom = from_geojson(json.dumps(g))
            if geom.is_empty:
                simplified_features.append(ft)
                continue

            # Simplify in metric CRS
            gdf = gpd.GeoSeries([geom], crs="EPSG:4326").to_crs("EPSG:3857")
            simplified = gdf.simplify(tolerance_m, preserve_topology=True).to_crs("EPSG:4326")[0]

            new_ft = dict(ft)
            new_ft["geometry"] = json.loads(json.dumps(simplified.__geo_interface__))
            simplified_features.append(new_ft)
        except Exception:
            simplified_features.append(ft)

    return {"type": "FeatureCollection", "features": simplified_features}


def buffer_zone(
    geojson: Dict[str, Any],
    distance_m: float = 100.0,
) -> Dict[str, Any]:
    """Create buffer zone around features.

    Args:
        geojson: FeatureCollection to buffer
        distance_m: Buffer distance in meters

    Returns:
        Buffered FeatureCollection
    """
    try:
        import geopandas as gpd
        from shapely import from_geojson
    except ImportError:
        return geojson

    features = geojson.get("features", [])
    if not features:
        return geojson

    buffered_features = []
    for ft in features:
        g = ft.get("geometry", {})
        if not g or not g.get("coordinates"):
            continue

        try:
            geom = from_geojson(json.dumps(g))
            if geom.is_empty:
                continue

            gdf = gpd.GeoSeries([geom], crs="EPSG:4326").to_crs("EPSG:3857")
            buffered = gdf.buffer(distance_m).to_crs("EPSG:4326")[0]

            new_ft = dict(ft)
            new_ft["geometry"] = json.loads(json.dumps(buffered.__geo_interface__))
            buffered_features.append(new_ft)
        except Exception:
            continue

    return {"type": "FeatureCollection", "features": buffered_features}


def geojson_to_geodataframe(geojson: Dict[str, Any]) -> Optional["geopandas.GeoDataFrame"]:
    """Convert GeoJSON FeatureCollection to GeoDataFrame.

    Args:
        geojson: FeatureCollection dict

    Returns:
        GeoDataFrame or None if conversion fails
    """
    try:
        import geopandas as gpd
        from shapely import from_geojson
    except ImportError:
        return None

    features = geojson.get("features", [])
    if not features:
        return None

    geoms = []
    props = []
    for ft in features:
        g = ft.get("geometry", {})
        if g and g.get("coordinates"):
            try:
                geom = from_geojson(json.dumps(g))
                if not geom.is_empty:
                    geoms.append(geom)
                    props.append(ft.get("properties", {}))
            except Exception:
                continue

    if not geoms:
        return None

    return gpd.GeoDataFrame(props, geometry=geoms, crs="EPSG:4326")


def geodataframe_to_geojson(gdf: "geopandas.GeoDataFrame") -> Dict[str, Any]:
    """Convert GeoDataFrame to GeoJSON FeatureCollection.

    Args:
        gdf: GeoDataFrame

    Returns:
        FeatureCollection dict
    """
    features = []
    for _, row in gdf.iterrows():
        geom = row.geometry
        if geom is None or geom.is_empty:
            continue

        props = {k: v for k, v in row.items() if k != gdf.geometry.name}
        # Convert non-serializable types
        for k, v in props.items():
            if not isinstance(v, (str, int, float, bool, list, dict, type(None))):
                props[k] = str(v)

        features.append({
            "type": "Feature",
            "properties": props,
            "geometry": json.loads(json.dumps(geom.__geo_interface__)),
        })

    return {"type": "FeatureCollection", "features": features}
