'use client';

/**
 * MapView - MapLibre GL 地图容器组件
 *
 * 用于渲染 GIS 分析结果，支持 GeoJSON 图层、矢量瓦片等。
 * 使用 GeoJSON 标准坐标格式 [longitude, latitude]（经度在前）。
 * 支持要素点击事件和 Popup 属性显示。
 */

import { useEffect, useState, useMemo, useRef, useCallback } from 'react';
import Map, { Source, Layer, Popup } from 'react-map-gl/maplibre';
import type { FillLayerSpecification, LineLayerSpecification, CircleLayerSpecification, StyleSpecification, ExpressionSpecification } from 'maplibre-gl';
import type { MapRef, MapLayerMouseEvent } from 'react-map-gl/maplibre';
import type { FeatureCollection, Geometry, Position, Feature, GeoJsonProperties } from 'geojson';
import 'maplibre-gl/dist/maplibre-gl.css';

import type { GISLayerConfig, GeoJsonFeatureCollection } from '@/types/message/message-types';
import { PLANNING_COLORS, DEFAULT_COLORS, TILE_SOURCES, BASE_MAP_TYPES, BaseMapType, LineColors, FeatureColors, LayerType, LAYER_TYPE_LABELS } from '@/features/planning/constants/gis';
import LegendPanel from './LegendPanel';

// Feature Popup Content Component
function FeaturePopupContent({
  feature,
  layerName,
  layerType,
}: {
  feature: Feature<Geometry, GeoJsonProperties>;
  layerName: string;
  layerType: string;
}) {
  const properties = feature.properties || {};

  // Filter and limit display properties
  const displayProps = Object.entries(properties)
    .filter(([key]) => !key.startsWith('_')) // Filter internal props
    .slice(0, 10); // Limit to 10 properties

  return (
    <div className="p-2 max-w-[280px]">
      <div className="font-semibold text-sm text-gray-800 mb-1 border-b border-gray-200 pb-1">
        {(LAYER_TYPE_LABELS[layerType as LayerType] || layerType)} - {layerName}
      </div>
      <div className="space-y-1 text-xs">
        {displayProps.length > 0 ? (
          displayProps.map(([key, value]) => (
            <div key={key} className="flex justify-between gap-2">
              <span className="text-gray-500">{key}:</span>
              <span className="text-gray-700 font-medium truncate">
                {typeof value === 'object' ? JSON.stringify(value).slice(0, 50) : String(value)}
              </span>
            </div>
          ))
        ) : (
          <div className="text-gray-400">无属性数据</div>
        )}
      </div>
    </div>
  );
}

// Helper: Extract all coordinates from a geometry recursively
function extractCoords(geometry: { type: string; coordinates: unknown }): Position[] {
  const coords: Position[] = [];
  const coordsData = geometry.coordinates;
  if (geometry.type === 'Point') {
    coords.push(coordsData as Position);
  } else if (geometry.type === 'LineString' || geometry.type === 'MultiPoint') {
    coords.push(...(coordsData as Position[]));
  } else if (geometry.type === 'Polygon' || geometry.type === 'MultiLineString') {
    for (const ring of coordsData as Position[][]) {
      coords.push(...ring);
    }
  } else if (geometry.type === 'MultiPolygon') {
    for (const polygon of coordsData as Position[][][]) {
      for (const ring of polygon) {
        coords.push(...ring);
      }
    }
  }
  return coords;
}

// Helper: Calculate bounds from GeoJSON
function getBoundsFromGeoJSON(geojson: GeoJsonFeatureCollection): [[number, number], [number, number]] | null {
  if (!geojson.features || geojson.features.length === 0) return null;

  let minLon = Infinity, maxLon = -Infinity;
  let minLat = Infinity, maxLat = -Infinity;

  for (const feature of geojson.features) {
    const coords = extractCoords(feature.geometry);
    for (const coord of coords) {
      const [lon, lat] = coord;
      if (lon < minLon) minLon = lon;
      if (lon > maxLon) maxLon = lon;
      if (lat < minLat) minLat = lat;
      if (lat > maxLat) maxLat = lat;
    }
  }

  if (minLon === Infinity) return null;
  return [[minLon, minLat], [maxLon, maxLat]];
}

// Tile URLs - vec_w: Vector map (planning法定底图), cva_w: Vector annotation
const getTiandituUrls = (baseMapType: BaseMapType) => {
  const config = BASE_MAP_TYPES[baseMapType];
  return {
    baseUrl: `/api/tiles/tianditu/${config.tile}_w/{z}/{y}/{x}`,
    annotationUrl: `/api/tiles/tianditu/${config.annotation}_w/{z}/{y}/{x}`,
  };
};
const GEOQ_TILE_URL = 'https://map.geoq.cn/ArcGIS/rest/services/ChinaOnlineCommunity/MapServer/tile/{z}/{y}/{x}';
const OSM_TILE_URL = 'https://tile.openstreetmap.org/{z}/{x}/{y}.png';

interface MapViewProps {
  layers: GISLayerConfig[];
  center?: [number, number]; // [longitude, latitude] GeoJSON standard
  zoom?: number;
  height?: string;
  title?: string;
  baseMapType?: BaseMapType; // Default: 'vector' (planning法定底图)
  showLegend?: boolean; // Whether to show legend panel
  legendPosition?: 'bottom-right' | 'bottom-left' | 'top-right' | 'top-left';
  visibleLayerTypes?: Set<LayerType>; // Optional: filter which layers to render
}

// Layer rendering priority (numerical order, higher = top layer)
const LAYER_PRIORITY: Record<string, number> = {
  'boundary': 0,
  'infrastructure': 1,
  'sensitivity_zone': 2,
  'function_zone': 3,
  'planning_zone': 4,
  'isochrone': 5,
  'development_axis': 6,
  'facility_point': 7,
};

// Helper: check if features have per-feature color
function hasFeatureColors(geojson: GeoJsonFeatureCollection | undefined): boolean {
  return !!geojson?.features?.some(f => (f.properties as Record<string, unknown>)?.color);
}

// Build match expression from PLANNING_COLORS sub-map
function buildMatchExpression(
  property: string,
  colorMap: Record<string, Record<string, unknown>>,
  defaultColor: string,
  field: 'fill' | 'stroke' = 'fill',
): ExpressionSpecification {
  const cases: (string | number)[] = [];
  for (const [key, colors] of Object.entries(colorMap)) {
    const value = colors[field];
    if (typeof value === 'string') cases.push(key, value);
  }
  return ['match', ['get', property], ...cases, defaultColor] as unknown as ExpressionSpecification;
}

export default function MapView({
  layers,
  center = [120.0, 30.0],
  zoom = 14,
  height = '400px',
  title,
  baseMapType = 'vector',
  showLegend = true,
  legendPosition = 'bottom-right',
  visibleLayerTypes,
}: MapViewProps) {
  // Filter layers by visible types if provided
  const filteredLayers = useMemo(
    () => visibleLayerTypes
      ? layers.filter((l) => visibleLayerTypes.has(l.layerType as LayerType))
      : layers,
    [layers, visibleLayerTypes],
  );
  const [mounted, setMounted] = useState(false);
  const mapRef = useRef<MapRef>(null);

  // Popup state
  const [popupInfo, setPopupInfo] = useState<{
    longitude: number;
    latitude: number;
    feature: Feature<Geometry, GeoJsonProperties>;
    layerName: string;
    layerType: string;
  } | null>(null);

  useEffect(() => {
    setMounted(true);
  }, []);

  // Handle feature click
  const handleLayerClick = useCallback((event: MapLayerMouseEvent) => {
    const feature = event.features?.[0];
    if (!feature) return;

    // Get click coordinates
    const coordinates = event.lngLat;

    // Extract layer info from source id
    const sourceId = (feature.source as string) || '';
    const layerMatch = sourceId.match(/layer-\d+-(.+)/);
    const layerName = layerMatch?.[1] || '未知图层';
    const layerType = filteredLayers.find(l => l.layerName === layerName)?.layerType || 'custom';

    setPopupInfo({
      longitude: coordinates.lng,
      latitude: coordinates.lat,
      feature: feature as Feature<Geometry, GeoJsonProperties>,
      layerName,
      layerType,
    });
  }, [filteredLayers]);

  // Close popup
  const closePopup = useCallback(() => {
    setPopupInfo(null);
  }, []);

  // Auto-fit bounds when boundary layer is present
  useEffect(() => {
    if (!mounted || !mapRef.current) return;

    // Prefer village-level boundary (fewer features, more local)
    // over county-level admin boundaries
    const boundaryLayers = filteredLayers.filter(l => l.layerType === 'boundary');
    if (boundaryLayers.length === 0) return;

    // Find the best boundary: prefer layers with fewer features (village > town > county)
    // and layers with 'boundary' or 'village' in the name
    let bestBoundary = boundaryLayers[0];
    let bestScore = Infinity;
    for (const layer of boundaryLayers) {
      const featureCount = layer.geojson?.features?.length || 0;
      const name = (layer.layerName || '').toLowerCase();
      // Score: prefer village/current boundary (lower is better)
      let score = featureCount;
      if (name.includes('village') || name.includes('current')) score *= 0.5;
      if (name.includes('admin') || name.includes('county')) score *= 10;
      if (name.includes('pingyuan')) score *= 100; // county-level
      if (score < bestScore) {
        bestScore = score;
        bestBoundary = layer;
      }
    }

    const bounds = getBoundsFromGeoJSON(bestBoundary.geojson);
    if (bounds) {
      mapRef.current.fitBounds(
        [bounds[0], bounds[1]],
        { padding: 40, duration: 1000 }
      );
    }
  }, [mounted, filteredLayers]);

  // Build GeoJSON sources with layer priority sorting
  const geojsonSources = useMemo(() => {
    return [...filteredLayers].sort((a, b) => {
      const pa = LAYER_PRIORITY[a.layerType] || 0;
      const pb = LAYER_PRIORITY[b.layerType] || 0;
      return pa - pb;
    }).map((layer, index) => {
      const sourceId = `layer-${index}-${layer.layerName}`;
      return { sourceId, data: layer.geojson, layer };
    });
  }, [filteredLayers]);

  // Extract active layer types for legend
  const activeLayerTypes = useMemo(() => {
    const types = new Set<LayerType>();
    for (const layer of filteredLayers) {
      const layerType = layer.layerType as LayerType;
      if (layerType && PLANNING_COLORS[layerType]) {
        types.add(layerType);
      }
    }
    return Array.from(types);
  }, [filteredLayers]);

  // Build layer styles — unified: ['get', 'color'] with ['match'] fallback
  const layerStyles = useMemo(() => {
    return geojsonSources.map(({ sourceId, layer }) => {
      if (layer.layerType === 'boundary') {
        const boundaryStyle = (PLANNING_COLORS.boundary as Record<string, LineColors>)['行政边界'] || { stroke: '#333333', width: 2 };
        const boundaryLayer: LineLayerSpecification = {
          id: `${sourceId}-boundary`,
          type: 'line',
          source: sourceId,
          paint: {
            'line-color': boundaryStyle.stroke,
            'line-width': boundaryStyle.width,
            'line-opacity': 1,
          },
        };
        return [boundaryLayer];
      } else if (layer.layerType === 'facility_point') {
        const useFeatureColors = hasFeatureColors(layer.geojson);
        const circleLayer: CircleLayerSpecification = {
          id: `${sourceId}-circle`,
          type: 'circle',
          source: sourceId,
          paint: {
            'circle-radius': [
              'interpolate', ['linear'], ['zoom'],
              10, 4, 14, 6, 18, 10,
            ] as ExpressionSpecification,
            'circle-color': useFeatureColors
              ? ['get', 'color'] as ExpressionSpecification
              : buildMatchExpression('status', PLANNING_COLORS.facility_point, DEFAULT_COLORS.fill),
            'circle-stroke-width': [
              'interpolate', ['linear'], ['zoom'],
              10, 1, 14, 2, 18, 3,
            ] as ExpressionSpecification,
            'circle-stroke-color': useFeatureColors
              ? ['get', 'stroke'] as ExpressionSpecification
              : buildMatchExpression('status', PLANNING_COLORS.facility_point, DEFAULT_COLORS.stroke, 'stroke'),
            'circle-opacity': 0.8,
          },
        };
        return [circleLayer];
      } else if (layer.layerType === 'development_axis') {
        const useFeatureColors = hasFeatureColors(layer.geojson);
        const lineLayer: LineLayerSpecification = {
          id: `${sourceId}-line`,
          type: 'line',
          source: sourceId,
          paint: {
            'line-color': useFeatureColors
              ? ['get', 'color'] as ExpressionSpecification
              : buildMatchExpression('axis_type', PLANNING_COLORS.development_axis, '#00AA00', 'stroke'),
            'line-width': useFeatureColors
              ? ['coalesce', ['get', 'weight'], 2] as ExpressionSpecification
              : 2,
          },
        };
        return [lineLayer];
      } else if (layer.layerType === 'infrastructure') {
        const useFeatureColors = hasFeatureColors(layer.geojson);
        const lineLayer: LineLayerSpecification = {
          id: `${sourceId}-infra`,
          type: 'line',
          source: sourceId,
          paint: {
            'line-color': useFeatureColors
              ? ['get', 'color'] as ExpressionSpecification
              : buildMatchExpression('infra_type', PLANNING_COLORS.infrastructure, '#666666', 'stroke'),
            'line-width': useFeatureColors
              ? ['coalesce', ['get', 'weight'], 2] as ExpressionSpecification
              : 2,
          },
        };
        return [lineLayer];
      } else if (layer.layerType === 'sensitivity_zone') {
        const useFeatureColors = hasFeatureColors(layer.geojson);
        const fillLayer: FillLayerSpecification = {
          id: `${sourceId}-fill`,
          type: 'fill',
          source: sourceId,
          paint: {
            'fill-color': useFeatureColors
              ? ['get', 'color'] as ExpressionSpecification
              : buildMatchExpression('sensitivity_level', PLANNING_COLORS.sensitivity_zone, DEFAULT_COLORS.fill),
            'fill-opacity': 0.3,
          },
        };
        const lineLayer: LineLayerSpecification = {
          id: `${sourceId}-line`,
          type: 'line',
          source: sourceId,
          paint: {
            'line-color': useFeatureColors
              ? ['get', 'stroke'] as ExpressionSpecification
              : buildMatchExpression('sensitivity_level', PLANNING_COLORS.sensitivity_zone, DEFAULT_COLORS.stroke, 'stroke'),
            'line-width': 1,
          },
        };
        return [fillLayer, lineLayer];
      } else if (layer.layerType === 'isochrone') {
        const useFeatureColors = hasFeatureColors(layer.geojson);
        // Isochrone match: time_minutes is numeric (5/10/15), PLANNING_COLORS keys are '5min'/'10min'/'15min'
        const isoMatch = (field: 'fill' | 'stroke', defaultColor: string): ExpressionSpecification =>
          ['match', ['to-string', ['get', 'time_minutes']],
            ...Object.entries(PLANNING_COLORS.isochrone).flatMap(([k, c]) => [k.replace('min', ''), (c as FeatureColors)[field]]),
            defaultColor] as ExpressionSpecification;
        const fillLayer: FillLayerSpecification = {
          id: `${sourceId}-fill`,
          type: 'fill',
          source: sourceId,
          paint: {
            'fill-color': useFeatureColors ? ['get', 'color'] as ExpressionSpecification : isoMatch('fill', DEFAULT_COLORS.fill),
            'fill-opacity': 0.2,
          },
        };
        const lineLayer: LineLayerSpecification = {
          id: `${sourceId}-line`,
          type: 'line',
          source: sourceId,
          paint: {
            'line-color': useFeatureColors ? ['get', 'stroke'] as ExpressionSpecification : isoMatch('stroke', DEFAULT_COLORS.stroke),
            'line-width': 1,
          },
        };
        return [fillLayer, lineLayer];
      } else if (layer.layerType === 'planning_zone') {
        const useFeatureColors = hasFeatureColors(layer.geojson);
        const fillLayer: FillLayerSpecification = {
          id: `${sourceId}-fill`,
          type: 'fill',
          source: sourceId,
          paint: {
            'fill-color': useFeatureColors
              ? ['get', 'color'] as ExpressionSpecification
              : buildMatchExpression('zone_type', PLANNING_COLORS.planning_zone, DEFAULT_COLORS.fill),
            'fill-opacity': 0.35,
          },
        };
        const lineLayer: LineLayerSpecification = {
          id: `${sourceId}-line`,
          type: 'line',
          source: sourceId,
          paint: {
            'line-color': useFeatureColors
              ? ['get', 'stroke'] as ExpressionSpecification
              : buildMatchExpression('zone_type', PLANNING_COLORS.planning_zone, DEFAULT_COLORS.stroke, 'stroke'),
            'line-width': 2.5,
            'line-dasharray': [3, 2],
            'line-opacity': 0.9,
          },
        };
        return [fillLayer, lineLayer];
      } else if (layer.layerType === 'function_zone') {
        const useFeatureColors = hasFeatureColors(layer.geojson);
        const fillLayer: FillLayerSpecification = {
          id: `${sourceId}-fill`,
          type: 'fill',
          source: sourceId,
          paint: {
            'fill-color': useFeatureColors
              ? ['get', 'color'] as ExpressionSpecification
              : buildMatchExpression('zone_type', PLANNING_COLORS.function_zone, DEFAULT_COLORS.fill),
            'fill-opacity': 0.6,
          },
        };
        const lineLayer: LineLayerSpecification = {
          id: `${sourceId}-line`,
          type: 'line',
          source: sourceId,
          paint: {
            'line-color': useFeatureColors
              ? ['get', 'stroke'] as ExpressionSpecification
              : buildMatchExpression('zone_type', PLANNING_COLORS.function_zone, DEFAULT_COLORS.stroke, 'stroke'),
            'line-width': 1.5,
            'line-opacity': 0.8,
          },
        };
        return [fillLayer, lineLayer];
      }
      // Default: fill + line for unknown layer types
      const defaultFill: FillLayerSpecification = {
        id: `${sourceId}-fill`,
        type: 'fill',
        source: sourceId,
        paint: {
          'fill-color': hasFeatureColors(layer.geojson) ? ['get', 'color'] as ExpressionSpecification : DEFAULT_COLORS.fill,
          'fill-opacity': 0.5,
        },
      };
      const defaultLine: LineLayerSpecification = {
        id: `${sourceId}-line`,
        type: 'line',
        source: sourceId,
        paint: {
          'line-color': hasFeatureColors(layer.geojson) ? ['get', 'stroke'] as ExpressionSpecification : DEFAULT_COLORS.stroke,
          'line-width': 1.5,
        },
      };
      return [defaultFill, defaultLine];
    });
  }, [geojsonSources]);

  // Memoize interactive layer IDs for click handling
  const interactiveLayerIds = useMemo(() =>
    geojsonSources.flatMap(
      (_, index) => (layerStyles[index] || []).map(ls => ls.id)
    ).filter(Boolean),
    [geojsonSources, layerStyles]
  );

  // Build base map style - dynamic based on baseMapType
  const mapStyle: StyleSpecification = useMemo(() => {
    const tileSource = process.env.NEXT_PUBLIC_TILE_SOURCE || TILE_SOURCES.TIANDITU;

    // Handle non-Tianditu tile sources
    if (tileSource !== TILE_SOURCES.TIANDITU) {
      const otherConfigs: Record<string, { baseUrl: string; attribution: string }> = {
        [TILE_SOURCES.GEOQ]: { baseUrl: GEOQ_TILE_URL, attribution: 'GeoQ' },
        [TILE_SOURCES.OSM]: { baseUrl: OSM_TILE_URL, attribution: 'OpenStreetMap' },
      };
      const config = otherConfigs[tileSource] || otherConfigs[TILE_SOURCES.OSM];
      return {
        version: 8,
        sources: {
          'base-tiles': {
            type: 'raster',
            tiles: [config.baseUrl],
            tileSize: 256,
            attribution: config.attribution,
          },
        },
        layers: [
          { id: 'base-tiles-layer', type: 'raster', source: 'base-tiles' },
        ],
      } as StyleSpecification;
    }

    // Tianditu with annotation layer
    const { baseUrl, annotationUrl } = getTiandituUrls(baseMapType);
    return {
      version: 8,
      sources: {
        'base-tiles': {
          type: 'raster',
          tiles: [baseUrl],
          tileSize: 256,
          attribution: '天地图',
        },
        'annotation-tiles': {
          type: 'raster',
          tiles: [annotationUrl],
          tileSize: 256,
        },
      },
      layers: [
        { id: 'base-tiles-layer', type: 'raster', source: 'base-tiles' },
        { id: 'annotation-tiles-layer', type: 'raster', source: 'annotation-tiles' },
      ],
    } as StyleSpecification;
  }, [baseMapType]);

  if (!mounted) {
    return (
      <div
        className="bg-gray-100 rounded-lg flex items-center justify-center"
        style={{ height }}
      >
        <span className="text-gray-500">加载地图中...</span>
      </div>
    );
  }

  return (
    <div className="rounded-lg overflow-hidden border border-gray-200">
      {title && (
        <div className="bg-gray-50 px-4 py-2 border-b border-gray-200">
          <h3 className="text-sm font-medium text-gray-700">{title}</h3>
        </div>
      )}
      <div style={{ height, position: 'relative' }}>
        <Map
          ref={mapRef}
          reuseMaps
          initialViewState={{
            longitude: center[0],
            latitude: center[1],
            zoom: zoom,
          }}
          style={{ width: '100%', height: '100%' }}
          mapStyle={mapStyle}
          interactiveLayerIds={interactiveLayerIds}
          onClick={handleLayerClick}
        >
          {geojsonSources.map(({ sourceId, data }, index) => (
            <Source
              key={sourceId}
              id={sourceId}
              type="geojson"
              data={data as FeatureCollection<Geometry>}
            >
              {(layerStyles[index] || []).map((layerStyle) => (
                <Layer key={layerStyle.id} {...layerStyle} />
              ))}
            </Source>
          ))}

          {/* Feature Popup */}
          {popupInfo && (
            <Popup
              longitude={popupInfo.longitude}
              latitude={popupInfo.latitude}
              onClose={closePopup}
              closeButton={true}
              closeOnClick={false}
              anchor="top"
              className="feature-popup"
            >
              <FeaturePopupContent
                feature={popupInfo.feature}
                layerName={popupInfo.layerName}
                layerType={popupInfo.layerType}
              />
            </Popup>
          )}
        </Map>
        {showLegend && activeLayerTypes.length > 0 && (
          <LegendPanel
            layerTypes={activeLayerTypes}
            position={legendPosition}
          />
        )}
      </div>
    </div>
  );
}