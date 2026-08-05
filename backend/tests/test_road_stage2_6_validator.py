from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.modules.spatial_ops.road import PlanningNodeBuildConfig, build_planning_nodes
from app.modules.spatial_ops.road.stage2_6_validator import validate_stage2_6_outputs


CRS = {"type": "name", "properties": {"name": "EPSG:4527"}}


def _write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _collection(features: list[dict]) -> dict:
    return {"type": "FeatureCollection", "crs": CRS, "features": features}


def _feature(geometry: dict | None, properties: dict) -> dict:
    return {"type": "Feature", "geometry": geometry, "properties": properties}


def _base_stage2(root: Path) -> tuple[Path, Path, Path]:
    stage2 = root / "stage2"
    _write(
        stage2 / "demand_points.geojson",
        _collection(
            [
                _feature(
                    {"type": "Point", "coordinates": [220, 220]},
                    {
                        "demand_id": "D001",
                        "name": "service node",
                        "demand_type": "public_service",
                        "priority": "high",
                    },
                )
            ]
        ),
    )
    _write(stage2 / "road_projects.json", {"projects": []})
    _write(stage2 / "road_constraints.json", {"constraints": []})
    roads = root / "road_edges.geojson"
    _write(
        roads,
        _collection(
            [
                _feature(
                    {"type": "LineString", "coordinates": [[0, 0], [100, 0]]},
                    {"edge_id": "E000001", "component_id": "C0001"},
                )
            ]
        ),
    )
    boundary = root / "boundary.geojson"
    _write(
        boundary,
        _collection(
            [
                _feature(
                    {
                        "type": "Polygon",
                        "coordinates": [[[-100, -100], [500, -100], [500, 500], [-100, 500], [-100, -100]]],
                    },
                    {"name": "boundary"},
                )
            ]
        ),
    )
    return stage2, roads, boundary


def test_validate_stage2_6_outputs_accepts_generated_contract(tmp_path: Path) -> None:
    stage2, roads, boundary = _base_stage2(tmp_path)
    result = build_planning_nodes(
        PlanningNodeBuildConfig(
            stage2_dir=stage2,
            output_dir=tmp_path / "stage2_6",
            road_edges_path=roads,
            boundary_path=boundary,
            metric_crs="EPSG:4527",
            display_crs="EPSG:4527",
        )
    )

    report = validate_stage2_6_outputs(result.output_dir)

    assert report["valid"] is True
    assert report["counts"]["planning_nodes"] == 1
    assert report["counts"]["planning_kg_update_triples"] > 0
    assert "planning_kg_updates.json" in report["checked_files"]
    assert "spatial_quality_gates.json" in report["checked_files"]


def test_validate_stage2_6_outputs_rejects_unknown_request_node_reference(tmp_path: Path) -> None:
    stage2, roads, boundary = _base_stage2(tmp_path)
    result = build_planning_nodes(
        PlanningNodeBuildConfig(
            stage2_dir=stage2,
            output_dir=tmp_path / "stage2_6",
            road_edges_path=roads,
            boundary_path=boundary,
            metric_crs="EPSG:4527",
            display_crs="EPSG:4527",
        )
    )
    requests_path = result.road_planning_requests_path
    payload = json.loads(requests_path.read_text(encoding="utf-8"))
    payload["requests"][0]["served_node_ids"] = ["PN-DOES-NOT-EXIST"]
    _write(requests_path, payload)

    with pytest.raises(ValueError, match="unknown served_node_id"):
        validate_stage2_6_outputs(result.output_dir)


def test_validate_stage2_6_outputs_rejects_unknown_kg_entity_reference(tmp_path: Path) -> None:
    stage2, roads, boundary = _base_stage2(tmp_path)
    result = build_planning_nodes(
        PlanningNodeBuildConfig(
            stage2_dir=stage2,
            output_dir=tmp_path / "stage2_6",
            road_edges_path=roads,
            boundary_path=boundary,
            metric_crs="EPSG:4527",
            display_crs="EPSG:4527",
        )
    )
    kg_path = result.kg_updates_path
    payload = json.loads(kg_path.read_text(encoding="utf-8"))
    aggregate = next(item for item in payload["triples"] if item["predicate"] == "aggregates_entity")
    aggregate["object"] = "ENT-DOES-NOT-EXIST"
    _write(kg_path, payload)

    with pytest.raises(ValueError, match="unknown entity object"):
        validate_stage2_6_outputs(result.output_dir)


def test_validate_stage2_6_outputs_rejects_invalid_kg_bsm_reference(tmp_path: Path) -> None:
    stage2, roads, boundary = _base_stage2(tmp_path)
    result = build_planning_nodes(
        PlanningNodeBuildConfig(
            stage2_dir=stage2,
            output_dir=tmp_path / "stage2_6",
            road_edges_path=roads,
            boundary_path=boundary,
            metric_crs="EPSG:4527",
            display_crs="EPSG:4527",
        )
    )
    kg_path = result.kg_updates_path
    payload = json.loads(kg_path.read_text(encoding="utf-8"))
    entity = json.loads(result.located_entities_path.read_text(encoding="utf-8"))["features"][0]["properties"]
    payload["triples"].append(
        {
            "subject": entity["entity_id"],
            "predicate": "candidate_bsm",
            "object": "BSM-DOES-NOT-EXIST",
            "confidence": 0.9,
        }
    )
    payload["triple_count"] = len(payload["triples"])
    _write(kg_path, payload)

    with pytest.raises(ValueError, match="unknown BSM object"):
        validate_stage2_6_outputs(result.output_dir)


def test_validate_stage2_6_outputs_rejects_intent_without_text_provenance(tmp_path: Path) -> None:
    stage2, roads, boundary = _base_stage2(tmp_path)
    _write(
        stage2 / "road_projects.json",
        {
            "projects": [
                {
                    "project_id": "RP001",
                    "action": "new",
                    "start_place": "A",
                    "end_place": "B",
                }
            ]
        },
    )
    result = build_planning_nodes(
        PlanningNodeBuildConfig(
            stage2_dir=stage2,
            output_dir=tmp_path / "stage2_6",
            road_edges_path=roads,
            boundary_path=boundary,
            metric_crs="EPSG:4527",
            display_crs="EPSG:4527",
        )
    )

    with pytest.raises(ValueError, match="has no evidence_text"):
        validate_stage2_6_outputs(result.output_dir)
