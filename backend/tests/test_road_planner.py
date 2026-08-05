from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from app.modules.spatial_ops.road import RoadPlanningConfig, run_stage4_road_planning


CRS = {"type": "name", "properties": {"name": "EPSG:4527"}}


def _write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _fc(features: list[dict]) -> dict:
    return {"type": "FeatureCollection", "crs": CRS, "features": features}


def _feature(geometry: dict | None, properties: dict) -> dict:
    return {"type": "Feature", "geometry": geometry, "properties": properties}


def _inputs(root: Path) -> RoadPlanningConfig:
    nodes_path = root / "stage1" / "road_nodes.geojson"
    edges_path = root / "stage1" / "road_edges.geojson"
    nodes = [
        _feature({"type": "Point", "coordinates": [0, 0]}, {"node_id": "N1", "component_id": "C1"}),
        _feature({"type": "Point", "coordinates": [100, 0]}, {"node_id": "N2", "component_id": "C1"}),
        _feature({"type": "Point", "coordinates": [200, 0]}, {"node_id": "N3", "component_id": "C2"}),
        _feature({"type": "Point", "coordinates": [300, 0]}, {"node_id": "N4", "component_id": "C2"}),
    ]
    edges = [
        _feature({"type": "LineString", "coordinates": [[0, 0], [100, 0]]}, {"edge_id": "E1", "from_node": "N1", "to_node": "N2", "component_id": "C1"}),
        _feature({"type": "LineString", "coordinates": [[200, 0], [300, 0]]}, {"edge_id": "E2", "from_node": "N3", "to_node": "N4", "component_id": "C2"}),
    ]
    _write(nodes_path, _fc(nodes))
    _write(edges_path, _fc(edges))

    stage3 = root / "stage3"
    demands = [
        _feature({"type": "Point", "coordinates": [0, 0]}, {"demand_id": "D1", "name": "居民点", "demand_type": "settlement", "network_status": "connected"}),
        _feature({"type": "Point", "coordinates": [100, 0]}, {"demand_id": "D2", "name": "卫生站", "demand_type": "healthcare", "network_status": "connected"}),
        _feature({"type": "Point", "coordinates": [50, 100]}, {"demand_id": "D3", "name": "孤立项目", "demand_type": "industry", "network_status": "isolated", "priority": "high"}),
    ]
    _write(stage3 / "demand_network_binding.geojson", _fc(demands))
    _write(stage3 / "road_project_spatial_binding.json", {"projects": []})
    _write(stage3 / "road_project_endpoints.geojson", _fc([]))
    water = _feature(
        {"type": "Polygon", "coordinates": [[[145, -20], [155, -20], [155, 20], [145, 20], [145, -20]]]},
        {"constraint_id": "C1", "target_layer": "water", "severity": "hard"},
    )
    _write(stage3 / "spatial_constraints.geojson", _fc([water]))

    boundary = root / "boundary.geojson"
    _write(boundary, _fc([_feature({"type": "Polygon", "coordinates": [[[-100, -200], [400, -200], [400, 200], [-100, 200], [-100, -200]]]}, {"name": "村界"})]))
    landuse = root / "landuse.geojson"
    _write(landuse, _fc([_feature({"type": "Polygon", "coordinates": [[[-100, -200], [400, -200], [400, 200], [-100, 200], [-100, -200]]]}, {"DLMC": "林地"})]))
    hazards = root / "hazards.geojson"
    _write(hazards, _fc([_feature({"type": "Point", "coordinates": [50, 30]}, {"name": "风险点"})]))
    return RoadPlanningConfig(
        road_nodes_path=nodes_path,
        road_edges_path=edges_path,
        stage3_dir=stage3,
        boundary_path=boundary,
        landuse_path=landuse,
        hazard_points_path=hazards,
        output_dir=root / "output",
        metric_crs="EPSG:4527",
        display_crs="EPSG:4527",
        deadend_search_radius_m=150,
        component_search_radius_m=150,
        max_deadend_requests=2,
    )


def test_stage4_analyzes_network_accessibility_and_candidates(tmp_path: Path) -> None:
    config = _inputs(tmp_path)
    result = run_stage4_road_planning(config)
    assert result.report["network_analysis"]["connected_component_count"] == 2
    assert result.report["network_analysis"]["dead_end_node_count"] == 4
    accessibility = json.loads(result.accessibility_path.read_text(encoding="utf-8"))
    assert accessibility["records"][0]["shortest_path_length_m"] == 100
    assert accessibility["records"][0]["shortest_travel_time_min"] == pytest.approx(0.3)
    assert accessibility["records"][0]["detour_ratio"] == 1
    candidates = json.loads(result.candidates_path.read_text(encoding="utf-8"))["features"]
    assert candidates
    isolated_shortest = [
        item
        for item in candidates
        if item["properties"]["source_type"] == "isolated_demand"
        and item["properties"]["strategy"] == "shortest_distance"
    ]
    assert len(isolated_shortest) == 1
    assert isolated_shortest[0]["properties"]["length_m"] == pytest.approx(100)
    assert isolated_shortest[0]["geometry"]["coordinates"][-1] == pytest.approx([50, 0])
    assert {item["properties"]["strategy"] for item in candidates} == {
        "shortest_distance",
        "lowest_land_cost",
        "minimum_environmental_impact",
    }
    evaluations = json.loads(result.evaluations_path.read_text(encoding="utf-8"))["evaluations"]
    assert all("network_connection_valid" in item["checks"] for item in evaluations)
    assert all("crosses_water" in item["checks"] for item in evaluations)
    assert all(item["is_construction_design"] is False for item in evaluations)


def test_stage4_clusters_nearby_access_points_before_road_connection(tmp_path: Path) -> None:
    stage1 = tmp_path / "stage1"
    _write(
        stage1 / "road_nodes.geojson",
        _fc(
            [
                _feature({"type": "Point", "coordinates": [0, 0]}, {"node_id": "N1", "component_id": "C1"}),
                _feature({"type": "Point", "coordinates": [100, 0]}, {"node_id": "N2", "component_id": "C1"}),
            ]
        ),
    )
    _write(
        stage1 / "road_edges.geojson",
        _fc(
            [
                _feature(
                    {"type": "LineString", "coordinates": [[0, 0], [100, 0]]},
                    {"edge_id": "E1", "from_node": "N1", "to_node": "N2", "component_id": "C1"},
                )
            ]
        ),
    )
    stage3 = tmp_path / "stage3"
    _write(
        stage3 / "demand_network_binding.geojson",
        _fc(
            [
                _feature({"type": "Point", "coordinates": [40, 100]}, {"demand_id": "D1", "demand_type": "settlement", "network_status": "isolated"}),
                _feature({"type": "Point", "coordinates": [55, 110]}, {"demand_id": "D2", "demand_type": "settlement", "network_status": "isolated"}),
            ]
        ),
    )
    _write(stage3 / "road_project_spatial_binding.json", {"projects": []})
    _write(stage3 / "road_project_endpoints.geojson", _fc([]))
    _write(stage3 / "spatial_constraints.geojson", _fc([]))
    boundary = tmp_path / "boundary.geojson"
    _write(boundary, _fc([_feature({"type": "Polygon", "coordinates": [[[-50, -50], [150, -50], [150, 200], [-50, 200], [-50, -50]]]}, {})]))
    landuse = tmp_path / "landuse.geojson"
    _write(landuse, _fc([_feature({"type": "Polygon", "coordinates": [[[-50, -50], [150, -50], [150, 200], [-50, 200], [-50, -50]]]}, {"DLMC": "鏋楀湴"})]))

    result = run_stage4_road_planning(
        RoadPlanningConfig(
            road_nodes_path=stage1 / "road_nodes.geojson",
            road_edges_path=stage1 / "road_edges.geojson",
            stage3_dir=stage3,
            boundary_path=boundary,
            landuse_path=landuse,
            output_dir=tmp_path / "output",
            metric_crs="EPSG:4527",
            display_crs="EPSG:4527",
            max_deadend_requests=0,
            max_component_requests=0,
            access_cluster_distance_m=30,
            min_access_connector_length_m=20,
        )
    )
    candidates = json.loads(result.candidates_path.read_text(encoding="utf-8"))["features"]
    assert len(candidates) == 3
    assert {item["properties"]["source_type"] for item in candidates} == {"access_cluster"}
    assert all(item["properties"]["access_point_count"] == 2 for item in candidates)
    assert candidates[0]["properties"]["grouped_source_ids"] == ["D1", "D2"]


def test_stage4_outputs_are_deterministic(tmp_path: Path) -> None:
    config = _inputs(tmp_path)
    first = run_stage4_road_planning(config)
    names = [
        first.network_analysis_path,
        first.accessibility_path,
        first.candidates_path,
        first.evaluations_path,
        first.blocked_requests_path,
        first.preview_path,
        first.report_path,
    ]
    first_hashes = [hashlib.sha256(path.read_bytes()).hexdigest() for path in names]
    second = run_stage4_road_planning(config)
    second_paths = [
        second.network_analysis_path,
        second.accessibility_path,
        second.candidates_path,
        second.evaluations_path,
        second.blocked_requests_path,
        second.preview_path,
        second.report_path,
    ]
    assert first_hashes == [hashlib.sha256(path.read_bytes()).hexdigest() for path in second_paths]


def test_stage4_rejects_planned_road_input(tmp_path: Path) -> None:
    config = _inputs(tmp_path)
    planned = tmp_path / "planned" / "road.geojson"
    _write(planned, _fc([]))
    invalid = RoadPlanningConfig(
        road_nodes_path=config.road_nodes_path,
        road_edges_path=planned,
        stage3_dir=config.stage3_dir,
        boundary_path=config.boundary_path,
        landuse_path=config.landuse_path,
        output_dir=config.output_dir,
    )
    with pytest.raises(ValueError, match="planned/evaluation"):
        run_stage4_road_planning(invalid)


def test_stage4_respects_explicit_stage3_planning_gate(tmp_path: Path) -> None:
    config = _inputs(tmp_path)
    _write(
        config.stage3_dir / "stage3_report.json",
        {
            "planning_gate": {
                "automatic_route_generation_allowed": False,
                "reason": "KG retry and human confirmation are still required.",
            }
        },
    )

    result = run_stage4_road_planning(config)

    candidates = json.loads(result.candidates_path.read_text(encoding="utf-8"))["features"]
    blocked = json.loads(result.blocked_requests_path.read_text(encoding="utf-8"))["blocked_requests"]
    assert candidates == []
    assert result.report["stage3_planning_gate"]["automatic_route_generation_allowed"] is False
    assert result.report["pre_gate_candidate_request_count"] > 0
    assert result.report["gate_blocked_candidate_request_count"] == result.report["pre_gate_candidate_request_count"]
    assert any(item["reason"] == "stage3_planning_gate_blocked" for item in blocked)
