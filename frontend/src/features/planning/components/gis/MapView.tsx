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
import type { FillLayerSpecification, LineLayerSpecification, CircleLayerSpecification, StyleSpecification } from 'maplibre-gl';
import type { MapRef, MapLayerMouseEvent } from 'react-map-gl/maplibre';
import type { FeatureCollection, Geometry, Position, Feature, GeoJsonProperties } from 'geojson';
import 'maplibre-gl/dist/maplibre-gl.css';

import type { GISLayerConfig, GeoJsonFeatureCollection } from '@/types/message/message-types';
import { PLANNING_COLORS, DEFAULT_COLORS, TILE_SOURCES, BASE_MAP_TYPES, BaseMapType, LineColors, FeatureColors, LayerType } from '@/lib/constants/gis';
import LegendPanel from './LegendPanel';

// Layer type display names（规划输出图层类型，区别于 GISUploadSidebar 的 DATA_TYPE_NAMES）
const LAYER_TYPE_NAMES: Record<string, string> = {
  boundary: '行政边界',
  function_zone: '功能区',
  facility_point: '设施点',
  sensitivity_zone: '敏感区',
  infrastructure: '基础设施',
  isochrone: '等时圈',
  development_axis: '发展轴',
  custom: '自定义',
};

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
        {LAYER_TYPE_NAMES[layerType] || layerType} - {layerName}
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
}

// Layer style from backend
interface LayerStyle {
  color?: string;
}

// Layer rendering priority (numerical order, higher = top layer)
const LAYER_PRIORITY: Record<string, number> = {
  'boundary': 0,           // Administrative boundary (bottom layer, reference area)
  'infrastructure': 1,      // Infrastructure (roads, waterways)
  'sensitivity_zone': 2,   // Sensitivity zones
  'function_zone': 3,      // Functional zones
  'isochrone': 4,          // Isochrones
  'development_axis': 5,   // Development axes
  'facility_point': 6,     // Facility points (top layer)
};

// Get feature colors - prioritize backend color
function getFeatureColors(
  geojson: GeoJsonFeatureCollection | undefined,
  layerType: string,
  layerStyle?: LayerStyle,
  directColor?: string
): { fill: string; stroke: string } {
  // Priority 1: Use direct color field (backend sends color at top level)
  if (directColor) {
    return { fill: directColor, stroke: directColor };
  }

  // Priority 2: Use backend style.color if provided
  if (layerStyle?.color) {
    return { fill: layerStyle.color, stroke: layerStyle.color };
  }

  // Priority 3: Use feature's style.color from geojson properties
  const geojsonProps = geojson?.features?.[0]?.properties as Record<string, unknown> | undefined;
  const geojsonColor = geojsonProps?.style as Record<string, unknown> | undefined;
  const colorValue = geojsonColor?.color as string | undefined;
  if (colorValue) {
    return { fill: colorValue, stroke: colorValue };
  }

  // Priority 4: Use PLANNING_COLORS lookup
  // Note: development_axis handled separately in layerStyles, not here
  const props = geojsonProps || {};

  // Map layerType to correct PLANNING_COLORS sub-object
  let subtype = 'default';
  let colorsMap: Record<string, FeatureColors>;

  // Note: boundary is handled separately in layerStyles (line layer, not fill)
  if (layerType === 'function_zone') {
    colorsMap = PLANNING_COLORS.function_zone;
    subtype = (props.zone_type as string) || '居住用地';
  } else if (layerType === 'facility_point') {
    colorsMap = PLANNING_COLORS.facility_point;
    subtype = (props.status as string) || '规划新建';
  } else if (layerType === 'sensitivity_zone') {
    colorsMap = PLANNING_COLORS.sensitivity_zone;
    subtype = (props.sensitivity_level as string) || '中敏感区';
  } else if (layerType === 'isochrone') {
    colorsMap = PLANNING_COLORS.isochrone;
    const timeMinutes = props.time_minutes as number;
    if (timeMinutes) {
      subtype = `${timeMinutes}min`;
    }
  } else {
    // Fallback for unknown layer types
    return DEFAULT_COLORS;
  }

  return colorsMap[subtype] || DEFAULT_COLORS;
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
}: MapViewProps) {
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
    const layerType = layers.find(l => l.layerName === layerName)?.layerType || 'custom';

    setPopupInfo({
      longitude: coordinates.lng,
      latitude: coordinates.lat,
      feature: feature as Feature<Geometry, GeoJsonProperties>,
      layerName,
      layerType,
    });
  }, [layers]);

  // Close popup
  const closePopup = useCallback(() => {
    setPopupInfo(null);
  }, []);

  // Auto-fit bounds when boundary layer is present
  useEffect(() => {
    if (!mounted || !mapRef.current) return;

    const boundaryLayer = layers.find(l => l.layerType === 'boundary');
    if (boundaryLayer) {
      const bounds = getBoundsFromGeoJSON(boundaryLayer.geojson);
      if (bounds) {
        mapRef.current.fitBounds(
          [bounds[0], bounds[1]],
          { padding: 40, duration: 1000 }
        );
      }
    }
  }, [mounted, layers]);

  // 构建 GeoJSON sources - 添加图层渲染优先级排序
  const geojsonSources = useMemo(() => {
    return [...layers].sort((a, b) => {
      const pa = LAYER_PRIORITY[a.layerType] || 0;
      const pb = LAYER_PRIORITY[b.layerType] || 0;
      return pa - pb;
    }).map((layer, index) => {
      const sourceId = `layer-${index}-${layer.layerName}`;
      return { sourceId, data: layer.geojson, layer };
    });
  }, [layers]);

  // Extract active layer types for legend
  const activeLayerTypes = useMemo(() => {
    const types = new Set<LayerType>();
    for (const layer of layers) {
      const layerType = layer.layerType as LayerType;
      if (layerType && PLANNING_COLORS[layerType]) {
        types.add(layerType);
      }
    }
    return Array.from(types);
  }, [layers]);

  // Build layer styles
  const layerStyles = useMemo(() => {
    return geojsonSources.map(({ sourceId, layer }) => {
      // Get color from top-level or style.color (backend sends color at top level)
      const directColor = layer.color;
      const styleColor = layer.style?.color;
      if (layer.layerType === 'boundary') {
        // Boundary - line only, no fill
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
        // Point features - circle layer
        const colors = getFeatureColors(layer.geojson, layer.layerType, { color: styleColor }, directColor);
        const circleLayer: CircleLayerSpecification = {
          id: `${sourceId}-circle`,
          type: 'circle',
          source: sourceId,
          paint: {
            'circle-radius': 8,
            'circle-color': colors.fill,
            'circle-stroke-width': 2,
            'circle-stroke-color': colors.stroke,
            'circle-opacity': 0.8,
          },
        };
        return [circleLayer];
      } else if (layer.layerType === 'development_axis') {
        // Line features - use LineColors type
        let lineColor = directColor || styleColor;
        let lineWidth = 2;
        if (!lineColor) {
          const axisStyles: Record<string, LineColors> = PLANNING_COLORS.development_axis;
          const props = layer.geojson?.features?.[0]?.properties || {};
          const axisType = (props.axis_type as string) || '发展主轴';
          const style = axisStyles[axisType] || { stroke: '#FF0000', width: 2 };
          lineColor = style.stroke;
          lineWidth = style.width;
        }
        const lineLayer: LineLayerSpecification = {
          id: `${sourceId}-line`,
          type: 'line',
          source: sourceId,
          paint: {
            'line-color': lineColor,
            'line-width': lineWidth,
          },
        };
        return [lineLayer];
      } else if (layer.layerType === 'infrastructure') {
        // Infrastructure - roads, waterways, utilities (line)
        const props = layer.geojson?.features?.[0]?.properties || {};
        const infraType = (props.infrastructure_type as string) || (props.RN as string) || '道路';
        const infraStyles: Record<string, LineColors> = PLANNING_COLORS.infrastructure;

        let lineColor = '#666666';
        let lineWidth = 2;

        // Match subtype
        if (infraType.includes('县道')) {
          lineColor = infraStyles['县道']?.stroke || '#555555';
          lineWidth = infraStyles['县道']?.width || 2;
        } else if (infraType.includes('乡道')) {
          lineColor = infraStyles['乡道']?.stroke || '#808080';
          lineWidth = infraStyles['乡道']?.width || 1.5;
        } else if (infraType.includes('河') || infraType.includes('水系')) {
          lineColor = infraStyles['河流']?.stroke || '#00BFFF';
          lineWidth = infraStyles['河流']?.width || 2.5;
        } else {
          lineColor = infraStyles['道路']?.stroke || '#666666';
          lineWidth = infraStyles['道路']?.width || 2;
        }

        const infraLayer: LineLayerSpecification = {
          id: `${sourceId}-infra`,
          type: 'line',
          source: sourceId,
          paint: {
            'line-color': lineColor,
            'line-width': lineWidth,
          },
        };
        return [infraLayer];
      } else {
        // Polygon features - fill + line layers
        // Check if features have color property (from backend spatial_layout_generator)
        const hasFeatureColors = layer.geojson?.features?.some(
          f => (f.properties as Record<string, unknown>)?.color
        );

        if (hasFeatureColors) {
          // Use data-driven styling from feature properties
          const fillLayer: FillLayerSpecification = {
            id: `${sourceId}-fill`,
            type: 'fill',
            source: sourceId,
            paint: {
              'fill-color': ['get', 'color'],
              'fill-opacity': 0.6,
            },
          };
          // Soft outline using same color family
          const lineLayer: LineLayerSpecification = {
            id: `${sourceId}-line`,
            type: 'line',
            source: sourceId,
            paint: {
              'line-color': ['get', 'color'],
              'line-width': 1.5,
              'line-opacity': 0.8,
            },
          };
          return [fillLayer, lineLayer];
        } else {
          // Fallback: use static colors from PLANNING_COLORS
          const colors = getFeatureColors(layer.geojson, layer.layerType, { color: styleColor }, directColor);
          const fillLayer: FillLayerSpecification = {
            id: `${sourceId}-fill`,
            type: 'fill',
            source: sourceId,
            paint: {
              'fill-color': colors.fill,
              'fill-opacity': 0.5,
            },
          };
          const lineLayer: LineLayerSpecification = {
            id: `${sourceId}-line`,
            type: 'line',
            source: sourceId,
            paint: {
              'line-color': colors.stroke,
              'line-width': 2,
            },
          };
          return [fillLayer, lineLayer];
        }
      }
    });
  }, [geojsonSources]);

  // Memoize interactive layer IDs for click handling
  const interactiveLayerIds = useMemo(() =>
    geojsonSources.flatMap(
      (_, index) => layerStyles[index].map(ls => ls.id)
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
              {layerStyles[index].map((layerStyle) => (
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