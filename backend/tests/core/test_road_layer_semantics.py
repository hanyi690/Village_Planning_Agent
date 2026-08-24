from __future__ import annotations

from app.data.model.canonical import VillageBundle
from app.data.model.snapshot import SessionDataSnapshot
from app.infrastructure.export.delivery_snapshot import (
    build_delivery_spatial_snapshot_from_gis_data,
)


def _line(identifier: str) -> dict:
    return {
        "type": "Feature",
        "geometry": {
            "type": "LineString",
            "coordinates": [[114.0, 22.0], [114.001, 22.001]],
        },
        "properties": {"source_feature_id": identifier},
    }


def _landuse() -> dict:
    return {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[114.0, 22.0], [114.001, 22.0],
                                  [114.001, 22.001], [114.0, 22.0]]],
            },
            "properties": {"BSM": "parcel-1"},
        }],
    }


def test_bundle_and_manifest_keep_current_and_planned_roads_separate() -> None:
    bundle = VillageBundle(village_name="测试村")
    bundle.lines._layers = {
        "roads_current": [_line("current-1")],
        "roads_planned": [_line("planned-1"), _line("planned-2")],
    }

    payload = bundle.to_geojson_dict()
    assert len(payload["road_geojson"]["features"]) == 1
    assert len(payload["planned_road_geojson"]["features"]) == 2

    snapshot = SessionDataSnapshot.from_bundle(bundle, session_id="road-semantics")
    assert snapshot.collection("road_geojson").source_feature_count == 1
    assert snapshot.collection("planned_road_geojson").source_feature_count == 2


def test_delivery_snapshot_classifies_planned_roads_as_overlay(tmp_path) -> None:
    snapshot = build_delivery_spatial_snapshot_from_gis_data(
        {
            "landuse_current_geojson": _landuse(),
            "road_geojson": {"type": "FeatureCollection", "features": [_line("current-1")]},
            "planned_road_geojson": {
                "type": "FeatureCollection",
                "features": [_line("planned-1"), _line("planned-2")],
            },
        },
        output_dir=tmp_path,
    )

    assert "road_geojson" in snapshot.current_layers
    assert "planned_road_geojson" not in snapshot.current_layers
    assert "planned_road_geojson" in snapshot.planned_overlay_layers
