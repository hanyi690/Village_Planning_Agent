'use client';

/**
 * MapContainer - Leaflet 地图容器组件
 *
 * 用于渲染 GIS 分析结果，支持 GeoJSON 图层、等时圈等功能。
 */

import { useEffect, useState, useMemo, useCallback } from 'react';
import dynamic from 'next/dynamic';

// 动态导入 Leaflet 组件，避免 SSR 问题
const MapContainer = dynamic(
  () => import('react-leaflet').then((mod) => mod.MapContainer),
  { ssr: false }
);
const TileLayer = dynamic(
  () => import('react-leaflet').then((mod) => mod.TileLayer),
  { ssr: false }
);
const GeoJSON = dynamic(
  () => import('react-leaflet').then((mod) => mod.GeoJSON),
  { ssr: false }
);

import type { GISLayerConfig } from '@/types/message/message-types';

// 导入 Leaflet CSS
import 'leaflet/dist/leaflet.css';

// Leaflet 类型定义
type LeafletPathOptions = {
  fillColor?: string;
  fillOpacity?: number;
  color?: string;
  weight?: number;
  radius?: number;
  opacity?: number;
};

interface MapViewProps {
  layers: GISLayerConfig[];
  center?: [number, number];
  zoom?: number;
  height?: string;
  title?: string;
}

// 规划符号样式
const PLANNING_STYLES: Record<string, Record<string, LeafletPathOptions>> = {
  function_zone: {
    '居住用地': { fillColor: '#FFD700', fillOpacity: 0.6, color: '#B8860B', weight: 2 },
    '产业用地': { fillColor: '#FF6B6B', fillOpacity: 0.6, color: '#CC0000', weight: 2 },
    '公共服务用地': { fillColor: '#4A90D9', fillOpacity: 0.6, color: '#1E3A5F', weight: 2 },
    '生态绿地': { fillColor: '#90EE90', fillOpacity: 0.6, color: '#228B22', weight: 2 },
    '交通用地': { fillColor: '#808080', fillOpacity: 0.5, color: '#404040', weight: 2 },
    '水域': { fillColor: '#87CEEB', fillOpacity: 0.7, color: '#4169E1', weight: 2 },
    '农业用地': { fillColor: '#8B4513', fillOpacity: 0.5, color: '#654321', weight: 2 },
    '商业用地': { fillColor: '#FFA500', fillOpacity: 0.6, color: '#CC8400', weight: 2 },
  },
  facility_point: {
    '现状保留': { fillColor: 'green', radius: 8 },
    '规划新建': { fillColor: 'blue', radius: 8 },
    '规划改扩建': { fillColor: 'orange', radius: 8 },
    '规划迁建': { fillColor: 'purple', radius: 8 },
  },
  sensitivity_zone: {
    '高敏感区': { fillColor: '#FF0000', fillOpacity: 0.4, color: '#CC0000', weight: 2 },
    '中敏感区': { fillColor: '#FFFF00', fillOpacity: 0.3, color: '#CCCC00', weight: 2 },
    '低敏感区': { fillColor: '#00FF00', fillOpacity: 0.2, color: '#00CC00', weight: 2 },
  },
  isochrone: {
    '5min': { fillColor: '#00FF00', fillOpacity: 0.3, color: '#00CC00', weight: 2 },
    '10min': { fillColor: '#FFFF00', fillOpacity: 0.25, color: '#CCCC00', weight: 2 },
    '15min': { fillColor: '#FFA500', fillOpacity: 0.2, color: '#CC8400', weight: 2 },
  },
};

// 默认样式
const DEFAULT_STYLE: LeafletPathOptions = { fillColor: '#CCCCCC', fillOpacity: 0.5, color: '#666666', weight: 2 };

// 获取要素样式（提取到组件外部避免重复创建）
function getFeatureStyle(properties: Record<string, unknown> | undefined, layerType: string): LeafletPathOptions {
  const styles = PLANNING_STYLES[layerType] || {};
  const props = properties || {};

  // 根据图层类型确定子类型
  let subtype = 'default';
  if (layerType === 'function_zone') {
    subtype = (props.zone_type as string) || '居住用地';
  } else if (layerType === 'facility_point') {
    subtype = (props.status as string) || '规划新建';
  } else if (layerType === 'sensitivity_zone') {
    subtype = (props.sensitivity_level as string) || '中敏感区';
  } else if (layerType === 'isochrone') {
    const timeMinutes = props.time_minutes as number;
    if (timeMinutes) {
      subtype = `${timeMinutes}min`;
    }
  }

  const baseStyle = styles[subtype] || DEFAULT_STYLE;

  // 返回样式
  const result: LeafletPathOptions = { ...baseStyle };
  if (props.color) {
    result.fillColor = props.color as string;
  }
  if (props.fillOpacity !== undefined) {
    result.fillOpacity = props.fillOpacity as number;
  }
  return result;
}

export default function MapView({
  layers,
  center = [30.0, 120.0],
  zoom = 14,
  height = '400px',
  title,
}: MapViewProps) {
  const [mounted, setMounted] = useState(false);
  const [L, setL] = useState<typeof import('leaflet') | null>(null);

  useEffect(() => {
    setMounted(true);
    // 只在客户端加载 Leaflet
    import('leaflet').then((leaflet) => {
      setL(leaflet.default || leaflet);
    });
  }, []);

  // 使用 useMemo 缓存样式函数，避免每次渲染重新创建
  const layerRenderers = useMemo(() => {
    if (!L) return [];

    return layers.map((layer) => {
      // 样式函数
      const styleFunc = (feature: { properties?: Record<string, unknown> } | undefined) => {
        if (!feature) return DEFAULT_STYLE;
        return getFeatureStyle(feature.properties, layer.layerType);
      };

      // 点要素渲染函数
      const pointToLayerFunc = layer.layerType === 'facility_point'
        ? (feature: { properties?: Record<string, unknown> }, latlng: L.LatLng) => {
            const style = getFeatureStyle(feature?.properties, layer.layerType);
            return L.circleMarker(latlng, {
              radius: style.radius || 8,
              fillColor: style.fillColor || 'blue',
              color: '#fff',
              weight: 2,
              opacity: 1,
              fillOpacity: 0.8,
            });
          }
        : undefined;

      return { layer, styleFunc, pointToLayerFunc };
    });
  }, [layers, L]);

  if (!mounted || !L) {
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
        <MapContainer
          center={center}
          zoom={zoom}
          style={{ height: '100%', width: '100%' }}
          scrollWheelZoom={true}
        >
          <TileLayer
            attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          />
          {layerRenderers.map(({ layer, styleFunc, pointToLayerFunc }, index) => (
            <GeoJSON
              key={`layer-${index}-${layer.layerName}`}
              data={layer.geojson}
              style={styleFunc}
              pointToLayer={pointToLayerFunc}
            />
          ))}
        </MapContainer>
      </div>
    </div>
  );
}