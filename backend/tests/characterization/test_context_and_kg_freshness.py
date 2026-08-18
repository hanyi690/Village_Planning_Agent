from __future__ import annotations

from types import SimpleNamespace

from app.data.model.snapshot import SessionDataSnapshot
from app.infrastructure.kg.manager import compute_layer1_cache_key


def _parcel() -> SimpleNamespace:
    return SimpleNamespace(bsm="P-1", dlbm="0101", area_sqm=100.0)


def _bundle(annotation_x: float) -> SimpleNamespace:
    return SimpleNamespace(
        village_name="demo",
        to_geojson_dict=lambda: {
            "landuse_current_geojson": {
                "type": "FeatureCollection",
                "features": [{
                    "type": "Feature",
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]],
                    },
                    "properties": {"BSM": "P-1"},
                }],
            },
            "annotation_geojson": {
                "type": "FeatureCollection",
                "features": [{
                    "type": "Feature",
                    "geometry": {
                        "type": "Point",
                        "coordinates": [annotation_x, 1.0],
                    },
                    "properties": {
                        "_raw": {
                            "source_feature_id": f"source:{annotation_x}",
                            "source_content_digest": "sha256:source",
                        },
                    },
                }],
            },
        },
        polygons=SimpleNamespace(get=lambda key: [_parcel()] if key == "landuse_current" else []),
    )


def test_bundle_layer1_cache_key_changes_when_source_geometry_changes() -> None:
    first = _bundle(116.0)
    second = _bundle(116.1)
    first_key = compute_layer1_cache_key(
        "demo", [_parcel()], bundle=first
    )
    second_key = compute_layer1_cache_key(
        "demo", [_parcel()], bundle=second
    )
    assert first_key is not None
    assert second_key is not None
    assert first_key != second_key
    # The compatibility form remains parcel-only and therefore cannot prove
    # that source-backed point/line geometry is current.
    assert compute_layer1_cache_key("demo", [_parcel()]) == compute_layer1_cache_key(
        "demo", [_parcel()]
    )


def test_data_snapshot_records_source_feature_manifest() -> None:
    snapshot = SessionDataSnapshot.from_bundle(
        _bundle(116.0),
        session_id="s1",
    )
    annotation = snapshot.collection("annotation_geojson")
    assert annotation is not None
    assert annotation.source_feature_count == 1
    assert annotation.source_feature_digest.startswith("sha256:")
    assert snapshot.digest.startswith("sha256:")

