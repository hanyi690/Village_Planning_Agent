from __future__ import annotations

import hashlib
import json
from pathlib import Path

from tests.fixtures.road.demo_proxy import (
    build_demo_imagery_reviewed_road_baseline,
    generate_demo_proxy_inputs,
)


CRS = {"type": "name", "properties": {"name": "EPSG:4527"}}


def _write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _fc(features: list[dict]) -> dict:
    return {"type": "FeatureCollection", "crs": CRS, "features": features}


def _polygon(x: float, y: float) -> dict:
    return {
        "type": "Feature",
        "geometry": {
            "type": "Polygon",
            "coordinates": [[[x, y], [x + 40, y], [x + 40, y + 40], [x, y + 40], [x, y]]],
        },
        "properties": {"DLMC": "宅基地"},
    }


def test_demo_proxy_is_isolated_labelled_and_deterministic(tmp_path: Path) -> None:
    stage2 = tmp_path / "stage2"
    demands = []
    for index, place in enumerate(("甲村", "乙村", "丙村"), 1):
        demands.append(
            {
                "type": "Feature",
                "geometry": None,
                "properties": {
                    "demand_id": f"D{index}",
                    "name": place,
                    "place_name": place,
                    "demand_type": "settlement",
                },
            }
        )
    demands.append(
        {
            "type": "Feature",
            "geometry": None,
            "properties": {
                "demand_id": "D4",
                "name": "demo public service",
                "place_name": demands[0]["properties"]["place_name"],
                "demand_type": "public_service",
            },
        }
    )
    _write(stage2 / "demand_points.geojson", _fc(demands))
    _write(
        stage2 / "road_projects.json",
        {
            "projects": [
                {
                    "project_id": "RP1",
                    "start_demand_id": "D1",
                    "end_demand_id": "D2",
                    "start_place": "甲村",
                    "end_place": "乙村",
                    "service_places": ["甲村-乙村"],
                }
            ]
        },
    )
    _write(stage2 / "road_constraints.json", {"constraints": []})
    tasks_path = tmp_path / "tasks.json"
    _write(
        tasks_path,
        {
            "tasks": [
                {"task_id": f"LC{index:03d}", "task_type": "place", "place_name": place}
                for index, place in enumerate(("甲村", "乙村", "丙村"), 1)
            ]
        },
    )
    landuse = tmp_path / "landuse.geojson"
    _write(landuse, _fc([_polygon(0, 0), _polygon(300, 0), _polygon(600, 0)]))
    boundary = tmp_path / "boundary.geojson"
    _write(
        boundary,
        _fc(
            [
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [[[-100, -100], [800, -100], [800, 200], [-100, 200], [-100, -100]]],
                    },
                    "properties": {},
                }
            ]
        ),
    )
    output = tmp_path / "demo"
    kwargs = {
        "stage2_dir": stage2,
        "stage2_5_tasks_path": tasks_path,
        "landuse_path": landuse,
        "boundary_path": boundary,
        "output_dir": output,
        "metric_crs": "EPSG:4527",
        "display_crs": "EPSG:4527",
        "cluster_distance_m": 100,
    }
    report = generate_demo_proxy_inputs(**kwargs)
    assert report["data_mode"] == "demo_proxy"
    assert report["planned_road_read"] is False
    assert report["demo_healthcare_facility_count"] == 1
    demand_payload = json.loads((output / "demand_points.geojson").read_text(encoding="utf-8"))
    assert demand_payload["data_mode"] == "demo_proxy"
    assert all(feature["geometry"] for feature in demand_payload["features"])
    assert all(feature["properties"]["location_status"] == "proxy_demo" for feature in demand_payload["features"])
    healthcare = [
        feature
        for feature in demand_payload["features"]
        if feature["properties"]["demand_type"] == "healthcare"
    ]
    assert len(healthcare) == 1
    assert healthcare[0]["properties"]["demo_original_demand_type"] == "public_service"
    project_payload = json.loads((output / "road_projects.json").read_text(encoding="utf-8"))
    assert project_payload["projects"][0]["planning_status"] == "demo_proxy_ready"
    paths = sorted(output.glob("*"))
    first_hashes = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    generate_demo_proxy_inputs(**kwargs)
    assert first_hashes == {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}


def test_imagery_reviewed_demo_road_baseline_preserves_source(tmp_path: Path) -> None:
    source = tmp_path / "current_roads.geojson"
    _write(
        source,
        _fc(
            [
                {
                    "type": "Feature",
                    "geometry": {"type": "LineString", "coordinates": [[116.0, 24.8], [116.001, 24.801]]},
                    "properties": {"road_id": "CURRENT-001"},
                }
            ]
        ),
    )
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    result = build_demo_imagery_reviewed_road_baseline(
        current_road_path=source,
        output_path=tmp_path / "derived" / "current_roads_demo_only.geojson",
    )
    payload = json.loads(result["path"].read_text(encoding="utf-8"))
    manifest = json.loads(result["manifest_path"].read_text(encoding="utf-8"))
    assert hashlib.sha256(source.read_bytes()).hexdigest() == source_hash
    assert result["source_feature_count"] == 1
    assert result["imagery_reviewed_trace_count"] == 1
    assert len(payload["features"]) == 2
    assert manifest["original_bundle_modified"] is False
    appended = payload["features"][-1]["properties"]
    assert appended["road_status"] == "current_imagery_reviewed_demo_only"
    assert appended["requires_human_confirmation"] is True
