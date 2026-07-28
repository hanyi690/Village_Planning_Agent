from __future__ import annotations

from typing import Any, Dict

import pytest

from app.modules.data.adapters import (
    ADAPTERS,
    AdapterResult,
    IngestAdapter,
    register_adapter,
)
from app.modules.schema.types.layer_registry import GisLayerTypeEntry, IngestSpec


def test_adapter_result_defaults():
    result = AdapterResult()
    assert result.features == []
    assert result.warnings == []
    assert result.dlq == []


def test_adapter_result_with_data():
    result = AdapterResult(
        features=["f1", "f2"],
        warnings=["w1"],
        dlq=[{"bsm": "123"}],
    )
    assert len(result.features) == 2
    assert len(result.warnings) == 1
    assert len(result.dlq) == 1


def test_register_adapter():
    class FakeAdapter(IngestAdapter):
        def load(self, data: dict, entry: GisLayerTypeEntry, *, strict: bool = False) -> AdapterResult:
            return AdapterResult(features=[data.get("msg", "ok")])

    register_adapter("test_fake", FakeAdapter())
    assert "test_fake" in ADAPTERS
    entry = GisLayerTypeEntry(gis_type_ref="test", ingest=IngestSpec(adapter="test_fake"))
    result = ADAPTERS["test_fake"].load({"msg": "hello"}, entry)
    assert result.features == ["hello"]
    ADAPTERS.pop("test_fake", None)


def test_ingest_adapter_is_protocol():
    import inspect
    assert inspect.isclass(IngestAdapter)


def test_parcels_adapter_registered():
    from app.modules.data.adapters import ADAPTERS
    assert "parcels" in ADAPTERS


def test_features_adapter_registered():
    from app.modules.data.adapters import ADAPTERS
    assert "features" in ADAPTERS


def test_parcels_adapter_current_landuse():
    from app.modules.data.adapters import ADAPTERS
    from app.modules.schema.types.layer_registry import GisLayerTypeEntry, IngestSpec

    adapter = ADAPTERS["parcels"]
    geojson = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]},
                "properties": {"BSM": "001", "DLBM": "0703", "DLMC": "宅基地"},
            }
        ],
    }
    entry = GisLayerTypeEntry(
        gis_type_ref="landuse_current",
        ingest=IngestSpec(adapter="parcels", feature_type="current_landuse"),
    )
    result = adapter.load(geojson, entry)
    assert len(result.features) >= 1
    p = result.features[0]
    assert p.bsm == "001"
    assert p.layer_type == "landuse_current"


def test_raster_adapter_registered():
    from app.modules.data.adapters import ADAPTERS
    assert "raster" in ADAPTERS


def test_table_adapter_registered():
    from app.modules.data.adapters import ADAPTERS
    assert "table" in ADAPTERS


def test_document_adapter_registered():
    from app.modules.data.adapters import ADAPTERS
    assert "document" in ADAPTERS


def test_table_adapter_returns_empty():
    from app.modules.data.adapters import ADAPTERS
    from app.modules.schema.types.layer_registry import GisLayerTypeEntry

    adapter = ADAPTERS["table"]
    entry = GisLayerTypeEntry(gis_type_ref="population")
    result = adapter.load({}, entry)
    assert result.features == []
    assert result.warnings == []


def test_document_adapter_returns_empty():
    from app.modules.data.adapters import ADAPTERS
    from app.modules.schema.types.layer_registry import GisLayerTypeEntry

    adapter = ADAPTERS["document"]
    entry = GisLayerTypeEntry(gis_type_ref="planning_text")
    result = adapter.load({}, entry)
    assert result.features == []
    assert result.warnings == []


def test_features_adapter_admin_area():
    from app.modules.data.adapters import ADAPTERS
    from app.modules.schema.types.layer_registry import GisLayerTypeEntry, IngestSpec

    adapter = ADAPTERS["features"]
    geojson = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]},
                "properties": {"BSM": "A001", "NAME": "金田村"},
            }
        ],
    }
    entry = GisLayerTypeEntry(
        gis_type_ref="admin_area",
        ingest=IngestSpec(adapter="features", feature_type="admin_area"),
    )
    result = adapter.load(geojson, entry)
    assert len(result.features) >= 1
    f = result.features[0]
    assert f.bsm == "A001"
    assert f.layer_type == "admin_area"