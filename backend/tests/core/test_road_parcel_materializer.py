from __future__ import annotations

from shapely.geometry import Polygon, mapping

from app.domain.materialization.road_parcel_materializer import (
    materialize_road_parcel_changes,
)


def _landuse() -> dict:
    return {
        "type": "FeatureCollection",
        "crs": {"type": "name", "properties": {"name": "EPSG:4326"}},
        "features": [{
            "type": "Feature",
            "geometry": mapping(Polygon([
                (116.000, 24.800),
                (116.010, 24.800),
                (116.010, 24.810),
                (116.000, 24.810),
                (116.000, 24.800),
            ])),
            "properties": {"BSM": "P-1", "DLBM": "0101"},
        }],
    }


def _line_layer() -> list[dict]:
    return [{
        "layerType": "planned_road",
        "data": {
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": [
                        [116.001, 24.805],
                        [116.009, 24.805],
                    ],
                },
                "properties": {
                    "target_id": "road-1",
                    "road_level": "village_road",
                    "roadbed_width_m": 8,
                    "feature_id": "planned-road-1",
                },
            }],
        },
    }]


def test_new_road_materializes_line_corridor_as_transport_land_and_preserves_remainder():
    changes, diagnostics = materialize_road_parcel_changes(
        target={"target_id": "road-1", "road_level": "village_road"},
        layers=_line_layer(),
        landuse_payload=_landuse(),
        target_id="road-1",
        evidence_refs=["evidence:road-1"],
    )

    assert diagnostics == []
    assert len(changes) == 2
    road_change = next(item for item in changes if ":road:" in item.bsm)
    remainder = next(item for item in changes if ":remainder:" in item.bsm)
    assert road_change.after_classification is not None
    assert road_change.after_classification.code == "1006"
    assert road_change.action == "split"
    assert remainder.after_classification is not None
    assert remainder.after_classification.code == "0101"
    assert road_change.new_area_ha > 0
    assert remainder.new_area_ha > 0
    assert 110.0 < road_change.new_area_ha + remainder.new_area_ha < 116.0


def test_new_road_fails_closed_when_width_is_not_typed():
    layers = _line_layer()
    layers[0]["data"]["features"][0]["properties"].pop("roadbed_width_m")
    changes, diagnostics = materialize_road_parcel_changes(
        target={"target_id": "road-1", "road_level": "village_road"},
        layers=layers,
        landuse_payload=_landuse(),
        target_id="road-1",
    )

    assert changes == []
    assert diagnostics[0]["code"] == "road_width_missing"
