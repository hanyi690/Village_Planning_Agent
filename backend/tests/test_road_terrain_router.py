from __future__ import annotations

import math
from pathlib import Path

import numpy as np
from shapely.geometry import LineString, Point, box
from shapely.ops import unary_union

from app.modules.spatial_ops.road.terrain_router import (
    generate_least_cost_routes,
    load_terrain_context,
    route_impact_metrics,
)


def _grid(path: Path) -> None:
    shape = (20, 20)
    np.savez_compressed(
        path,
        elevation_m=np.full(shape, 100.0),
        slope_deg=np.zeros(shape),
        land_cost=np.full(shape, 2.0),
        inside_boundary=np.ones(shape, dtype=np.uint8),
        x_min=np.array(0.0),
        y_max=np.array(600.0),
        cell_size_m=np.array(30.0),
        metric_crs=np.array("EPSG:4527"),
    )


def test_terrain_router_bends_around_hard_constraint(tmp_path: Path) -> None:
    grid = tmp_path / "terrain.npz"
    _grid(grid)
    water = unary_union([box(270, 0, 330, 390), box(270, 480, 330, 600)])
    current_road = LineString([(15, 300), (90, 300)])
    context = load_terrain_context(
        grid,
        constraints={"water": water},
        buildings=None,
        hazards=None,
        roads_union=current_road,
        max_slope_deg=35,
        existing_road_buffer_m=4,
        hazard_screening_distance_m=100,
    )
    routes = generate_least_cost_routes(
        Point(45, 300), Point(555, 300), context,
        preferred_slope_deg=12,
        hazard_distance_m=100,
    )
    assert len(routes) == 3
    assert all(len(route["line"].coords) > 2 for route in routes)
    assert all(not route["line"].intersects(water) for route in routes)
    assert all(route["engineering"]["maximum_grade_percent"] == 0 for route in routes)
    assert all(math.isfinite(route["least_cost_value"]) for route in routes)


def test_route_impact_counts_only_net_new_footprint() -> None:
    current = LineString([(0, 0), (100, 0)])
    route = LineString([(0, 0), (100, 0), (200, 0)])
    metrics = route_impact_metrics(
        route,
        current,
        requested_action="widen",
        planned_width_m=5.0,
        existing_width_m=3.5,
        road_buffer_m=2.0,
    )
    assert metrics["new_length_m"] == 98.0
    assert metrics["widen_length_m"] == 102.0
    assert metrics["reuse_existing_length_m"] == 0.0
    assert metrics["net_new_footprint_m2"] == 643.0


def test_terrain_router_avoids_excessive_longitudinal_grade(tmp_path: Path) -> None:
    grid = tmp_path / "grade_barrier.npz"
    shape = (20, 20)
    elevation = np.zeros(shape)
    elevation[:15, 9:11] = 30.0
    np.savez_compressed(
        grid,
        elevation_m=elevation,
        slope_deg=np.zeros(shape),
        land_cost=np.ones(shape),
        inside_boundary=np.ones(shape, dtype=np.uint8),
        x_min=np.array(0.0),
        y_max=np.array(600.0),
        cell_size_m=np.array(30.0),
        metric_crs=np.array("EPSG:4527"),
    )
    context = load_terrain_context(
        grid,
        constraints={},
        buildings=None,
        hazards=None,
        roads_union=LineString(),
        max_slope_deg=35,
        existing_road_buffer_m=4,
        hazard_screening_distance_m=100,
    )
    routes = generate_least_cost_routes(
        Point(75, 525),
        Point(525, 525),
        context,
        preferred_slope_deg=12,
        hazard_distance_m=100,
        maximum_grade_percent=18,
    )
    assert len(routes) == 3
    assert all(route["engineering"]["maximum_grade_percent"] <= 18 for route in routes)
    assert all(len(route["line"].coords) > 2 for route in routes)


def test_terrain_router_avoids_demo_building_footprint(tmp_path: Path) -> None:
    grid = tmp_path / "building.npz"
    _grid(grid)
    building = box(270, 240, 330, 360)
    context = load_terrain_context(
        grid,
        constraints={},
        buildings=building,
        hazards=None,
        roads_union=LineString(),
        max_slope_deg=35,
        existing_road_buffer_m=4,
        hazard_screening_distance_m=100,
        block_buildings=True,
    )
    routes = generate_least_cost_routes(
        Point(45, 300),
        Point(555, 300),
        context,
        preferred_slope_deg=12,
        hazard_distance_m=100,
    )
    assert len(routes) == 3
    assert all(not route["line"].intersects(building) for route in routes)
