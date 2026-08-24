"""Read-only catalog projection for the current GIS context."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from app.api.v1.contracts import (
    CurrentSourceLayer,
    CurrentSourceLayerCollection,
    CurrentSourceRaster,
)
from app.data.catalog.catalog import DataCatalog


router = APIRouter(prefix='/api/v1', tags=['Stable v1'])


_CURRENT_VECTOR_SOURCES: tuple[tuple[str, str, str, str, str], ...] = (
    ('jintian_boundary', 'boundary', 'boundary', '村域边界', 'boundary'),
    ('jintian_current_landuse', 'function_zone', 'landuse_current', '现状地块', 'current_landuse'),
    ('jintian_road', 'infrastructure', 'current_road', '现状道路', 'current_road'),
    ('jintian_admin_boundary_line', 'boundary', 'admin_boundary_line', '行政边界线', 'admin_boundary'),
    ('jintian_annotation', 'facility_point', 'current_annotation', '现状注记点', 'current_annotation'),
    ('jintian_farmland_protection', 'construction_control', 'farmland_protection', '永久基本农田', 'farmland_protection'),
    ('jintian_ecological_protection', 'sensitivity_zone', 'ecological_protection', '生态保护区', 'ecological_protection'),
    ('jintian_historical_protection', 'sensitivity_zone', 'historical_protection', '历史保护区', 'historical_protection'),
    ('jintian_construction_zone', 'construction_control', 'conditional_construction_zone', '建设控制区', 'construction_zone'),
    ('jintian_geological_hazard', 'hazard_point', 'geological_hazard_point', '地质灾害点', 'geological_hazard'),
)


def _is_jintian_reference(village_name: str) -> bool:
    normalized = str(village_name or '').strip().lower()
    return normalized in {'金田', '金田村', 'jintian'}


def _feature_count(geojson: dict[str, Any]) -> int:
    features = geojson.get('features')
    return len(features) if isinstance(features, list) else 0


def _geojson_center(geojson: dict[str, Any]) -> list[float] | None:
    """Return a center from the first boundary geometry without GIS mutation."""

    points: list[tuple[float, float]] = []

    def collect(value: Any) -> None:
        if isinstance(value, list) and len(value) >= 2:
            try:
                first, second = float(value[0]), float(value[1])
            except (TypeError, ValueError):
                first = second = None
            if (
                first is not None
                and second is not None
                and -180 <= first <= 180
                and -90 <= second <= 90
            ):
                points.append((first, second))
                return
        if isinstance(value, list):
            for child in value:
                collect(child)

    features = geojson.get('features')
    if not isinstance(features, list):
        return None
    for feature in features:
        if not isinstance(feature, dict):
            continue
        geometry = feature.get('geometry')
        if isinstance(geometry, dict):
            collect(geometry.get('coordinates'))
    if not points:
        return None
    return [sum(point[0] for point in points) / len(points), sum(point[1] for point in points) / len(points)]


def _raster_manifest(catalog: DataCatalog, source_name: str, layer_type: str) -> CurrentSourceRaster:
    try:
        result = catalog.get_source(source_name).fetch()
    except KeyError as exc:
        return CurrentSourceRaster(
            source_name=source_name,
            layer_name='数字高程模型' if layer_type == 'dem' else '数字正射影像',
            layer_type=layer_type,
            source_ref=f'catalog://{source_name}',
            reason=str(exc),
        )
    metadata = result.metadata if result.success else {}
    raw_bounds = metadata.get('bounds')
    bounds = {
        key: float(raw_bounds[key])
        for key in ('west', 'south', 'east', 'north')
        if isinstance(raw_bounds, dict) and isinstance(raw_bounds.get(key), (int, float))
    }
    return CurrentSourceRaster(
        source_name=source_name,
        layer_name='数字高程模型' if layer_type == 'dem' else '数字正射影像',
        layer_type=layer_type,
        format=str(metadata.get('format') or ''),
        crs=str(metadata.get('crs') or ''),
        available=bool(result.success),
        resolution=float(metadata['resolution']) if isinstance(metadata.get('resolution'), (int, float)) else None,
        width=int(metadata['width']) if isinstance(metadata.get('width'), int) else None,
        height=int(metadata['height']) if isinstance(metadata.get('height'), int) else None,
        bands=int(metadata['bands']) if isinstance(metadata.get('bands'), int) else None,
        dtype=str(metadata.get('dtype') or ''),
        bounds=bounds,
        source_ref=f'catalog://{source_name}',
        reason='' if result.success else str(result.error or '栅格源不可用'),
    )


@router.get('/source-layers', response_model=CurrentSourceLayerCollection)
def get_current_source_layers(
    village_name: str = Query(default='金田村', min_length=1),
) -> CurrentSourceLayerCollection:
    """Expose configured current vectors and raster manifests.

    This is context data, not planning output. DELIVER remains the only source
    for generated/planned layers.
    """

    if not _is_jintian_reference(village_name):
        return CurrentSourceLayerCollection(
            village_name=village_name,
            center=None,
            layers=[],
            rasters=[],
            diagnostics=[
                f'no catalog-backed current spatial source is configured for village {village_name!r}'
            ],
        )

    catalog = DataCatalog()
    layers: list[CurrentSourceLayer] = []
    diagnostics: list[str] = []
    center: list[float] | None = None

    for source_name, layer_type, source_layer_type, layer_name, display_role in _CURRENT_VECTOR_SOURCES:
        try:
            result = catalog.get_source(source_name).fetch()
        except KeyError as exc:
            diagnostics.append(f'{source_name}: {exc}')
            continue
        if not result.success or not isinstance(result.data, dict):
            diagnostics.append(f'{source_name}: {result.error or "数据源不可用"}')
            continue
        geojson = result.data
        if geojson.get('type') != 'FeatureCollection':
            diagnostics.append(f'{source_name}: 返回内容不是 FeatureCollection')
            continue
        if source_name == 'jintian_boundary':
            center = _geojson_center(geojson)
        count = _feature_count(geojson)
        layers.append(CurrentSourceLayer(
            source_name=source_name,
            source_layer_type=source_layer_type,
            layer_type=layer_type,
            layer_name=layer_name,
            display_role=display_role,
            crs='EPSG:4326',
            feature_count=count,
            geojson=geojson,
            metadata={
                'path': f'catalog://{source_name}/current',
                'sourceRef': f'catalog://{source_name}',
                'displayRole': display_role,
                'featureCount': count,
                'villageName': village_name,
            },
        ))

    rasters = [_raster_manifest(catalog, 'dem_local', 'dem')]
    return CurrentSourceLayerCollection(
        village_name=village_name,
        center=center,
        layers=layers,
        rasters=rasters,
        diagnostics=diagnostics,
    )
