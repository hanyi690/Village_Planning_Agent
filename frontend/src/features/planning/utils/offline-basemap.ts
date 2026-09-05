import { classifyLanduseZone } from '@/features/planning/constants/gis';
import { normalizeGisLayers } from '@/features/planning/utils/gis-normalize';
import type { GISLayerConfig, GeoJsonFeatureCollection } from '@/types/message/message-types';
import { planningApi } from '@/features/planning/api';
import type { CurrentSourceRaster } from '@/features/planning/api/types';

const cachedSources = new Map<string, CurrentSourceLayersResult>();
const pendingSources = new Map<string, Promise<CurrentSourceLayersResult>>();

export interface CurrentSourceLayersResult {
  layers: GISLayerConfig[];
  center: [number, number] | null;
  rasters: CurrentSourceRaster[];
  diagnostics: string[];
}

const OFFLINE_LANDUSE_COLORS: Record<string, { color: string; stroke: string }> = {
  农业用地: { color: '#D9C84A', stroke: '#7A6A28' },
  生态用地: { color: '#4CAF50', stroke: '#2E7D32' },
  村庄建设用地: { color: '#EF8D7B', stroke: '#B84D3D' },
  交通与水利用地: { color: '#5DA9E9', stroke: '#2B6CB0' },
};

const OFFLINE_LANDUSE_DEFAULT = { color: '#A8B4C2', stroke: '#5C6B7A' };

const OFFLINE_LANDUSE_LAYER_NAMES = new Set([
  '现状用地（原版底图）',
  'landuse',
]);

function isOfflineLanduseLayer(layer: GISLayerConfig): boolean {
  return OFFLINE_LANDUSE_LAYER_NAMES.has(layer.layerName)
    || (layer.layerType === 'function_zone' && layer.layerName.includes('现状用地'))
    || layer.layerType === 'final_landuse';
}

export function enrichLanduseFeaturesForOffline(
  geojson: GeoJsonFeatureCollection | undefined,
): GeoJsonFeatureCollection | undefined {
  if (!geojson?.features?.length) return geojson;
  return {
    ...geojson,
    features: geojson.features.map((feature) => {
      const properties = feature.properties || {};
      if (properties.color && properties.stroke) {
        return feature;
      }
      const zone = String(properties.zone_type || classifyLanduseZone(properties) || '').trim();
      const colors = OFFLINE_LANDUSE_COLORS[zone] || OFFLINE_LANDUSE_DEFAULT;
      return {
        ...feature,
        properties: {
          ...properties,
          ...(zone ? { zone_type: zone } : {}),
          color: colors.color,
          stroke: colors.stroke,
        },
      };
    }),
  };
}

export function styleOfflineBasemapLayer(layer: GISLayerConfig): GISLayerConfig {
  if (isOfflineLanduseLayer(layer)) {
    const geojson = enrichLanduseFeaturesForOffline(layer.geojson);
    return {
      ...layer,
      ...(geojson ? { geojson } : {}),
      style: {
        ...layer.style,
        fillOpacity: 0.88,
        lineOpacity: 0.55,
        lineWidth: 0.45,
      },
    };
  }
  if (layer.layerType === 'boundary' || layer.layerName === 'boundary') {
    return {
      ...layer,
      style: {
        ...layer.style,
        fillOpacity: 0.08,
        lineOpacity: 0.95,
        lineWidth: 2.4,
        lineColor: '#3d6b58',
      },
    };
  }
  return layer;
}

export function styleOfflineBasemapLayers(layers: GISLayerConfig[]): GISLayerConfig[] {
  return layers.map(styleOfflineBasemapLayer);
}

export async function fetchCurrentSourceLayers(villageName = '', sessionId = ''): Promise<CurrentSourceLayersResult> {
  const sourceKey = `${String(sessionId || '').trim().toLowerCase()}:${String(villageName || '').trim().toLowerCase()}`;
  const cached = cachedSources.get(sourceKey);
  if (cached) return cached;
  const pending = pendingSources.get(sourceKey);
  if (pending) return pending;

  const sourceRequest = planningApi.getCurrentSourceLayers(villageName, sessionId)
    .then((payload) => {
      const layers = styleOfflineBasemapLayers(normalizeGisLayers(payload.layers));
      const center = Array.isArray(payload.center) && payload.center.length === 2
        ? [Number(payload.center[0]), Number(payload.center[1])] as [number, number]
        : null;
      const result = { layers, center, rasters: payload.rasters, diagnostics: payload.diagnostics };
      cachedSources.set(sourceKey, result);
      return result;
    })
    .finally(() => {
      pendingSources.delete(sourceKey);
    });

  pendingSources.set(sourceKey, sourceRequest);
  return sourceRequest;
}
