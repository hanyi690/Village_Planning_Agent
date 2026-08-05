"""Acceptance tests for Stage-2.5 manual spatial confirmation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.modules.spatial_ops.road.location_confirmation import (
    apply_location_confirmations,
    generate_location_confirmation_workflow,
)
from app.modules.spatial_ops.road.schemas import LocationConfirmationConfig


def _write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _config(tmp_path: Path) -> LocationConfirmationConfig:
    stage2 = tmp_path / "stage2"
    demand_features = []
    for index, name in enumerate(("甲村", "乙村"), 1):
        demand_features.append(
            {
                "type": "Feature",
                "id": f"D{index:03d}",
                "geometry": None,
                "properties": {
                    "demand_id": f"D{index:03d}",
                    "name": f"{name}自然村",
                    "demand_type": "settlement",
                    "place_name": name,
                    "location_status": "unresolved",
                    "location_confidence": 0.0,
                    "requires_human_confirmation": True,
                },
            }
        )
    _write(stage2 / "demand_points.geojson", {"type": "FeatureCollection", "features": demand_features})
    _write(
        stage2 / "road_projects.json",
        {
            "type": "RoadProjectCollection",
            "projects": [
                {
                    "project_id": "RP001",
                    "name": "村道硬化",
                    "start_place": "甲村",
                    "end_place": "乙村",
                    "start_location_status": "unresolved",
                    "end_location_status": "unresolved",
                    "start_geometry": None,
                    "end_geometry": None,
                    "planning_status": "blocked_needs_location_confirmation",
                    "requires_human_confirmation": True,
                    "evidence": {"source_text": "新建甲村至乙村道路"},
                }
            ],
        },
    )
    _write(
        stage2 / "road_constraints.json",
        {
            "type": "RoadConstraintCollection",
            "constraints": [
                {
                    "constraint_id": "C001",
                    "target_layer": "geological_hazard_points",
                    "description": "避让地质灾害风险区",
                    "buffer_m": None,
                    "requires_human_confirmation": True,
                    "evidence": {"evidence_id": "EV001"},
                }
            ],
        },
    )
    boundary = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[114.9, 23.9], [115.2, 23.9], [115.2, 24.2], [114.9, 24.2], [114.9, 23.9]]],
                },
                "properties": {},
            }
        ],
    }
    roads = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": [[115.0, 24.0], [115.1, 24.1]]},
                "properties": {},
            }
        ],
    }
    _write(tmp_path / "boundary.geojson", boundary)
    _write(tmp_path / "road.geojson", roads)
    return LocationConfirmationConfig(
        stage2_dir=stage2,
        output_dir=tmp_path / "stage2_5",
        boundary_path=tmp_path / "boundary.geojson",
        current_road_path=tmp_path / "road.geojson",
        maplibre_dist_dir=None,
    )


def _confirmation_files(
    config: LocationConfirmationConfig, *, with_parameter: bool = True, confirmed_by: str = "测试员"
) -> tuple[Path, Path]:
    workflow = generate_location_confirmation_workflow(config)
    tasks = json.loads(workflow.tasks_path.read_text(encoding="utf-8"))["tasks"]
    coordinates = {"甲村": [115.0, 24.0], "乙村": [115.1, 24.1]}
    features = []
    for task in tasks:
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": coordinates[task["place_name"]]},
                "properties": {
                    "task_id": task["task_id"],
                    "confirmation_type": "place",
                    "confirmation_status": "confirmed",
                    "confirmed_by": confirmed_by,
                    "confirmed_at": "2026-07-22T00:00:00Z",
                    "source_method": "manual_map_click",
                    "name": task["place_name"],
                },
            }
        )
    confirmations = config.output_dir / "test_confirmations.geojson"
    _write(confirmations, {"type": "FeatureCollection", "features": features})
    parameters = config.output_dir / "test_parameters.json"
    _write(
        parameters,
        {
            "type": "ConstraintParameterConfirmation",
            "parameters": [
                {
                    "constraint_id": "C001",
                    "status": "confirmed" if with_parameter else "pending",
                    "value": 50 if with_parameter else None,
                    "confirmed_by": "技术负责人" if with_parameter else None,
                    "confirmed_at": "2026-07-22T00:00:00Z" if with_parameter else None,
                    "basis": "项目地质灾害评估意见" if with_parameter else None,
                }
            ],
        },
    )
    return confirmations, parameters


def test_workflow_generates_unique_place_tasks_and_click_map(tmp_path: Path) -> None:
    result = generate_location_confirmation_workflow(_config(tmp_path))
    tasks = json.loads(result.tasks_path.read_text(encoding="utf-8"))["tasks"]

    assert result.report["place_task_count"] == 2
    assert result.report["road_endpoint_task_count"] == 0
    assert result.report["constraint_parameter_task_count"] == 1
    assert {task["place_name"] for task in tasks} == {"甲村", "乙村"}
    assert result.report["planned_geometry_read"] is False
    html = result.map_path.read_text(encoding="utf-8")
    assert "manual_map_click" in html
    assert "导出位置确认 GeoJSON" in html


def test_confirmed_points_and_buffers_make_project_ready(tmp_path: Path) -> None:
    config = _config(tmp_path)
    confirmations, parameters = _confirmation_files(config)
    report = apply_location_confirmations(config, confirmations, parameters)

    assert report["status"] == "ready_for_stage3"
    assert report["matched_demand_count"] == 2
    assert report["ready_project_count"] == 1
    project = json.loads(
        (config.output_dir / "resolved" / "road_projects.json").read_text(encoding="utf-8")
    )["projects"][0]
    constraint = json.loads(
        (config.output_dir / "resolved" / "road_constraints.json").read_text(encoding="utf-8")
    )["constraints"][0]
    assert project["planning_status"] == "ready"
    assert project["start_geometry"]["coordinates"] == [115.0, 24.0]
    assert project["end_geometry"]["coordinates"] == [115.1, 24.1]
    assert constraint["buffer_m"] == 50.0
    assert constraint["parameter_confirmation"]["basis"] == "项目地质灾害评估意见"


def test_missing_buffer_keeps_spatially_resolved_project_blocked(tmp_path: Path) -> None:
    config = _config(tmp_path)
    confirmations, parameters = _confirmation_files(config, with_parameter=False)
    report = apply_location_confirmations(config, confirmations, parameters)
    project = json.loads(
        (config.output_dir / "resolved" / "road_projects.json").read_text(encoding="utf-8")
    )["projects"][0]

    assert report["ready_project_count"] == 0
    assert report["pending_constraint_parameter_count"] == 1
    assert project["planning_status"] == "blocked_missing_constraint_parameters"


def test_confirmation_without_human_provenance_is_rejected(tmp_path: Path) -> None:
    config = _config(tmp_path)
    confirmations, parameters = _confirmation_files(config, confirmed_by="")
    with pytest.raises(ValueError, match="missing confirmed_by"):
        apply_location_confirmations(config, confirmations, parameters)
