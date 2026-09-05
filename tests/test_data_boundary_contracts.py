from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]


def test_data_exports_provider_acquisition_contract_only():
    import app.contracts.data as data_contracts

    from app.contracts.data import (
        ProviderAcquisitionPlan,
        build_provider_acquisition_plan,
    )

    assert ProviderAcquisitionPlan.__name__ == "ProviderAcquisitionPlan"
    assert callable(build_provider_acquisition_plan)
    assert not hasattr(data_contracts, "ProviderQueryPlan")


@pytest.mark.parametrize(
    "relative",
    (
        "scripts/collect_amap_jintian_validation.py",
        "scripts/collect_three_provider_validation.py",
        "scripts/collect_tianditu_full.py",
    ),
)
def test_provider_collectors_use_data_acquisition_naming(relative: str):
    source = (ROOT / relative).read_text(encoding="utf-8")

    assert "provider_acquisition_plans" in source
    assert "provider_query_plans" not in source
    assert "provider_acquisition_plan" in source
    assert "provider_query_plan" not in source


def test_source_layers_projection_consumes_admitted_catalog_without_fixed_sources():
    from app.api.v1.routes.source_layers import _catalog_projection

    polygon = SimpleNamespace(
        dataset_ref="upload:session:boundary",
        source_feature_ref="feature-1",
        layer_ref="boundary-layer",
        geometry_kind="polygon",
        normalized_geometry_kind="polygon",
        normalized_geometry={
            "type": "MultiPolygon",
            "coordinates": [[[
                [116.0, 24.0],
                [116.001, 24.0],
                [116.001, 24.001],
                [116.0, 24.0],
            ]]],
        },
        raw_attributes={"arbitrary_field": "kept"},
        source_feature_digest="sha256:feature",
    )
    collection = SimpleNamespace(
        dataset_ref="upload:session:boundary",
        source_feature_ref="feature-2",
        layer_ref="mixed-layer",
        geometry_kind="collection",
        normalized_geometry_kind="collection",
        normalized_geometry={"type": "GeometryCollection", "geometries": []},
        geometry={"type": "GeometryCollection", "geometries": []},
        raw_attributes={},
        source_feature_digest="sha256:collection",
    )
    result = _catalog_projection(
        SimpleNamespace(features=(polygon, collection))
    )

    assert len(result.layers) == 1
    assert result.layers[0].source_layer_type == "boundary-layer"
    assert result.layers[0].geojson["features"][0]["properties"]["arbitrary_field"] == "kept"
    assert result.layers[0].geojson["features"][0]["properties"]["geometry_authority"] == "data_resource_catalog"
    assert result.diagnostics == [
        "1 read-only or non-executable feature(s) omitted from map projection"
    ]
