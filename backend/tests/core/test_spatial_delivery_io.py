"""Unit coverage for bounded spatial reads and delivery snapshot materialization."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.modules.schema.contracts.parcel_change_contracts import ParcelChange
from app.modules.schema.contracts.spatial_delivery_contracts import (
    SpatialLayerRef,
    SpatialReadRequest,
)
from app.modules.spatial_ops.io import (
    GeoJSONSpatialDataPort,
    PyogrioSpatialDataPort,
    build_delivery_spatial_snapshot,
    build_delivery_spatial_snapshot_from_gis_data,
    load_complete_planned_geojson,
)


def _write_layer(path: Path) -> SpatialLayerRef:
    payload = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "id": 0,
                "properties": {"BSM": "P001", "DLBM": "0101", "name": "north"},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]],
                },
            },
            {
                "type": "Feature",
                "id": 1,
                "properties": {"BSM": "P002", "DLBM": "0702", "name": "south"},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[10, 10], [11, 10], [11, 11], [10, 11], [10, 10]]],
                },
            },
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return SpatialLayerRef(artifact_ref="current-landuse", path=str(path), layer_name="layer")


def test_spatial_contracts_reject_unbounded_requests() -> None:
    ref = SpatialLayerRef(artifact_ref="a", path="layer.geojson", layer_name="layer")
    with pytest.raises(ValueError):
        SpatialLayerRef(artifact_ref="a", path="layer.geojson", layer_name="layer", feature_count=-1)
    with pytest.raises(ValueError):
        SpatialReadRequest(layer_ref=ref, bbox=(0, 0, 1, 1), mask={"type": "Polygon"})
    with pytest.raises(ValueError):
        SpatialReadRequest(layer_ref=ref, fids=[-1])
    with pytest.raises(ValueError):
        SpatialReadRequest.model_validate({"layer_ref": ref.model_dump(), "unexpected": True})


def test_pyogrio_reads_metadata_and_only_requested_features(tmp_path: Path) -> None:
    ref = _write_layer(tmp_path / "layer.geojson")
    port = PyogrioSpatialDataPort()

    described = port.describe(ref)
    assert described.feature_count == 2
    assert described.fields == ["BSM", "DLBM", "name"]
    assert described.bbox == (0.0, 0.0, 11.0, 11.0)

    batch = port.read(
        SpatialReadRequest(
            layer_ref=described,
            bsms=["P002"],
            columns=["BSM", "DLBM"],
            read_geometry=False,
        )
    )
    assert batch.feature_count == 1
    assert batch.features[0]["properties"] == {"BSM": "P002", "DLBM": "0702"}
    assert "geometry" not in batch.features[0]
    assert batch.complete is False


def test_geojson_fallback_applies_bbox_and_where(tmp_path: Path) -> None:
    ref = _write_layer(tmp_path / "layer.geojson")
    port = PyogrioSpatialDataPort(prefer_pyogrio=False)

    batch = port.read(
        SpatialReadRequest(
            layer_ref=ref,
            columns=["BSM", "DLBM"],
            bbox=(9, 9, 12, 12),
            where="DLBM = '0702'",
            read_geometry=False,
        )
    )
    assert batch.feature_count == 1
    assert batch.features[0]["properties"] == {"BSM": "P002", "DLBM": "0702"}


def test_geojson_fallback_is_used_when_arrow_read_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ref = _write_layer(tmp_path / "layer.geojson")
    import pyogrio

    def fail_read(*args, **kwargs):
        raise RuntimeError("arrow unavailable")

    monkeypatch.setattr(pyogrio, "read_dataframe", fail_read)
    batch = PyogrioSpatialDataPort().read_by_bsms(ref, ["P001"], ["BSM"])
    assert batch.feature_count == 1
    assert batch.features[0]["properties"] == {"BSM": "P001"}


def test_delivery_snapshot_preserves_unmodified_features_and_is_checksummed(tmp_path: Path) -> None:
    ref = _write_layer(tmp_path / "current.geojson")
    output = tmp_path / "planned.geojson"
    snapshot = build_delivery_spatial_snapshot(
        ref,
        [
            ParcelChange(
                bsm="P001",
                action="reclassify",
            )
        ],
        data_port=GeoJSONSpatialDataPort(),
        output_path=output,
        provenance={"session_id": "test-session"},
    )

    assert snapshot.delivery_status == "complete"
    assert snapshot.complete_planned_landuse is not None
    assert snapshot.complete_planned_landuse.feature_count == 2
    assert snapshot.change_summary["preserved"] == 1
    assert snapshot.change_summary["modified"] == 1
    assert snapshot.checksum
    assert output.exists()

    payload = json.loads(output.read_text(encoding="utf-8"))
    by_bsm = {feature["properties"]["BSM"]: feature for feature in payload["features"]}
    assert by_bsm["P001"]["properties"]["change_status"] == "modified"
    assert by_bsm["P002"]["properties"]["change_status"] == "preserved"
    assert by_bsm["P002"]["geometry"]["coordinates"] == [[[10, 10], [11, 10], [11, 11], [10, 11], [10, 10]]]


def test_gis_data_delivery_integration_writes_and_reloads_complete_artifact(tmp_path: Path) -> None:
    current = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"BSM": "P001"},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]],
                },
            },
            {
                "type": "Feature",
                "properties": {"BSM": "P002"},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[10, 10], [11, 10], [11, 11], [10, 11], [10, 10]]],
                },
            },
        ],
    }
    planned = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"BSM": "P001", "change_status": "modified"},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]],
                },
            }
        ],
    }
    snapshot = build_delivery_spatial_snapshot_from_gis_data(
        {"landuse_current_geojson": current, "boundary_geojson": current},
        planned_geojson=planned,
        output_dir=tmp_path,
    )

    complete = load_complete_planned_geojson(snapshot)
    by_bsm = {feature["properties"]["BSM"]: feature for feature in complete["features"]}
    assert snapshot.complete_planned_landuse is not None
    assert snapshot.complete_planned_landuse.checksum
    assert len(complete["features"]) == 2
    assert by_bsm["P001"]["properties"]["change_status"] == "modified"
    assert by_bsm["P002"]["properties"]["change_status"] == "preserved"
