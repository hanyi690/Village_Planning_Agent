"""Contract coverage for the catalog-backed current GIS projection."""

from __future__ import annotations

from app.api.v1.routes.source_layers import get_current_source_layers


def test_current_source_layers_expose_real_vectors_and_dem() -> None:
    response = get_current_source_layers('金田村')
    counts = {layer.layer_name: layer.feature_count for layer in response.layers}

    assert counts == {
        '村域边界': 1,
        '现状地块': 660,
        '现状道路': 131,
        '行政边界线': 561,
        '现状注记点': 34,
        '永久基本农田': 88,
        '生态保护区': 5,
        '历史保护区': 3,
        '建设控制区': 139,
        '地质灾害点': 40,
    }
    assert response.source == 'data_catalog'
    assert response.center is not None
    assert 115 < response.center[0] < 117
    assert 23 < response.center[1] < 26
    assert response.rasters[0].layer_type == 'dem'
    assert response.rasters[0].available is True
    assert response.rasters[0].width == 3601
    assert response.rasters[0].height == 3601
    assert response.rasters[0].source_ref == 'catalog://dem_local'
    assert 'path' not in response.rasters[0].model_dump()
