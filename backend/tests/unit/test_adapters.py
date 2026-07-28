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