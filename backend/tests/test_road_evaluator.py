from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from app.services.modules.gis.road import CandidateScoringConfig, score_road_candidates


CRS = {"type": "name", "properties": {"name": "EPSG:4527"}}


def _write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _fc(features: list[dict]) -> dict:
    return {"type": "FeatureCollection", "crs": CRS, "features": features}


def _feature(geometry: dict | None, properties: dict) -> dict:
    return {"type": "Feature", "geometry": geometry, "properties": properties}


def _config(root: Path) -> CandidateScoringConfig:
    stage4 = root / "stage4"
    candidates = [
        _feature({"type": "LineString", "coordinates": [[0, 0], [100, 0]]}, {"candidate_id": "CR1", "request_id": "RQ1", "strategy": "shortest_distance", "source_type": "dead_end"}),
        _feature({"type": "LineString", "coordinates": [[0, 0], [50, 20], [100, 0]]}, {"candidate_id": "CR2", "request_id": "RQ1", "strategy": "lowest_land_cost", "source_type": "dead_end"}),
        _feature({"type": "LineString", "coordinates": [[100, 0], [200, 0]]}, {"candidate_id": "CR3", "request_id": "RQ2", "strategy": "shortest_distance", "source_type": "component_connection"}),
    ]
    _write(stage4 / "candidate_roads.geojson", _fc(candidates))
    evaluations = []
    for candidate_id in ("CR1", "CR2", "CR3"):
        crosses_water = candidate_id == "CR3"
        evaluations.append(
            {
                "candidate_id": candidate_id,
                "checks": {
                    "network_connection_valid": True,
                    "crosses_water_length_m": 10 if crosses_water else 0,
                    "crosses_ecological_protection_length_m": 0,
                    "occupies_basic_farmland_length_m": 0,
                    "outside_boundary_length_m": 0,
                    "existing_building_land_intersection_m": 0,
                    "distance_to_nearest_hazard_m": 200,
                },
            }
        )
    _write(stage4 / "candidate_evaluations.json", {"evaluations": evaluations})

    stage3 = root / "stage3"
    demands = [
        _feature({"type": "Point", "coordinates": [0, 0]}, {"demand_id": "D1", "demand_type": "settlement", "population_served": 100}),
        _feature({"type": "Point", "coordinates": [200, 0]}, {"demand_id": "D2", "demand_type": "healthcare", "population_served": 50}),
    ]
    _write(stage3 / "demand_network_binding.geojson", _fc(demands))
    constraints = [
        _feature({"type": "Polygon", "coordinates": [[[145, -10], [155, -10], [155, 10], [145, 10], [145, -10]]]}, {"target_layer": "water"}),
        _feature({"type": "Polygon", "coordinates": [[[300, 300], [310, 300], [310, 310], [300, 310], [300, 300]]]}, {"target_layer": "ecological_protection"}),
    ]
    _write(stage3 / "spatial_constraints.geojson", _fc(constraints))

    nodes_path = root / "stage1" / "road_nodes.geojson"
    edges_path = root / "stage1" / "road_edges.geojson"
    _write(
        nodes_path,
        _fc(
            [
                _feature({"type": "Point", "coordinates": [0, 0]}, {"node_id": "N1"}),
                _feature({"type": "Point", "coordinates": [100, 0]}, {"node_id": "N2"}),
                _feature({"type": "Point", "coordinates": [200, 0]}, {"node_id": "N3"}),
                _feature({"type": "Point", "coordinates": [300, 0]}, {"node_id": "N4"}),
            ]
        ),
    )
    _write(
        edges_path,
        _fc(
            [
                _feature({"type": "LineString", "coordinates": [[0, 0], [100, 0]]}, {"edge_id": "E1", "from_node": "N1", "to_node": "N2"}),
                _feature({"type": "LineString", "coordinates": [[200, 0], [300, 0]]}, {"edge_id": "E2", "from_node": "N3", "to_node": "N4"}),
            ]
        ),
    )
    landuse = root / "landuse.geojson"
    _write(landuse, _fc([_feature({"type": "Polygon", "coordinates": [[[40, -5], [60, -5], [60, 10], [40, 10], [40, -5]]]}, {"DLMC": "耕地"})]))
    return CandidateScoringConfig(
        stage4_dir=stage4,
        stage3_dir=stage3,
        road_nodes_path=nodes_path,
        road_edges_path=edges_path,
        landuse_path=landuse,
        output_dir=root / "output",
        metric_crs="EPSG:4527",
        display_crs="EPSG:4527",
    )


def test_stage5_scores_filters_and_ranks_candidates(tmp_path: Path) -> None:
    result = score_road_candidates(_config(tmp_path))
    assert result.report["candidate_count"] == 3
    assert result.report["indicator_availability"]["slope"] is False
    assert result.report["indicator_availability"]["population_benefit"] is True
    assert result.report["indicator_availability"]["accessibility_benefit"] is True
    assert result.report["recommended_plan_summary"]["recommended_route_count"] == 1
    assert result.report["recommended_plan_summary"]["recommended_segment_count"] == 0
    details = json.loads(result.details_path.read_text(encoding="utf-8"))["candidates"]
    by_id = {item["candidate_id"]: item for item in details}
    assert by_id["CR3"]["eligible"] is False
    assert "prohibited_water_crossing" in by_id["CR3"]["hard_violations"]
    assert by_id["CR1"]["rank_within_request"] in {1, 2}
    assert by_id["CR2"]["rank_within_request"] in {1, 2}
    recommended = json.loads(result.recommended_path.read_text(encoding="utf-8"))["features"]
    assert len(recommended) == 1
    assert recommended[0]["properties"]["request_id"] == "RQ1"


def test_stage5_is_deterministic(tmp_path: Path) -> None:
    config = _config(tmp_path)
    first = score_road_candidates(config)
    paths = [first.scored_candidates_path, first.details_path, first.recommended_path, first.rejected_path, first.preview_path, first.report_path]
    hashes = [hashlib.sha256(path.read_bytes()).hexdigest() for path in paths]
    second = score_road_candidates(config)
    second_paths = [second.scored_candidates_path, second.details_path, second.recommended_path, second.rejected_path, second.preview_path, second.report_path]
    assert hashes == [hashlib.sha256(path.read_bytes()).hexdigest() for path in second_paths]


def test_stage5_rejects_invalid_weights_and_planned_road(tmp_path: Path) -> None:
    config = _config(tmp_path)
    bad_weights = CandidateScoringConfig(
        stage4_dir=config.stage4_dir,
        stage3_dir=config.stage3_dir,
        road_nodes_path=config.road_nodes_path,
        road_edges_path=config.road_edges_path,
        landuse_path=config.landuse_path,
        output_dir=config.output_dir,
        weights={"length": 1.0},
    )
    with pytest.raises(ValueError, match="weight keys mismatch"):
        score_road_candidates(bad_weights)
    planned = tmp_path / "planned" / "road.geojson"
    _write(planned, _fc([]))
    planned_config = CandidateScoringConfig(
        stage4_dir=config.stage4_dir,
        stage3_dir=config.stage3_dir,
        road_nodes_path=config.road_nodes_path,
        road_edges_path=planned,
        landuse_path=config.landuse_path,
        output_dir=config.output_dir,
    )
    with pytest.raises(ValueError, match="planned/evaluation"):
        score_road_candidates(planned_config)
