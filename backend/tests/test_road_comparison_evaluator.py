from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from app.services.modules.gis.road import PlanComparisonConfig, compare_road_plans


CRS = {"type": "name", "properties": {"name": "EPSG:4527"}}


def _write(path: Path, features: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"type": "FeatureCollection", "crs": CRS, "features": features}),
        encoding="utf-8",
    )


def _feature(geometry: dict, properties: dict) -> dict:
    return {"type": "Feature", "geometry": geometry, "properties": properties}


def _config(root: Path) -> PlanComparisonConfig:
    stage1 = root / "stage1"
    nodes = [
        _feature({"type": "Point", "coordinates": [0, 0]}, {"node_id": "N1"}),
        _feature({"type": "Point", "coordinates": [100, 0]}, {"node_id": "N2"}),
        _feature({"type": "Point", "coordinates": [200, 0]}, {"node_id": "N3"}),
        _feature({"type": "Point", "coordinates": [300, 0]}, {"node_id": "N4"}),
    ]
    edges = [
        _feature({"type": "LineString", "coordinates": [[0, 0], [100, 0]]}, {"edge_id": "E1", "from_node": "N1", "to_node": "N2"}),
        _feature({"type": "LineString", "coordinates": [[200, 0], [300, 0]]}, {"edge_id": "E2", "from_node": "N3", "to_node": "N4"}),
    ]
    _write(stage1 / "road_nodes.geojson", nodes)
    _write(stage1 / "road_edges.geojson", edges)
    algorithm = root / "stage5" / "recommended_candidates.geojson"
    _write(algorithm, [_feature({"type": "LineString", "coordinates": [[100, 0], [200, 0]]}, {"candidate_id": "C1"})])
    manual = root / "planned" / "road.geojson"
    _write(
        manual,
        edges + [_feature({"type": "LineString", "coordinates": [[100, 2], [200, 2]]}, {"road_id": "P1"})],
    )
    demands = root / "stage3" / "demand_network_binding.geojson"
    _write(
        demands,
        [
            _feature({"type": "Point", "coordinates": [50, 10]}, {"demand_id": "D1", "demand_type": "settlement", "population_served": 100}),
            _feature({"type": "Point", "coordinates": [250, 10]}, {"demand_id": "D2", "demand_type": "healthcare", "population_served": 0}),
        ],
    )
    landuse = root / "landuse.geojson"
    _write(
        landuse,
        [
            _feature({"type": "Polygon", "coordinates": [[[140, -5], [160, -5], [160, 5], [140, 5], [140, -5]]]}, {"DLBM": "3100"}),
            _feature({"type": "Polygon", "coordinates": [[[170, -5], [180, -5], [180, 5], [170, 5], [170, -5]]]}, {"DLBM": "2121"}),
        ],
    )
    ecology = root / "ecology.geojson"
    farmland = root / "farmland.geojson"
    hazards = root / "hazards.geojson"
    _write(ecology, [_feature({"type": "Polygon", "coordinates": [[[400, 0], [410, 0], [410, 10], [400, 10], [400, 0]]]}, {})])
    _write(farmland, [_feature({"type": "Polygon", "coordinates": [[[120, -5], [135, -5], [135, 5], [120, 5], [120, -5]]]}, {})])
    _write(hazards, [_feature({"type": "Point", "coordinates": [150, 20]}, {})])
    return PlanComparisonConfig(
        road_nodes_path=stage1 / "road_nodes.geojson",
        road_edges_path=stage1 / "road_edges.geojson",
        algorithm_roads_path=algorithm,
        manual_planned_roads_path=manual,
        demand_points_path=demands,
        landuse_path=landuse,
        ecological_protection_path=ecology,
        farmland_protection_path=farmland,
        hazard_points_path=hazards,
        output_dir=root / "stage6",
        metric_crs="EPSG:4527",
        display_crs="EPSG:4527",
        current_match_buffer_m=1.0,
        endpoint_match_m=10.0,
    )


def test_stage6_compares_geometry_function_and_reasonableness(tmp_path: Path) -> None:
    result = compare_road_plans(_config(tmp_path))
    report = result.report
    assert report["evaluation_design"]["planned_road_role"] == "held_out_evaluation_only"
    assert report["evaluation_design"]["manual_layer_detected_role"] == "complete_planned_network"
    assert report["geometry_similarity"]["average_symmetric_distance_m"] <= 2.1
    assert report["functional_consistency"]["algorithm_component_count"] == 1
    assert report["functional_consistency"]["manual_component_count"] == 1
    assert report["planning_reasonableness"]["algorithm"]["water_occupation_m2"] > 0
    assert report["planning_reasonableness"]["algorithm"]["basic_farmland_occupation_m2"] > 0
    assert result.comparison_table_path.exists()
    assert result.preview_path.exists()


def test_stage6_is_deterministic(tmp_path: Path) -> None:
    config = _config(tmp_path)
    first = compare_road_plans(config)
    paths = [first.algorithm_roads_path, first.manual_new_roads_path, first.preview_path, first.comparison_table_path, first.metrics_path, first.report_path]
    hashes = [hashlib.sha256(path.read_bytes()).hexdigest() for path in paths]
    second = compare_road_plans(config)
    assert hashes == [hashlib.sha256(path.read_bytes()).hexdigest() for path in paths]


def test_stage6_rejects_manual_reference_as_algorithm(tmp_path: Path) -> None:
    config = _config(tmp_path)
    invalid = PlanComparisonConfig(
        road_nodes_path=config.road_nodes_path,
        road_edges_path=config.road_edges_path,
        algorithm_roads_path=config.manual_planned_roads_path,
        manual_planned_roads_path=config.manual_planned_roads_path,
        demand_points_path=config.demand_points_path,
        landuse_path=config.landuse_path,
        ecological_protection_path=config.ecological_protection_path,
        farmland_protection_path=config.farmland_protection_path,
        hazard_points_path=config.hazard_points_path,
        output_dir=config.output_dir,
    )
    with pytest.raises(ValueError, match="algorithm roads"):
        compare_road_plans(invalid)
