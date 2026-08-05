from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.modules.spatial_ops.road import SpatialBindingConfig, bind_road_spatial_requirements


CRS = {"type": "name", "properties": {"name": "EPSG:4527"}}


def _write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _collection(features: list[dict]) -> dict:
    return {"type": "FeatureCollection", "crs": CRS, "features": features}


def _feature(geometry: dict | None, properties: dict) -> dict:
    return {"type": "Feature", "geometry": geometry, "properties": properties}


def _base_inputs(root: Path) -> tuple[Path, Path]:
    stage2 = root / "stage2"
    demands = [
        _feature({"type": "Point", "coordinates": [20, 5]}, {"demand_id": "D001", "name": "已连接", "demand_type": "settlement"}),
        _feature({"type": "Point", "coordinates": [40, 50]}, {"demand_id": "D002", "name": "较近", "demand_type": "industry"}),
        _feature({"type": "Point", "coordinates": [60, 200]}, {"demand_id": "D003", "name": "孤立", "demand_type": "tourism"}),
        _feature(None, {"demand_id": "D004", "name": "未知", "demand_type": "public_service", "location_status": "unresolved"}),
    ]
    _write(stage2 / "demand_points.geojson", _collection(demands))
    _write(stage2 / "road_projects.json", {"projects": []})
    _write(
        stage2 / "road_constraints.json",
        {
            "constraints": [
                {
                    "constraint_id": "C001",
                    "constraint_type": "avoid",
                    "target_layer": "ecological_protection",
                    "severity": "hard",
                    "buffer_m": 0,
                    "evidence": {"evidence_id": "EV1"},
                },
                {
                    "constraint_id": "C002",
                    "constraint_type": "avoid",
                    "target_layer": "geological_hazard_points",
                    "severity": "soft",
                    "buffer_m": None,
                    "evidence": {"evidence_id": "EV2"},
                },
                {
                    "constraint_id": "C003",
                    "constraint_type": "design_standard",
                    "target_layer": "road_design",
                    "severity": "hard",
                    "buffer_m": 0,
                },
            ]
        },
    )
    roads = root / "road_edges.geojson"
    _write(
        roads,
        _collection(
            [
                _feature(
                    {"type": "LineString", "coordinates": [[0, 0], [100, 0]]},
                    {"edge_id": "E000001", "component_id": "C0001", "is_isolated_component": False},
                )
            ]
        ),
    )
    return stage2, roads


def test_stage3_classifies_distances_and_keeps_unknown_locations(tmp_path: Path) -> None:
    stage2, roads = _base_inputs(tmp_path)
    polygon = tmp_path / "eco.geojson"
    _write(
        polygon,
        _collection(
            [
                _feature(
                    {
                        "type": "Polygon",
                        "coordinates": [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]],
                    },
                    {"name": "生态区"},
                )
            ]
        ),
    )
    hazard = tmp_path / "hazard.geojson"
    _write(hazard, _collection([_feature({"type": "Point", "coordinates": [50, 50]}, {"name": "隐患点"})]))
    result = bind_road_spatial_requirements(
        SpatialBindingConfig(
            stage2_dir=stage2,
            road_edges_path=roads,
            output_dir=tmp_path / "output",
            metric_crs="EPSG:4527",
            display_crs="EPSG:4527",
            connected_threshold_m=10,
            near_network_threshold_m=100,
            constraint_layer_sources={
                "ecological_protection": (polygon,),
                "geological_hazard_points": (hazard,),
            },
        )
    )
    payload = json.loads(result.demand_binding_path.read_text(encoding="utf-8"))
    statuses = [feature["properties"]["network_status"] for feature in payload["features"]]
    assert statuses == ["connected", "near_network", "isolated", "unresolved"]
    assert payload["features"][1]["properties"]["distance_to_road_m"] == 50
    assert payload["features"][3]["geometry"] is None
    assert result.report["short_connector_required_count"] == 1
    assert result.report["new_route_required_count"] == 1
    assert result.report["spatially_bound_constraint_count"] == 1
    assert result.report["unresolved_constraint_count"] == 1
    assert result.report["nonspatial_design_constraint_count"] == 1


def test_stage3_binds_inline_stage2_6_constraint_geometry(tmp_path: Path) -> None:
    stage2, roads = _base_inputs(tmp_path)
    _write(
        stage2 / "road_constraints.json",
        {
            "constraints": [
                {
                    "constraint_id": "S26-C-0001",
                    "constraint_type": "avoid",
                    "target_layer": "farmland_protection",
                    "severity": "hard",
                    "buffer_m": 0,
                    "geometry_crs": "EPSG:4527",
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [[[20, 20], [40, 20], [40, 40], [20, 40], [20, 20]]],
                    },
                    "derived_from": "stage2_6_restricted_planning_entity",
                }
            ]
        },
    )

    result = bind_road_spatial_requirements(
        SpatialBindingConfig(
            stage2_dir=stage2,
            road_edges_path=roads,
            output_dir=tmp_path / "output",
            metric_crs="EPSG:4527",
            display_crs="EPSG:4527",
            connected_threshold_m=10,
            near_network_threshold_m=100,
        )
    )

    constraints = json.loads(result.constraints_path.read_text(encoding="utf-8"))["features"]
    assert len(constraints) == 1
    props = constraints[0]["properties"]
    assert props["constraint_id"] == "S26-C-0001"
    assert props["target_layer"] == "farmland_protection"
    assert props["spatial_binding_status"] == "bound"
    assert props["binding_source"] == "inline_stage2_6_geometry"
    assert result.report["spatially_bound_constraint_count"] == 1
    assert result.report["unresolved_constraint_count"] == 0


def test_stage3_prefers_stage2_5_and_exact_matches_point_sources(tmp_path: Path) -> None:
    stage2, roads = _base_inputs(tmp_path)
    resolved = tmp_path / "stage2_5" / "resolved"
    resolved_demands = _collection(
        [_feature(None, {"demand_id": "D100", "name": "展销中心", "place_name": "展销中心", "demand_type": "industry"})]
    )
    _write(resolved / "demand_points.geojson", resolved_demands)
    _write(
        resolved / "road_projects.json",
        {
            "projects": [
                {
                    "project_id": "RP100",
                    "name": "展销中心接入路",
                    "action": "new",
                    "start_place": "展销中心",
                    "start_demand_id": "D100",
                    "start_geometry": None,
                    "end_place": "展销中心",
                    "end_demand_id": "D100",
                    "end_geometry": None,
                }
            ]
        },
    )
    _write(resolved / "road_constraints.json", {"constraints": []})
    points = tmp_path / "points.geojson"
    _write(points, _collection([_feature({"type": "Point", "coordinates": [25, 4]}, {"name": "展销中心"})]))
    result = bind_road_spatial_requirements(
        SpatialBindingConfig(
            stage2_dir=stage2,
            stage2_5_resolved_dir=resolved,
            road_edges_path=roads,
            output_dir=tmp_path / "output",
            point_sources=(points,),
            metric_crs="EPSG:4527",
            display_crs="EPSG:4527",
        )
    )
    payload = json.loads(result.demand_binding_path.read_text(encoding="utf-8"))
    assert result.report["input_mode"] == "stage2_5_resolved"
    assert result.report["demand_count"] == 1
    assert payload["features"][0]["properties"]["location_status"] == "matched"
    assert payload["features"][0]["properties"]["network_status"] == "connected"
    projects = json.loads(result.project_binding_path.read_text(encoding="utf-8"))
    assert projects["projects"][0]["spatial_binding_status"] == "ready"
    assert projects["projects"][0]["planning_need"] == "new_route"


def test_stage3_prefers_stage2_6_planning_nodes_over_stage2_5(tmp_path: Path) -> None:
    stage2, roads = _base_inputs(tmp_path)
    resolved = tmp_path / "stage2_5" / "resolved"
    _write(
        resolved / "demand_points.geojson",
        _collection([_feature({"type": "Point", "coordinates": [10, 5]}, {"demand_id": "D250", "name": "stage2_5"})]),
    )
    _write(resolved / "road_projects.json", {"projects": []})
    _write(resolved / "road_constraints.json", {"constraints": []})

    stage2_6 = tmp_path / "stage2_6"
    _write(
        stage2_6 / "demand_points.geojson",
        _collection(
            [
                _feature(
                    {"type": "Point", "coordinates": [40, 50]},
                    {
                        "demand_id": "PN-0001",
                        "planning_node_id": "PN-0001",
                        "name": "stage2_6",
                        "demand_type": "industry_node",
                    },
                )
            ]
        ),
    )
    _write(stage2_6 / "road_projects.json", {"projects": []})
    _write(stage2_6 / "road_constraints.json", {"constraints": []})
    _write(stage2_6 / "planning_nodes.geojson", _collection([]))
    _write(stage2_6 / "road_planning_requests.json", {"requests": []})

    result = bind_road_spatial_requirements(
        SpatialBindingConfig(
            stage2_dir=stage2,
            stage2_6_dir=stage2_6,
            stage2_5_resolved_dir=resolved,
            road_edges_path=roads,
            output_dir=tmp_path / "output",
            metric_crs="EPSG:4527",
            display_crs="EPSG:4527",
        )
    )
    payload = json.loads(result.demand_binding_path.read_text(encoding="utf-8"))
    assert result.report["input_mode"] == "stage2_6_planning_nodes"
    assert result.report["demand_count"] == 1
    assert payload["features"][0]["properties"]["planning_node_id"] == "PN-0001"


def test_stage3_propagates_blocked_stage2_6_gate(tmp_path: Path) -> None:
    stage2, roads = _base_inputs(tmp_path)
    stage2_6 = tmp_path / "stage2_6"
    _write(
        stage2_6 / "demand_points.geojson",
        _collection(
            [
                _feature(
                    {"type": "Point", "coordinates": [20, 5]},
                    {
                        "demand_id": "PN-0001",
                        "planning_node_id": "PN-0001",
                        "name": "confirmed node",
                        "demand_type": "facility_node",
                    },
                )
            ]
        ),
    )
    _write(stage2_6 / "road_projects.json", {"projects": []})
    _write(stage2_6 / "road_constraints.json", {"constraints": []})
    _write(stage2_6 / "planning_nodes.geojson", _collection([]))
    _write(stage2_6 / "road_planning_requests.json", {"requests": []})
    _write(
        stage2_6 / "stage2_6_report.json",
        {
            "planning_gate": {
                "automatic_route_generation_allowed": False,
                "reason": "KG retry and human confirmation are required.",
            }
        },
    )

    result = bind_road_spatial_requirements(
        SpatialBindingConfig(
            stage2_dir=stage2,
            stage2_6_dir=stage2_6,
            road_edges_path=roads,
            output_dir=tmp_path / "output",
            metric_crs="EPSG:4527",
            display_crs="EPSG:4527",
        )
    )

    assert result.report["demand_status_counts"]["unresolved"] == 0
    assert result.report["stage2_6_planning_gate"]["available"] is True
    assert result.report["planning_gate"]["automatic_route_generation_allowed"] is False
    assert "KG retry and human confirmation" in result.report["planning_gate"]["reason"]


def test_stage3_rejects_planned_road_as_algorithm_input(tmp_path: Path) -> None:
    stage2, _ = _base_inputs(tmp_path)
    planned_road = tmp_path / "planned" / "road.geojson"
    _write(planned_road, _collection([]))
    with pytest.raises(ValueError, match="planned/evaluation"):
        bind_road_spatial_requirements(
            SpatialBindingConfig(
                stage2_dir=stage2,
                road_edges_path=planned_road,
                output_dir=tmp_path / "output",
            )
        )
