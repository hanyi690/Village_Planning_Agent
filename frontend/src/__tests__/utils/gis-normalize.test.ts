import { normalizeTileSource } from '@/features/planning/constants/gis';
import {
  normalizeGisLayer,
  normalizeV1MapLayer,
  normalizeV1MapLayers,
} from '@/features/planning/utils/gis-normalize';

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

describe('normalizeV1MapLayer', () => {
  const parcelCollection = {
    type: 'FeatureCollection',
    features: [
      {
        type: 'Feature',
        properties: { DLBM: '030101', DLMC: '水田' },
        geometry: {
          type: 'Polygon',
          coordinates: [[[116.1, 24.3], [116.2, 24.3], [116.2, 24.4], [116.1, 24.3]]],
        },
      },
    ],
  };

  it('maps planned complete_planned_landuse to final_landuse', () => {
    const layer = normalizeV1MapLayer({
      layer_type: 'planned',
      layer_name: 'complete_planned_landuse',
      geojson: parcelCollection,
    });
    expect(layer?.layerType).toBe('final_landuse');
    expect(layer?.metadata?.v1_layer_name).toBe('complete_planned_landuse');
  });

  it('maps current_landuse to final_landuse render vocabulary', () => {
    const layer = normalizeV1MapLayer({
      layer_type: 'current',
      layer_name: 'current_landuse',
      geojson: parcelCollection,
    });
    expect(layer?.layerType).toBe('final_landuse');
  });

  it('maps overlay facility point to facility_point', () => {
    const layer = normalizeV1MapLayer({
      layer_type: 'overlay',
      layer_name: 'planned_facility',
      geojson: {
        type: 'FeatureCollection',
        features: [{
          type: 'Feature',
          properties: { '注记': '停' },
          geometry: { type: 'Point', coordinates: [116.1, 24.3] },
        }],
      },
    });
    expect(layer?.layerType).toBe('facility_point');
  });

  it('maps overlay road to planned_road', () => {
    const layer = normalizeV1MapLayer({
      layer_type: 'overlay',
      layer_name: 'planned_road',
      geojson: {
        type: 'FeatureCollection',
        features: [{
          type: 'Feature',
          properties: {},
          geometry: { type: 'LineString', coordinates: [[116.1, 24.3], [116.2, 24.4]] },
        }],
      },
    });
    expect(layer?.layerType).toBe('planned_road');
  });

  it('returns null for empty feature collections', () => {
    const layer = normalizeV1MapLayer({
      layer_type: 'planned',
      layer_name: 'complete_planned_landuse',
      geojson: { type: 'FeatureCollection', features: [] },
    });
    expect(layer).toBeNull();
  });
});

describe('normalizeV1MapLayers', () => {
  it('orders current → planned → overlay → constraint', () => {
    const layers = normalizeV1MapLayers([
      {
        layer_type: 'overlay',
        layer_name: 'planned_road',
        geojson: {
          type: 'FeatureCollection',
          features: [{ type: 'Feature', properties: {}, geometry: { type: 'Point', coordinates: [0, 0] } }],
        },
      },
      {
        layer_type: 'current',
        layer_name: 'current_landuse',
        geojson: {
          type: 'FeatureCollection',
          features: [{ type: 'Feature', properties: {}, geometry: { type: 'Point', coordinates: [0, 0] } }],
        },
      },
      {
        layer_type: 'planned',
        layer_name: 'complete_planned_landuse',
        geojson: {
          type: 'FeatureCollection',
          features: [{ type: 'Feature', properties: {}, geometry: { type: 'Point', coordinates: [0, 0] } }],
        },
      },
    ]);
    expect(layers.map((l) => l.metadata?.v1_layer_type)).toEqual(['current', 'planned', 'overlay']);
  });
});
