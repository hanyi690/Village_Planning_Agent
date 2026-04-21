"""
Spatial Layout Generator

Core algorithm for generating spatial planning layouts from structured JSON.
Implements road-based boundary splitting and zone allocation.

Reference: GIS Planning Visualization Architecture Refactoring Plan
"""

import math
import json
from typing import Dict, Any, List, Optional, Tuple, TYPE_CHECKING
from ...utils.logger import get_logger

logger = get_logger(__name__)

# Type checking imports
if TYPE_CHECKING:
    import geopandas as gpd

# Check geopandas availability
try:
    import geopandas as _gpd
    import shapely.geometry as geom
    from shapely.ops import split, nearest_points, unary_union
    GEOPANDAS_AVAILABLE = True
    gpd = _gpd
except ImportError:
    GEOPANDAS_AVAILABLE = False
    logger.warning("[spatial_layout_generator] geopandas/shapely not available")
    gpd = None

from .spatial_analysis import geojson_to_geodataframe, geodataframe_to_geojson, _get_geometry_coords
from .accessibility_core import haversine_distance
from .planning_schema import (
    VillagePlanningScheme,
    PlanningZone,
    FacilityPoint,
    DevelopmentAxis,
    get_zone_color,
    get_zone_code,
    get_facility_color,
)


# ==========================================
# Constants
# ==========================================

METERS_PER_DEGREE_LAT = 111000  # Approximately
DEFAULT_GRID_SIZE_M = 100  # Default grid cell size for fallback


# ==========================================
# Main Entry Function
# ==========================================

def generate_spatial_layout_from_json(
    village_boundary: Optional[Dict[str, Any]],
    road_network: Optional[Dict[str, Any]],
    planning_scheme: VillagePlanningScheme,
    **kwargs
) -> Dict[str, Any]:
    """
    Generate spatial layout GeoJSON from structured planning scheme.

    Algorithm flow:
    1. Data preparation - convert GeoJSON to GeoDataFrame
    2. Road-based boundary splitting
    3. Calculate parcel areas
    4. Allocate land use types by area_ratio and location_bias
    5. Merge adjacent same-type parcels
    6. Generate facility points
    7. Output GeoJSON

    Args:
        village_boundary: Village boundary GeoJSON FeatureCollection
        road_network: Road network GeoJSON FeatureCollection
        planning_scheme: Structured planning scheme (VillagePlanningScheme)
        **kwargs: Additional parameters
            - fallback_grid: Use grid splitting if roads insufficient (default: True)
            - merge_threshold: Minimum area for merging (default: 0.01 km2)

    Returns:
        Dict with success status and generated GeoJSON
    """
    if not GEOPANDAS_AVAILABLE:
        return {
            "success": False,
            "error": "Spatial layout generation requires geopandas. Install: pip install geopandas shapely"
        }

    try:
        # Step 1: Data preparation
        boundary_gdf = _prepare_boundary_gdf(village_boundary)
        road_gdf = _prepare_road_gdf(road_network)

        if boundary_gdf is None or len(boundary_gdf) == 0:
            return {"success": False, "error": "No valid boundary data"}

        # Get boundary geometry and center
        boundary_geom = boundary_gdf.union_all()
        center = (boundary_geom.centroid.x, boundary_geom.centroid.y)
        total_area_km2 = _calculate_area_km2(boundary_geom)

        # Step 2: Split boundary by roads or grid
        parcels = _split_boundary_by_roads(
            boundary_geom,
            road_gdf,
            fallback_grid=kwargs.get("fallback_grid", True)
        )

        if not parcels:
            return {"success": False, "error": "Failed to generate parcels from boundary"}

        # Step 3: Calculate parcel areas and classify by location
        parcel_data = _classify_parcels(parcels, center)

        # Step 4: Allocate land use types
        allocated_parcels = _allocate_zones(
            parcel_data,
            planning_scheme.zones,
            total_area_km2
        )

        # Step 5: Merge adjacent same-type parcels
        merge_threshold = kwargs.get("merge_threshold", 0.01)
        merged_zones = _merge_adjacent_same_type(allocated_parcels, merge_threshold)

        # Step 6: Generate facility points
        facilities_gdf = _generate_facility_points(
            planning_scheme.facilities,
            center,
            merged_zones,
            road_gdf
        )

        # Step 7: Generate development axes
        axes_gdf = _generate_development_axes(
            planning_scheme.axes,
            center,
            boundary_geom,
            road_gdf
        )

        # Build final GeoJSON
        zones_geojson = _build_zones_geojson(merged_zones)
        facilities_geojson = _build_facilities_geojson(facilities_gdf)
        axes_geojson = _build_axes_geojson(axes_gdf)

        # Combine all layers
        all_features = []
        all_features.extend(zones_geojson.get("features", []))
        all_features.extend(facilities_geojson.get("features", []))
        all_features.extend(axes_geojson.get("features", []))

        result_geojson = {
            "type": "FeatureCollection",
            "features": all_features
        }

        return {
            "success": True,
            "data": {
                "geojson": result_geojson,
                "zones_geojson": zones_geojson,
                "facilities_geojson": facilities_geojson,
                "axes_geojson": axes_geojson,
                "statistics": {
                    "zone_count": len(merged_zones),
                    "facility_count": len(facilities_gdf) if facilities_gdf else 0,
                    "axis_count": len(axes_gdf) if axes_gdf else 0,
                    "total_area_km2": round(total_area_km2, 4),
                },
                "center": center,
            }
        }

    except Exception as e:
        logger.error(f"[spatial_layout_generator] Generation failed: {e}")
        return {"success": False, "error": f"Spatial layout generation failed: {str(e)}"}


# ==========================================
# Data Preparation Functions
# ==========================================

def _prepare_boundary_gdf(boundary_geojson: Optional[Dict[str, Any]]) -> Optional["gpd.GeoDataFrame"]:
    """Prepare boundary GeoDataFrame"""
    if boundary_geojson is None:
        return None

    gdf = geojson_to_geodataframe(boundary_geojson)
    if gdf is None or len(gdf) == 0:
        return None

    # Ensure single CRS
    if gdf.crs is None:
        gdf.set_crs("EPSG:4326", inplace=True)

    return gdf


def _prepare_road_gdf(road_geojson: Optional[Dict[str, Any]]) -> Optional["gpd.GeoDataFrame"]:
    """Prepare road network GeoDataFrame"""
    if road_geojson is None:
        return None

    gdf = geojson_to_geodataframe(road_geojson)
    if gdf is None or len(gdf) == 0:
        return None

    if gdf.crs is None:
        gdf.set_crs("EPSG:4326", inplace=True)

    # Filter to LineString geometries only
    gdf = gdf[gdf.geometry.type == "LineString"]

    # Sort by importance (if RTEG attribute exists)
    if "RTEG" in gdf.columns:
        # RTEG: 1=major road, 2=secondary, 3=local
        gdf = gdf.sort_values("RTEG", ascending=True)

    return gdf


# ==========================================
# Boundary Splitting Functions
# ==========================================

def _split_boundary_by_roads(
    boundary_geom,
    road_gdf: Optional["gpd.GeoDataFrame"],
    fallback_grid: bool = True
) -> List[Any]:
    """
    Split boundary polygon by road network.

    Uses shapely.ops.split to cut boundary by road lines.
    If roads are insufficient, falls back to grid-based splitting.

    Args:
        boundary_geom: Boundary polygon geometry
        road_gdf: Road network GeoDataFrame
        fallback_grid: Whether to use grid splitting if roads insufficient

    Returns:
        List of parcel polygons
    """
    parcels = []

    # Try road-based splitting first
    if road_gdf is not None and len(road_gdf) > 0:
        try:
            # Get road lines within boundary
            road_lines = []
            for road_geom in road_gdf.geometry:
                if road_geom is not None and boundary_geom.intersects(road_geom):
                    # Clip road to boundary extent
                    clipped = road_geom.intersection(boundary_geom)
                    if clipped is not None and not clipped.is_empty:
                        road_lines.append(clipped)

            if road_lines:
                # Merge all road lines
                merged_roads = unary_union(road_lines)

                # Split boundary by roads
                split_result = split(boundary_geom, merged_roads)

                parcels = [geom for geom in split_result.geoms
                          if geom.is_valid and geom.area > 0]

                logger.debug(f"[split_boundary] Road splitting generated {len(parcels)} parcels")

        except Exception as e:
            logger.warning(f"[split_boundary] Road splitting failed: {e}")

    # Fallback: grid-based splitting
    if (not parcels or len(parcels) < 3) and fallback_grid:
        logger.info("[split_boundary] Using grid-based fallback splitting")
        parcels = _grid_split_boundary(boundary_geom)

    return parcels


def _grid_split_boundary(boundary_geom, grid_size_m: float = DEFAULT_GRID_SIZE_M) -> List[Any]:
    """
    Split boundary using regular grid pattern.

    Creates a grid of squares and intersects with boundary.

    Args:
        boundary_geom: Boundary polygon
        grid_size_m: Grid cell size in meters

    Returns:
        List of grid parcel polygons
    """
    parcels = []

    # Get bounds
    minx, miny, maxx, maxy = boundary_geom.bounds

    # Convert grid size to degrees (approximate)
    center_lat = (miny + maxy) / 2
    meters_per_deg_lon = METERS_PER_DEGREE_LAT / math.cos(math.radians(center_lat))
    grid_deg_x = grid_size_m / meters_per_deg_lon
    grid_deg_y = grid_size_m / METERS_PER_DEGREE_LAT

    # Create grid
    x_steps = int((maxx - minx) / grid_deg_x) + 1
    y_steps = int((maxy - miny) / grid_deg_y) + 1

    for i in range(x_steps):
        for j in range(y_steps):
            # Create grid cell
            cell_minx = minx + i * grid_deg_x
            cell_miny = miny + j * grid_deg_y
            cell_maxx = min(cell_minx + grid_deg_x, maxx)
            cell_maxy = min(cell_miny + grid_deg_y, maxy)

            cell_box = geom.box(cell_minx, cell_miny, cell_maxx, cell_maxy)

            # Intersect with boundary
            intersection = boundary_geom.intersection(cell_box)
            if intersection.is_valid and intersection.area > 0:
                parcels.append(intersection)

    logger.debug(f"[grid_split] Generated {len(parcels)} grid parcels")
    return parcels


# ==========================================
# Parcel Classification Functions
# ==========================================

def _classify_parcels(
    parcels: List[Any],
    center: Tuple[float, float]
) -> List[Dict[str, Any]]:
    """
    Classify parcels by location relative to center.

    Args:
        parcels: List of parcel geometries
        center: Village center (lon, lat)

    Returns:
        List of parcel data dicts with geometry, area, and location class
    """
    # Batch calculate areas for efficiency
    areas = _calculate_areas_batch(parcels)
    total_area = sum(areas)

    classified = []
    for i, parcel in enumerate(parcels):
        area_km2 = areas[i]

        parcel_center = (parcel.centroid.x, parcel.centroid.y)
        direction = _get_direction_from_center(parcel_center, center)

        classified.append({
            "id": f"P{i+1:02d}",
            "geometry": parcel,
            "area_km2": area_km2,
            "center": parcel_center,
            "direction": direction,
            "distance_from_center": _calculate_distance_km(parcel_center, center),
            "area_ratio": area_km2 / total_area if total_area > 0 else 0,
        })

    return classified


def _get_direction_from_center(
    point: Tuple[float, float],
    center: Tuple[float, float]
) -> str:
    """
    Determine direction of point relative to center.

    Args:
        point: Point coordinates (lon, lat)
        center: Center coordinates (lon, lat)

    Returns:
        Direction string: north, south, east, west, northeast, etc.
    """
    dx = point[0] - center[0]  # Longitude difference
    dy = point[1] - center[1]  # Latitude difference

    # Determine quadrant
    if abs(dx) < 0.001 and abs(dy) < 0.001:
        return "center"

    # Use angle to determine direction
    angle = math.degrees(math.atan2(dy, dx))

    # Map angle to direction (east=0, north=90, west=180, south=270)
    if -45 <= angle < 45:
        return "east"
    elif 45 <= angle < 135:
        return "north"
    elif 135 <= angle or angle < -135:
        return "west"
    else:  # -135 <= angle < -45
        return "south"


def _calculate_distance_km(
    point1: Tuple[float, float],
    point2: Tuple[float, float]
) -> float:
    """
    Calculate distance between two points in km.

    Uses haversine_distance from accessibility_core (returns meters),
    converted to km.
    """
    return haversine_distance(point1, point2) / 1000


# ==========================================
# Zone Allocation Functions
# ==========================================

def _allocate_zones(
    parcel_data: List[Dict[str, Any]],
    zones: List[PlanningZone],
    total_area_km2: float
) -> List[Dict[str, Any]]:
    """
    Allocate land use types to parcels based on zone definitions.

    Strategy:
    1. Sort zones by area_ratio (largest first)
    2. For each zone, find parcels matching location_bias
    3. Select parcels until area requirement met
    4. Assign zone type to selected parcels

    Args:
        parcel_data: Classified parcel data
        zones: Planning zone definitions
        total_area_km2: Total boundary area in km2

    Returns:
        List of allocated parcels with zone_type assigned
    """
    # Create copy of parcel data
    allocated = [p.copy() for p in parcel_data]
    available = set(p["id"] for p in allocated)

    # Sort zones by area_ratio (largest first)
    sorted_zones = sorted(zones, key=lambda z: z.area_ratio, reverse=True)

    for zone in sorted_zones:
        target_area_km2 = zone.area_ratio * total_area_km2

        # Filter parcels by location bias
        candidates = _filter_by_location_bias(allocated, zone.location_bias, available)

        # Select parcels to meet area requirement
        selected_ids = _select_parcels_by_area(candidates, target_area_km2)

        # Assign zone type
        for p in allocated:
            if p["id"] in selected_ids:
                p["zone_type"] = zone.land_use
                p["zone_id"] = zone.zone_id
                p["density"] = zone.density
                p["zone_description"] = zone.description
                available.remove(p["id"])

    # Assign remaining parcels as "unallocated"
    for p in allocated:
        if p["id"] in available:
            p["zone_type"] = "agricultural"  # Default unallocated

    return allocated


def _filter_by_location_bias(
    parcels: List[Dict[str, Any]],
    location_bias,
    available_ids: set
) -> List[Dict[str, Any]]:
    """
    Filter parcels by location bias direction.

    Args:
        parcels: Parcel data list
        location_bias: LocationBias model
        available_ids: Set of available parcel IDs

    Returns:
        Filtered list of parcels matching location bias
    """
    direction = location_bias.direction

    candidates = []

    for p in parcels:
        if p["id"] not in available_ids:
            continue

        parcel_dir = p["direction"]

        # Match direction
        if direction == "center":
            # Center parcels are closest to village center
            if p["distance_from_center"] < 0.5:  # Within 500m
                candidates.append(p)
        elif direction == "edge":
            # Edge parcels are furthest from center
            if p["distance_from_center"] > 1.0:  # Beyond 1km
                candidates.append(p)
        else:
            # Directional matching
            if _direction_matches(parcel_dir, direction):
                candidates.append(p)

    # Sort by distance from center (closer = higher priority)
    candidates.sort(key=lambda p: p["distance_from_center"])

    return candidates


def _direction_matches(parcel_dir: str, target_dir: str) -> bool:
    """Check if parcel direction matches target direction"""
    # Exact match
    if parcel_dir == target_dir:
        return True

    # Compound directions (northeast contains north and east)
    compound_mapping = {
        "northeast": ["north", "east"],
        "northwest": ["north", "west"],
        "southeast": ["south", "east"],
        "southwest": ["south", "west"],
    }

    # Check compound
    if target_dir in compound_mapping:
        return parcel_dir in compound_mapping[target_dir]

    # Reverse: parcel is compound, target is basic
    if parcel_dir in compound_mapping:
        return target_dir in compound_mapping[parcel_dir]

    return False


def _select_parcels_by_area(
    candidates: List[Dict[str, Any]],
    target_area_km2: float
) -> set:
    """
    Select parcels to meet target area requirement.

    Greedy selection: take largest parcels first until target met.

    Args:
        candidates: Candidate parcels
        target_area_km2: Target area in km2

    Returns:
        Set of selected parcel IDs
    """
    selected = set()
    current_area = 0

    # Sort by area (largest first)
    sorted_candidates = sorted(candidates, key=lambda p: p["area_km2"], reverse=True)

    for p in sorted_candidates:
        if current_area >= target_area_km2:
            break

        selected.add(p["id"])
        current_area += p["area_km2"]

    return selected


# ==========================================
# Zone Merging Functions
# ==========================================

def _merge_adjacent_same_type(
    allocated_parcels: List[Dict[str, Any]],
    merge_threshold_km2: float
) -> List[Dict[str, Any]]:
    """
    Merge adjacent parcels of the same zone type.

    Uses GeoDataFrame dissolve by zone_type.

    Args:
        allocated_parcels: Allocated parcel data
        merge_threshold_km2: Minimum area for merging

    Returns:
        List of merged zone geometries
    """
    if not allocated_parcels:
        return []

    # Create GeoDataFrame
    geometries = [p["geometry"] for p in allocated_parcels]
    properties = [
        {
            "zone_type": p.get("zone_type", "unknown"),
            "zone_id": p.get("zone_id", ""),
            "density": p.get("density", "medium"),
            "zone_description": p.get("zone_description", ""),
        }
        for p in allocated_parcels
    ]

    merge_gdf = gpd.GeoDataFrame(properties, geometry=geometries, crs="EPSG:4326")

    # Dissolve by zone_type
    dissolved = merge_gdf.dissolve(by="zone_type", as_index=False)

    # Filter by merge threshold
    merged_zones = []
    for idx, row in dissolved.iterrows():
        area_km2 = _calculate_area_km2(row.geometry)
        if area_km2 >= merge_threshold_km2:
            # Handle MultiPolygon - may need to split
            geom_type = row.geometry.geom_type
            if geom_type == "MultiPolygon":
                for i, poly in enumerate(row.geometry.geoms):
                    if poly.is_valid and poly.area > 0:
                        merged_zones.append({
                            "geometry": poly,
                            "zone_type": row.zone_type,
                            "zone_id": f"{row.zone_type[:2]}{i+1:02d}",
                            "area_km2": _calculate_area_km2(poly),
                            "density": row.density,
                        })
            else:
                merged_zones.append({
                    "geometry": row.geometry,
                    "zone_type": row.zone_type,
                    "zone_id": row.zone_id or f"{row.zone_type[:2]}01",
                    "area_km2": area_km2,
                    "density": row.density,
                })

    return merged_zones


# ==========================================
# Facility Generation Functions
# ==========================================

def _generate_facility_points(
    facilities: List[FacilityPoint],
    center: Tuple[float, float],
    merged_zones: List[Dict[str, Any]],
    road_gdf: Optional["gpd.GeoDataFrame"]
) -> Optional["gpd.GeoDataFrame"]:
    """
    Generate facility point geometries.

    Args:
        facilities: Facility definitions
        center: Village center
        merged_zones: Merged zone geometries
        road_gdf: Road network

    Returns:
        GeoDataFrame of facility points
    """
    if not facilities:
        return None

    points = []
    properties = []

    for facility in facilities:
        coords = _resolve_facility_location(
            facility,
            center,
            merged_zones,
            road_gdf
        )

        point_geom = geom.Point(coords)

        points.append(point_geom)
        properties.append({
            "facility_id": facility.facility_id,
            "facility_type": facility.facility_type,
            "status": facility.status,
            "service_radius": facility.service_radius,
            "priority": facility.priority,
            "color": get_facility_color(facility.status),
            "description": facility.description,
        })

    if not points:
        return None

    return gpd.GeoDataFrame(properties, geometry=points, crs="EPSG:4326")


def _resolve_facility_location(
    facility: FacilityPoint,
    center: Tuple[float, float],
    merged_zones: List[Dict[str, Any]],
    road_gdf: Optional["gpd.GeoDataFrame"]
) -> Tuple[float, float]:
    """
    Resolve facility location from hint.

    Args:
        facility: Facility definition
        center: Village center
        merged_zones: Merged zones
        road_gdf: Road network

    Returns:
        Coordinates (lon, lat)
    """
    hint = facility.location_hint.lower()

    # Parse common location hints
    if "中心" in hint or "center" in hint:
        return center

    if "村口" in hint or "entrance" in hint:
        # Village entrance: typically west or south edge
        return (center[0] - 0.005, center[1])

    # Zone-based positioning
    zone_type_mapping = {
        "居住": "residential",
        "产业": "industrial",
        "公共服务": "public_service",
        "学校": "public_service",
        "医院": "public_service",
    }

    for keyword, zone_type in zone_type_mapping.items():
        if keyword in hint:
            # Find matching zone
            for zone in merged_zones:
                if zone.get("zone_type") == zone_type:
                    centroid = zone["geometry"].centroid
                    return (centroid.x, centroid.y)

    # Road-based positioning
    if road_gdf and len(road_gdf) > 0:
        if "路边" in hint or "道路" in hint or "road" in hint:
            # Take first major road midpoint
            first_road = road_gdf.iloc[0].geometry
            coords = list(first_road.coords)
            mid_idx = len(coords) // 2
            road_point = coords[mid_idx]
            # Offset slightly from road
            return (road_point[0], road_point[1])

    # Default: center offset
    return (center[0] + 0.002, center[1] + 0.002)


# ==========================================
# Development Axis Generation Functions
# ==========================================

def _generate_development_axes(
    axes: List[DevelopmentAxis],
    center: Tuple[float, float],
    boundary_geom,
    road_gdf: Optional["gpd.GeoDataFrame"]
) -> Optional["gpd.GeoDataFrame"]:
    """
    Generate development axis geometries.

    Args:
        axes: Axis definitions
        center: Village center
        boundary_geom: Boundary polygon
        road_gdf: Road network

    Returns:
        GeoDataFrame of axis lines
    """
    if not axes:
        return None

    lines = []
    properties = []

    for axis in axes:
        axis_geom = _create_axis_geometry(
            axis,
            center,
            boundary_geom,
            road_gdf
        )

        if axis_geom is not None:
            lines.append(axis_geom)
            properties.append({
                "axis_id": axis.axis_id,
                "axis_type": axis.axis_type,
                "direction": axis.direction,
                "color": "#FF0000" if axis.axis_type == "primary" else "#00AA00",
                "description": axis.description,
            })

    if not lines:
        return None

    return gpd.GeoDataFrame(properties, geometry=lines, crs="EPSG:4326")


def _create_axis_geometry(
    axis: DevelopmentAxis,
    center: Tuple[float, float],
    boundary_geom,
    road_gdf: Optional["gpd.GeoDataFrame"]
) -> Optional[Any]:
    """
    Create axis line geometry.

    Args:
        axis: Axis definition
        center: Village center
        boundary_geom: Boundary polygon
        road_gdf: Road network

    Returns:
        LineString geometry
    """
    # Reference feature-based
    if axis.reference_feature:
        if "河" in axis.reference_feature or "river" in axis.reference_feature:
            # Find river-like features
            pass  # TODO: implement water feature lookup
        if "路" in axis.reference_feature or "road" in axis.reference_feature:
            if road_gdf and len(road_gdf) > 0:
                # Use major road
                first_road = road_gdf.iloc[0].geometry
                return first_road

    # Direction-based
    bounds = boundary_geom.bounds
    minx, miny, maxx, maxy = bounds

    if axis.direction == "east-west":
        # Horizontal axis through center
        return geom.LineString([(minx, center[1]), (maxx, center[1])])
    elif axis.direction == "north-south":
        # Vertical axis through center
        return geom.LineString([(center[0], miny), (center[0], maxy)])
    elif axis.direction == "radial":
        # Create radial pattern (multiple lines)
        return geom.LineString([center, (maxx, maxy)])  # Simplified
    else:
        return None


# ==========================================
# GeoJSON Building Functions
# ==========================================

def _build_zones_geojson(merged_zones: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Build zones GeoJSON FeatureCollection"""
    features = []

    for zone in merged_zones:
        geom_type = zone["geometry"].geom_type
        coords = _get_geometry_coords(zone["geometry"])

        feature = {
            "type": "Feature",
            "properties": {
                "zone_id": zone.get("zone_id", ""),
                "zone_type": zone.get("zone_type", ""),
                "zone_type_cn": zone.get("zone_type", ""),
                "area_km2": round(zone.get("area_km2", 0), 4),
                "density": zone.get("density", "medium"),
                "color": get_zone_color(zone.get("zone_type", "")),
                "zone_code": get_zone_code(zone.get("zone_type", "")),
                "layerType": "function_zone",
                "layerName": "规划用地",
            },
            "geometry": {
                "type": geom_type,
                "coordinates": coords
            }
        }
        features.append(feature)

    return {"type": "FeatureCollection", "features": features}


def _build_facilities_geojson(facilities_gdf: Optional["gpd.GeoDataFrame"]) -> Dict[str, Any]:
    """Build facilities GeoJSON FeatureCollection"""
    if facilities_gdf is None:
        return {"type": "FeatureCollection", "features": []}

    features = []

    for idx, row in facilities_gdf.iterrows():
        feature = {
            "type": "Feature",
            "properties": {
                "facility_id": row.get("facility_id", ""),
                "facility_type": row.get("facility_type", ""),
                "status": row.get("status", "new"),
                "service_radius": row.get("service_radius", 500),
                "priority": row.get("priority", "medium"),
                "color": row.get("color", "#4A90D9"),
                "description": row.get("description", ""),
                "layerType": "facility_point",
                "layerName": "公共设施",
            },
            "geometry": {
                "type": "Point",
                "coordinates": [row.geometry.x, row.geometry.y]
            }
        }
        features.append(feature)

    return {"type": "FeatureCollection", "features": features}


def _build_axes_geojson(axes_gdf: Optional["gpd.GeoDataFrame"]) -> Dict[str, Any]:
    """Build development axes GeoJSON FeatureCollection"""
    if axes_gdf is None:
        return {"type": "FeatureCollection", "features": []}

    features = []

    for idx, row in axes_gdf.iterrows():
        coords = _get_geometry_coords(row.geometry)

        feature = {
            "type": "Feature",
            "properties": {
                "axis_id": row.get("axis_id", ""),
                "axis_type": row.get("axis_type", "primary"),
                "direction": row.get("direction", ""),
                "color": row.get("color", "#FF0000"),
                "description": row.get("description", ""),
                "layerType": "development_axis",
                "layerName": "发展轴线",
            },
            "geometry": {
                "type": "LineString",
                "coordinates": coords
            }
        }
        features.append(feature)

    return {"type": "FeatureCollection", "features": features}


# ==========================================
# Utility Functions
# ==========================================

def _calculate_area_km2(geometry) -> float:
    """Calculate geometry area in km2"""
    try:
        # Project to meters for accurate area
        gdf_temp = gpd.GeoDataFrame([{"geometry": geometry}], crs="EPSG:4326")
        gdf_proj = gdf_temp.to_crs(epsg=3857)
        return gdf_proj.geometry.area.sum() / 1_000_000
    except Exception:
        # Fallback: use shapely area (degrees) and approximate
        return geometry.area * 111 * 111  # Rough km2 estimate


def _calculate_areas_batch(geometries: List[Any]) -> List[float]:
    """
    Calculate areas for multiple geometries efficiently.

    Projects all geometries together to avoid repeated CRS conversion.

    Args:
        geometries: List of shapely geometries

    Returns:
        List of area values in km2
    """
    if not geometries:
        return []

    try:
        # Create single GeoDataFrame with all geometries
        gdf_temp = gpd.GeoDataFrame(
            {"geometry": geometries},
            crs="EPSG:4326"
        )
        # Project once for all geometries
        gdf_proj = gdf_temp.to_crs(epsg=3857)
        # Return areas in km2
        return [area / 1_000_000 for area in gdf_proj.geometry.area.values]
    except Exception:
        # Fallback: approximate calculation
        return [g.area * 111 * 111 for g in geometries]


__all__ = [
    "generate_spatial_layout_from_json",
]