"""Raster least-cost routing and preliminary engineering checks for Stage 4."""

from __future__ import annotations

import heapq
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np
from scipy.ndimage import distance_transform_edt
from shapely import contains_xy
from shapely.geometry import LineString, Point
from shapely.ops import unary_union


@dataclass
class TerrainContext:
    elevation: np.ndarray
    slope: np.ndarray
    land_cost: np.ndarray
    inside: np.ndarray
    blocked: np.ndarray
    road_mask: np.ndarray
    hazard_distance_m: np.ndarray
    x_min: float
    y_max: float
    cell_size: float
    metric_crs: str
    source_path: Path

    @property
    def shape(self) -> Tuple[int, int]:
        return self.elevation.shape

    def point_to_cell(self, point: Point) -> Tuple[int, int]:
        column = int(round((point.x - self.x_min) / self.cell_size - 0.5))
        row = int(round((self.y_max - point.y) / self.cell_size - 0.5))
        return (
            max(0, min(self.shape[0] - 1, row)),
            max(0, min(self.shape[1] - 1, column)),
        )

    def cell_to_xy(self, row: int, column: int) -> Tuple[float, float]:
        return (
            self.x_min + (column + 0.5) * self.cell_size,
            self.y_max - (row + 0.5) * self.cell_size,
        )


def _grid_coordinates(shape: Tuple[int, int], x_min: float, y_max: float, cell_size: float) -> Tuple[np.ndarray, np.ndarray]:
    rows, columns = shape
    x = x_min + (np.arange(columns, dtype=np.float64) + 0.5) * cell_size
    y = y_max - (np.arange(rows, dtype=np.float64) + 0.5) * cell_size
    return np.meshgrid(x, y)


def _mask_geometry(geometry: Any, xx: np.ndarray, yy: np.ndarray) -> np.ndarray:
    if geometry is None or geometry.is_empty:
        return np.zeros(xx.shape, dtype=bool)
    return np.asarray(contains_xy(geometry, xx, yy), dtype=bool)


def load_terrain_context(
    grid_path: Path,
    *,
    constraints: Mapping[str, Any],
    buildings: Any,
    hazards: Any,
    roads_union: Any,
    max_slope_deg: float,
    existing_road_buffer_m: float,
    hazard_screening_distance_m: float,
    block_buildings: bool = False,
) -> TerrainContext:
    payload = np.load(grid_path, allow_pickle=False)
    elevation = payload["elevation_m"].astype(np.float64)
    slope = payload["slope_deg"].astype(np.float64)
    land_cost = payload["land_cost"].astype(np.float64)
    inside = payload["inside_boundary"].astype(bool)
    x_min = float(payload["x_min"])
    y_max = float(payload["y_max"])
    cell_size = float(payload["cell_size_m"])
    metric_crs = str(payload["metric_crs"])
    xx, yy = _grid_coordinates(elevation.shape, x_min, y_max, cell_size)
    hard_geometry = unary_union(
        [
            geometry
            for target in ("water", "ecological_protection", "farmland_protection", "historical_protection")
            for geometry in [constraints.get(target)]
            if geometry is not None and not geometry.is_empty
        ]
    )
    hard_mask = _mask_geometry(hard_geometry.buffer(cell_size * 0.75), xx, yy)
    building_geometry = (
        buildings.buffer(cell_size * 0.75)
        if block_buildings and buildings is not None and not buildings.is_empty
        else buildings
    )
    building_mask = _mask_geometry(building_geometry, xx, yy)
    road_mask = _mask_geometry(roads_union.buffer(existing_road_buffer_m), xx, yy)
    # Current land-use polygons identify construction parcels, not individual
    # building footprints. They receive a high cost but are not treated as an
    # impenetrable wall until a real building-footprint layer is supplied.
    blocked = (~inside) | (~np.isfinite(elevation)) | (~np.isfinite(slope)) | (slope > max_slope_deg) | hard_mask
    if block_buildings:
        blocked |= building_mask
    # Existing roads are already-built corridors. They stay traversable and are
    # excluded later from net-new impact, even when a planning polygon covers them.
    blocked[road_mask & inside & np.isfinite(elevation)] = False
    hazard_mask = _mask_geometry(hazards, xx, yy)
    if hazard_mask.any():
        hazard_distance = distance_transform_edt(~hazard_mask) * cell_size
    else:
        hazard_distance = np.full(elevation.shape, hazard_screening_distance_m * 10.0)
    return TerrainContext(
        elevation=elevation,
        slope=slope,
        land_cost=land_cost,
        inside=inside,
        blocked=blocked,
        road_mask=road_mask,
        hazard_distance_m=hazard_distance,
        x_min=x_min,
        y_max=y_max,
        cell_size=cell_size,
        metric_crs=metric_crs,
        source_path=grid_path,
    )


def _cost_surface(context: TerrainContext, strategy: str, preferred_slope_deg: float, hazard_distance_m: float) -> np.ndarray:
    slope_ratio = np.maximum(0.0, context.slope) / max(preferred_slope_deg, 1.0)
    slope_cost = slope_ratio * slope_ratio
    land = np.maximum(0.1, context.land_cost)
    hazard = np.maximum(0.0, hazard_distance_m - context.hazard_distance_m) / max(hazard_distance_m, 1.0)
    if strategy == "shortest_distance":
        cost = 1.0 + 0.45 * slope_cost + 0.03 * land + 0.5 * hazard
    elif strategy == "lowest_land_cost":
        cost = 1.0 + 0.75 * slope_cost + 1.4 * land + 1.0 * hazard
    else:
        cost = 1.0 + 1.25 * slope_cost + 0.35 * land + 4.0 * hazard
    cost = np.asarray(cost, dtype=np.float64)
    cost[context.road_mask] *= 0.15
    cost[context.blocked] = np.inf
    return cost


NEIGHBOURS = (
    (-1, 0, 1.0), (1, 0, 1.0), (0, -1, 1.0), (0, 1, 1.0),
    (-1, -1, math.sqrt(2.0)), (-1, 1, math.sqrt(2.0)),
    (1, -1, math.sqrt(2.0)), (1, 1, math.sqrt(2.0)),
)


def _nearest_traversable(
    cost: np.ndarray, cell: Tuple[int, int], max_radius: int = 8
) -> Optional[Tuple[int, int]]:
    row, column = cell
    if math.isfinite(float(cost[row, column])):
        return cell
    rows, columns = cost.shape
    for radius in range(1, max_radius + 1):
        candidates: List[Tuple[float, int, int]] = []
        for candidate_row in range(max(0, row - radius), min(rows, row + radius + 1)):
            for candidate_column in range(max(0, column - radius), min(columns, column + radius + 1)):
                if max(abs(candidate_row - row), abs(candidate_column - column)) != radius:
                    continue
                if math.isfinite(float(cost[candidate_row, candidate_column])):
                    candidates.append(
                        (
                            math.hypot(candidate_row - row, candidate_column - column),
                            candidate_row,
                            candidate_column,
                        )
                    )
        if candidates:
            _, candidate_row, candidate_column = min(candidates)
            return candidate_row, candidate_column
    return None


def _astar(
    cost: np.ndarray,
    start: Tuple[int, int],
    goal: Tuple[int, int],
    cell_size: float,
    *,
    elevation: Optional[np.ndarray] = None,
    road_mask: Optional[np.ndarray] = None,
    maximum_grade_percent: float = math.inf,
) -> Optional[List[Tuple[int, int]]]:
    if start == goal:
        return [start]
    rows, columns = cost.shape
    local = cost.copy()
    finite_costs = local[np.isfinite(local)]
    if finite_costs.size == 0:
        return None
    endpoint_cost = max(1.0, float(np.median(finite_costs)))
    for row, column in (start, goal):
        # A caller may explicitly place an endpoint on a blocked cell. Permit
        # that exact endpoint only; opening its whole 3x3 neighbourhood lets a
        # path cut through nearby water/buildings and produces an infinite
        # reported route cost when evaluated against the original surface.
        if not math.isfinite(float(local[row, column])):
            local[row, column] = endpoint_cost
    minimum_cost = max(0.01, float(np.min(local[np.isfinite(local)])))
    frontier: List[Tuple[float, float, int, int]] = [(0.0, 0.0, start[0], start[1])]
    best = {start: 0.0}
    parent: Dict[Tuple[int, int], Tuple[int, int]] = {}
    while frontier:
        _, current_cost, row, column = heapq.heappop(frontier)
        current = (row, column)
        if current == goal:
            path = [current]
            while path[-1] != start:
                path.append(parent[path[-1]])
            return list(reversed(path))
        if current_cost > best.get(current, math.inf) + 1e-9:
            continue
        for dr, dc, factor in NEIGHBOURS:
            nr, nc = row + dr, column + dc
            if not (0 <= nr < rows and 0 <= nc < columns) or not math.isfinite(float(local[nr, nc])):
                continue
            if dr and dc and not (math.isfinite(float(local[row, nc])) or math.isfinite(float(local[nr, column]))):
                continue
            if elevation is not None:
                horizontal = factor * cell_size
                left_elevation = float(elevation[row, column])
                right_elevation = float(elevation[nr, nc])
                if not (math.isfinite(left_elevation) and math.isfinite(right_elevation)):
                    continue
                grade = abs(right_elevation - left_elevation) / horizontal * 100.0
                uses_existing_road = bool(
                    road_mask is not None
                    and (road_mask[row, column] or road_mask[nr, nc])
                )
                if grade > maximum_grade_percent and not uses_existing_road:
                    continue
            step = factor * cell_size * (float(local[row, column]) + float(local[nr, nc])) / 2.0
            candidate = current_cost + step
            neighbour = (nr, nc)
            if candidate + 1e-9 >= best.get(neighbour, math.inf):
                continue
            best[neighbour] = candidate
            parent[neighbour] = current
            heuristic = math.hypot(goal[0] - nr, goal[1] - nc) * cell_size * minimum_cost
            heapq.heappush(frontier, (candidate + heuristic, candidate, nr, nc))
    return None


def _chaikin(coordinates: Sequence[Tuple[float, float]], iterations: int = 2) -> List[Tuple[float, float]]:
    output = list(coordinates)
    for _ in range(iterations):
        if len(output) < 3:
            break
        refined = [output[0]]
        for left, right in zip(output, output[1:]):
            refined.append((0.75 * left[0] + 0.25 * right[0], 0.75 * left[1] + 0.25 * right[1]))
            refined.append((0.25 * left[0] + 0.75 * right[0], 0.25 * left[1] + 0.75 * right[1]))
        refined.append(output[-1])
        output = refined
    return output


def _line_is_valid(line: LineString, context: TerrainContext, start: Point, end: Point) -> bool:
    count = max(2, int(math.ceil(line.length / (context.cell_size / 2.0))))
    for index in range(count + 1):
        point = line.interpolate(index / count, normalized=True)
        row, column = context.point_to_cell(point)
        if context.blocked[row, column] and point.distance(start) > context.cell_size * 1.5 and point.distance(end) > context.cell_size * 1.5:
            return False
    return True


def _minimum_curve_radius(line: LineString) -> Optional[float]:
    coordinates = list(line.coords)
    radii: List[float] = []
    for left, middle, right in zip(coordinates, coordinates[1:], coordinates[2:]):
        a = math.dist(middle, right)
        b = math.dist(left, right)
        c = math.dist(left, middle)
        cross = abs((middle[0] - left[0]) * (right[1] - left[1]) - (middle[1] - left[1]) * (right[0] - left[0]))
        if cross <= 1e-6:
            continue
        radius = a * b * c / (2.0 * cross)
        if math.isfinite(radius):
            radii.append(radius)
    return min(radii) if radii else None


def _engineering_metrics(path: Sequence[Tuple[int, int]], line: LineString, context: TerrainContext) -> Dict[str, Any]:
    grades: List[float] = []
    slopes: List[float] = []
    elevations: List[float] = []
    new_slopes: List[float] = []
    for row, column in path:
        elevations.append(float(context.elevation[row, column]))
        slopes.append(float(context.slope[row, column]))
        if not context.road_mask[row, column]:
            new_slopes.append(float(context.slope[row, column]))
    terrain_data_complete = all(math.isfinite(value) for value in (*elevations, *slopes))
    if not terrain_data_complete:
        return {
            "terrain_data_complete": False,
            "elevation_start_m": None,
            "elevation_end_m": None,
            "elevation_min_m": None,
            "elevation_max_m": None,
            "maximum_grade_percent": None,
            "mean_grade_percent": None,
            "maximum_cross_slope_deg": None,
            "mean_cross_slope_deg": None,
            "minimum_curve_radius_m": _minimum_curve_radius(line),
            "terrain_sample_count": len(path),
        }
    for (left_row, left_col), (right_row, right_col), left_z, right_z in zip(path, path[1:], elevations, elevations[1:]):
        distance = math.hypot(right_row - left_row, right_col - left_col) * context.cell_size
        uses_existing_road = bool(
            context.road_mask[left_row, left_col]
            or context.road_mask[right_row, right_col]
        )
        if distance > 0 and not uses_existing_road:
            grades.append(abs(right_z - left_z) / distance * 100.0)
    radius = _minimum_curve_radius(line)
    return {
        "terrain_data_complete": True,
        "elevation_start_m": round(elevations[0], 3),
        "elevation_end_m": round(elevations[-1], 3),
        "elevation_min_m": round(min(elevations), 3),
        "elevation_max_m": round(max(elevations), 3),
        "maximum_grade_percent": round(max(grades, default=0.0), 3),
        "mean_grade_percent": round(float(np.mean(grades)) if grades else 0.0, 3),
        "maximum_cross_slope_deg": round(max(new_slopes, default=0.0), 3),
        "mean_cross_slope_deg": round(float(np.mean(new_slopes)) if new_slopes else 0.0, 3),
        "minimum_curve_radius_m": round(radius, 3) if radius is not None else None,
        "terrain_sample_count": len(path),
        "new_terrain_sample_count": len(new_slopes),
    }


def generate_least_cost_routes(
    start: Point,
    end: Point,
    context: TerrainContext,
    *,
    preferred_slope_deg: float,
    hazard_distance_m: float,
    maximum_grade_percent: float = 18.0,
) -> List[Dict[str, Any]]:
    """Generate one terrain-aware route for each explainable strategy."""
    requested_start_cell, requested_end_cell = context.point_to_cell(start), context.point_to_cell(end)
    output: List[Dict[str, Any]] = []
    for strategy in ("shortest_distance", "lowest_land_cost", "minimum_environmental_impact"):
        surface = _cost_surface(context, strategy, preferred_slope_deg, hazard_distance_m)
        start_cell = _nearest_traversable(surface, requested_start_cell)
        end_cell = _nearest_traversable(surface, requested_end_cell)
        if start_cell is None or end_cell is None:
            continue
        path = _astar(
            surface,
            start_cell,
            end_cell,
            context.cell_size,
            elevation=context.elevation,
            road_mask=context.road_mask,
            maximum_grade_percent=maximum_grade_percent,
        )
        if not path or len(path) < 2:
            continue
        coordinates = [context.cell_to_xy(row, column) for row, column in path]
        coordinates[0], coordinates[-1] = (start.x, start.y), (end.x, end.y)
        raw = LineString(coordinates)
        simplified = raw.simplify(context.cell_size * 0.55, preserve_topology=False)
        smoothed = LineString(_chaikin(list(simplified.coords), 2)) if len(simplified.coords) >= 3 else simplified
        line = smoothed if _line_is_valid(smoothed, context, start, end) else (simplified if _line_is_valid(simplified, context, start, end) else raw)
        route_cost = 0.0
        for (left_row, left_col), (right_row, right_col) in zip(path, path[1:]):
            distance = math.hypot(right_row - left_row, right_col - left_col) * context.cell_size
            route_cost += distance * (float(surface[left_row, left_col]) + float(surface[right_row, right_col])) / 2.0
        if not math.isfinite(route_cost):
            # Do not emit non-standard Infinity values in GeoJSON. This also
            # guards against a future pathfinding regression through a blocked
            # cost cell.
            continue
        output.append(
            {
                "strategy": strategy,
                "line": line,
                "raw_grid_length_m": round(raw.length, 3),
                "least_cost_value": round(route_cost, 3),
                "start_cell_adjustment_m": round(
                    math.hypot(
                        start_cell[0] - requested_start_cell[0],
                        start_cell[1] - requested_start_cell[1],
                    )
                    * context.cell_size,
                    3,
                ),
                "end_cell_adjustment_m": round(
                    math.hypot(
                        end_cell[0] - requested_end_cell[0],
                        end_cell[1] - requested_end_cell[1],
                    )
                    * context.cell_size,
                    3,
                ),
                "smoothing_applied": line.equals(smoothed),
                "engineering": _engineering_metrics(path, line, context),
            }
        )
    return output


def route_impact_metrics(
    line: LineString,
    roads_union: Any,
    *,
    requested_action: str,
    planned_width_m: float,
    existing_width_m: float,
    road_buffer_m: float,
) -> Dict[str, Any]:
    existing_corridor = roads_union.buffer(road_buffer_m)
    reused = line.intersection(existing_corridor)
    new = line.difference(existing_corridor)
    new_length = float(new.length)
    existing_length = float(reused.length)
    action = str(requested_action or "new").lower()
    widen_length = existing_length if action == "widen" else 0.0
    harden_length = existing_length if action == "harden" else 0.0
    reuse_length = max(0.0, existing_length - widen_length - harden_length)
    widening_extra_width = max(0.0, planned_width_m - existing_width_m)
    footprint = new_length * planned_width_m + widen_length * widening_extra_width
    return {
        "new_length_m": round(new_length, 3),
        "reuse_existing_length_m": round(reuse_length, 3),
        "widen_length_m": round(widen_length, 3),
        "harden_length_m": round(harden_length, 3),
        "construction_length_m": round(new_length + widen_length + harden_length, 3),
        "net_new_footprint_m2": round(footprint, 3),
        "planned_width_m": round(planned_width_m, 3),
        "assumed_existing_width_m": round(existing_width_m, 3),
        "new_geometry": new,
        "existing_geometry": reused,
    }


def line_parts(geometry: Any) -> List[LineString]:
    if geometry is None or geometry.is_empty:
        return []
    if geometry.geom_type == "LineString":
        return [geometry]
    if geometry.geom_type in {"MultiLineString", "GeometryCollection"}:
        output: List[LineString] = []
        for part in geometry.geoms:
            output.extend(line_parts(part))
        return output
    return []


__all__ = [
    "TerrainContext",
    "generate_least_cost_routes",
    "line_parts",
    "load_terrain_context",
    "route_impact_metrics",
]
