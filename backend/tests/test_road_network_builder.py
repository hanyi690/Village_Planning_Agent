"""Acceptance tests for Stage-1 deterministic road-network construction."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import geopandas as gpd
import pytest
from shapely.geometry import LineString

from app.services.modules.gis.road.network_builder import RoadNetworkBuilder
from app.services.modules.gis.road.schemas import NetworkBuildConfig


def _gdf(lines: list[LineString]) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {"Shape_Length": [999999.0] * len(lines)},
        geometry=lines,
        crs="EPSG:4527",
    )


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _config(**overrides: object) -> NetworkBuildConfig:
    values = {
        "metric_crs": "EPSG:4527",
        "snap_tolerance_m": 1.0,
        "tolerance_scenarios_m": (1.0, 3.0, 5.0),
        "min_source_length_m": 0.5,
        "min_edge_length_m": 0.05,
    }
    values.update(overrides)
    return NetworkBuildConfig(**values)


def test_crossing_lines_are_noded_and_edge_references_are_valid(tmp_path: Path) -> None:
    roads = _gdf([
        LineString([(0, 0), (10, 0)]),
        LineString([(5, -5), (5, 5)]),
    ])

    result = RoadNetworkBuilder(_config()).build(roads, tmp_path)
    report = result.report
    nodes = json.loads(result.nodes_path.read_text(encoding="utf-8"))
    edges = json.loads(result.edges_path.read_text(encoding="utf-8"))

    assert report["node_count"] == 5
    assert report["clean_edge_count"] == 4
    assert report["connected_component_count"] == 1
    assert report["intersection_node_count"] == 1
    assert report["validation"]["status"] == "pass"
    node_ids = {feature["properties"]["node_id"] for feature in nodes["features"]}
    for feature in edges["features"]:
        properties = feature["properties"]
        assert properties["from_node"] in node_ids
        assert properties["to_node"] in node_ids
        assert properties["from_node"] != properties["to_node"]
        assert properties["length_m"] == pytest.approx(5.0)


def test_near_endpoints_snap_only_when_within_selected_tolerance(tmp_path: Path) -> None:
    roads = _gdf([
        LineString([(0, 0), (10, 0)]),
        LineString([(10.6, 0), (20, 0)]),
    ])

    snapped = RoadNetworkBuilder(_config()).build(roads, tmp_path / "snapped")
    unsnapped = RoadNetworkBuilder(_config(
        snap_tolerance_m=0.5,
        tolerance_scenarios_m=(0.5, 1.0),
    )).build(roads, tmp_path / "unsnapped")

    assert snapped.report["connected_component_count"] == 1
    assert snapped.report["node_count"] == 3
    assert snapped.report["tolerance_scenarios"]["1m"]["snap"]["merged_cluster_count"] == 1
    assert unsnapped.report["connected_component_count"] == 2
    assert unsnapped.report["node_count"] == 4


def test_reverse_duplicate_and_short_source_line_are_removed(tmp_path: Path) -> None:
    roads = _gdf([
        LineString([(0, 0), (10, 0)]),
        LineString([(10, 0), (0, 0)]),
        LineString([(20, 0), (20.2, 0)]),
    ])

    result = RoadNetworkBuilder(_config()).build(roads, tmp_path)

    assert result.report["source_feature_count"] == 3
    assert result.report["duplicate_removed"] == 1
    assert result.report["short_edge_removed"] == 1
    assert result.report["clean_edge_count"] == 1
    assert result.report["selected_topology"]["duplicate_remaining"] == 0
    assert result.report["selected_topology"]["invalid_geometry_remaining"] == 0


def test_original_shape_length_is_ignored_and_metric_length_recomputed(tmp_path: Path) -> None:
    roads = _gdf([LineString([(0, 0), (12.5, 0)])])

    result = RoadNetworkBuilder(_config()).build(roads, tmp_path)
    edges = json.loads(result.edges_path.read_text(encoding="utf-8"))

    assert result.report["total_length_m"] == pytest.approx(12.5)
    assert edges["features"][0]["properties"]["length_m"] == pytest.approx(12.5)
    assert any("Shape_Length" in warning for warning in result.report["warnings"])


def test_same_input_and_parameters_produce_byte_identical_outputs(tmp_path: Path) -> None:
    roads = _gdf([
        LineString([(0, 0), (10, 0)]),
        LineString([(5, -5), (5, 5)]),
        LineString([(10.4, 0), (15, 0)]),
    ])
    builder = RoadNetworkBuilder(_config())

    first = builder.build(roads, tmp_path / "first")
    second = builder.build(roads, tmp_path / "second")

    for name in (
        "road_nodes.geojson",
        "road_edges.geojson",
        "road_network_report.json",
        "road_network_preview.geojson",
    ):
        assert _hash(first.output_dir / name) == _hash(second.output_dir / name)


def test_planned_road_path_is_rejected_by_default(tmp_path: Path) -> None:
    planned_dir = tmp_path / "planned"
    planned_dir.mkdir()
    path = planned_dir / "road.geojson"
    _gdf([LineString([(0, 0), (10, 0)])]).to_file(path, driver="GeoJSON")

    with pytest.raises(ValueError, match="evaluation-only"):
        RoadNetworkBuilder(_config()).build(path, tmp_path / "output")
