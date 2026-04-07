'use client';

/**
 * MapView - MapLibre GL 地图容器组件
 *
 * 用于渲染 GIS 分析结果，支持 GeoJSON 图层、矢量瓦片等。
 * 使用 GeoJSON 标准坐标格式 [longitude, latitude]（经度在前）。
 */

import { useEffect, useState, useMemo } from 'react';
import Map, { Source, Layer } from 'react-map-gl/maplibre';
import type { FillLayerSpecification, LineLayerSpecification, CircleLayerSpecification, StyleSpecification } from 'maplibre-gl';
import type { FeatureCollection, Geometry } from 'geojson';
import 'maplibre-gl/dist/maplibre-gl.css';

import type { GISLayerConfig, GeoJsonFeatureCollection } from '@/types/message/message-types';
import { PLANNING_COLORS, DEFAULT_COLORS, TILE_SOURCES, LineColors, FeatureColors } from '@/lib/constants/gis';

// Tile URLs (static - evaluated at build time)
// ter_w: 地形晕渲（球面墨卡托投影）- 淡色背景更适合规划展示
// cta_w: 地形注记（球面墨卡托投影）
const TIANDITU_BASE_URL = '/api/tiles/tianditu/ter_w/{z}/{y}/{x}';
const TIANDITU_ANNOTATION_URL = '/api/tiles/tianditu/cta_w/{z}/{y}/{x}';
const GEOQ_TILE_URL = 'https://map.geoq.cn/ArcGIS/rest/services/ChinaOnlineCommunity/MapServer/tile/{z}/{y}/{x}';
const OSM_TILE_URL = 'https://tile.openstreetmap.org/{z}/{x}/{y}.png';

// Tile config type
type TileConfig = { baseUrl: string; annotationUrl: string; attribution: string };

// Module-level tile config (IIFE - evaluated once at build time)
const TILE_CONFIG: TileConfig = (() => {
  const source = (process.env.NEXT_PUBLIC_TILE_SOURCE || TILE_SOURCES.TIANDITU) as keyof typeof configs;
  const configs: Record<string, TileConfig> = {
    [TILE_SOURCES.TIANDITU]: {
      baseUrl: TIANDITU_BASE_URL,
      annotationUrl: TIANDITU_ANNOTATION_URL,
      attribution: '天地图'
    },
    [TILE_SOURCES.GEOQ]: {
      baseUrl: GEOQ_TILE_URL,
      annotationUrl: '',
      attribution: 'GeoQ'
    },
    [TILE_SOURCES.OSM]: {
      baseUrl: OSM_TILE_URL,
      annotationUrl: '',
      attribution: 'OpenStreetMap'
    },
  };
  return configs[source] || configs[TILE_SOURCES.OSM];
})();

interface MapViewProps {
  layers: GISLayerConfig[];
  center?: [number, number]; // [longitude, latitude] GeoJSON 标准
  zoom?: number;
  height?: string;
  title?: string;
}

// Layer style from backend
interface LayerStyle {
  color?: string;
}

// Layer rendering priority (numerical order, higher = top layer)
const LAYER_PRIORITY: Record<string, number> = {
  'sensitivity_zone': 1,   // Sensitivity zones (bottom layer)
  'function_zone': 2,      // Functional zones
  'isochrone': 3,          // Isochrones
  'development_axis': 4,   // Development axes
  'facility_point': 5,     // Facility points (top layer)
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
  center = [120.0, 30.0], // [longitude, latitude] GeoJSON 标准
  zoom = 14,
  height = '400px',
  title,
}: MapViewProps) {
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

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

  // Build layer styles
  const layerStyles = useMemo(() => {
    return geojsonSources.map(({ sourceId, layer }) => {
      // Get color from top-level or style.color (backend sends color at top level)
      const directColor = layer.color;
      const styleColor = layer.style?.color;
      if (layer.layerType === 'facility_point') {
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
      } else {
        // Polygon features - fill + line layers
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
    });
  }, [geojsonSources]);

  // Build base map style (static - TILE_CONFIG is module-level constant)
  const mapStyle: StyleSpecification = useMemo(() => {
    // Tianditu needs annotation layer overlay for place names
    if (TILE_CONFIG.annotationUrl) {
      return {
        version: 8,
        sources: {
          'base-tiles': {
            type: 'raster',
            tiles: [TILE_CONFIG.baseUrl],
            tileSize: 256,
            attribution: TILE_CONFIG.attribution,
          },
          'annotation-tiles': {
            type: 'raster',
            tiles: [TILE_CONFIG.annotationUrl],
            tileSize: 256,
          },
        },
        layers: [
          { id: 'base-tiles-layer', type: 'raster', source: 'base-tiles' },
          { id: 'annotation-tiles-layer', type: 'raster', source: 'annotation-tiles' },
        ],
      } as StyleSpecification;
    }
    // Other tile sources without annotation overlay
    return {
      version: 8,
      sources: {
        'base-tiles': {
          type: 'raster',
          tiles: [TILE_CONFIG.baseUrl],
          tileSize: 256,
          attribution: TILE_CONFIG.attribution,
        },
      },
      layers: [
        { id: 'base-tiles-layer', type: 'raster', source: 'base-tiles' },
      ],
    } as StyleSpecification;
  }, []);

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
      <div style={{ height }}>
        <Map
          initialViewState={{
            longitude: center[0],
            latitude: center[1],
            zoom: zoom,
          }}
          style={{ width: '100%', height: '100%' }}
          mapStyle={mapStyle}
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
        </Map>
      </div>
    </div>
  );
}