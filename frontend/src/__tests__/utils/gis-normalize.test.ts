import { normalizeTileSource } from '@/features/planning/constants/gis';
import { normalizeGisLayer } from '@/features/planning/utils/gis-normalize';

const pointCollection = {
  type: 'FeatureCollection',
  features: [
    {
      type: 'Feature',
      properties: { hazard_scale: '中型', color: '#ef4444' },
      geometry: { type: 'Point', coordinates: [116.12, 24.31] },
    },
  ],
};

describe('normalizeTileSource', () => {
  it('defaults to amap and normalizes common aliases', () => {
    expect(normalizeTileSource()).toBe('amap');
    expect(normalizeTileSource('gaode')).toBe('amap');
    expect(normalizeTileSource('openstreetmap')).toBe('osm');
    expect(normalizeTileSource('osm')).toBe('osm');
    expect(normalizeTileSource('geoq')).toBe('geoq');
  });
});

describe('normalizeGisLayer', () => {
  it('preserves standard metadata and recognizes hazard layers', () => {
    const layer = normalizeGisLayer({
      geojson: pointCollection,
      layerType: 'hazard_point',
      layerName: 'geological_hazard_points',
      standardCode: 'DZZHD',
      standardName: '地质灾害点',
      dataAuthority: 'reference',
      requirement: 'conditional',
      featureCount: 1,
      crs: 'EPSG:4326',
      metadata: {
        planningBasis: { report_count: 28, source_layers: [1, 2, 3] },
        dataQuality: { status: 'ready' },
      },
    });

    expect(layer).toMatchObject({
      layerType: 'hazard_point',
      standardCode: 'DZZHD',
      standardName: '地质灾害点',
      dataAuthority: 'reference',
      requirement: 'conditional',
      featureCount: 1,
      crs: 'EPSG:4326',
      metadata: {
        planningBasis: { report_count: 28, source_layers: [1, 2, 3] },
        dataQuality: { status: 'ready' },
      },
    });
  });

  it('infers hazard points from historical layer names', () => {
    const layer = normalizeGisLayer({
      geojson: pointCollection,
      layerName: '地质灾害风险点',
    });

    expect(layer?.layerType).toBe('hazard_point');
  });

  it('keeps the planned-road contract and its visibility metadata', () => {
    const layer = normalizeGisLayer({
      geojson: {
        type: 'FeatureCollection',
        features: [{
          type: 'Feature',
          properties: { construction_action: 'new', action_label: '规划新建' },
          geometry: { type: 'LineString', coordinates: [[116.1, 24.3], [116.2, 24.4]] },
        }],
      },
      layerType: 'planned_road',
      layerName: '规划道路推荐方案',
      visible: false,
      metadata: { generationStage: 'stage5_candidate_scoring' },
    });

    expect(layer).toMatchObject({
      layerType: 'planned_road',
      visible: false,
      metadata: { generationStage: 'stage5_candidate_scoring' },
    });
  });

  it('maps the backend custom-zone alias to the frontend function zone', () => {
    const layer = normalizeGisLayer({
      geojson: pointCollection,
      layerType: 'custom_functional_zone',
      layerName: '自定义功能区',
    });
    expect(layer?.layerType).toBe('function_zone');
  });

  it('replaces cartographic facility symbols with complete frontend labels', () => {
    const layer = normalizeGisLayer({
      geojson: {
        type: 'FeatureCollection',
        features: [{
          type: 'Feature',
          properties: { '注记': '停', '分类': '规划设施点' },
          geometry: { type: 'Point', coordinates: [116.1, 24.3] },
        }],
      },
      layerType: 'facility',
      layerName: '规划设施',
    });

    expect(layer?.layerType).toBe('facility_point');
    expect(layer?.geojson.features[0].properties).toMatchObject({
      annotation_symbol: '停',
      facility_type: '停车场',
      facility_name: '规划停车场',
      label: '规划停车场',
    });
  });
});
