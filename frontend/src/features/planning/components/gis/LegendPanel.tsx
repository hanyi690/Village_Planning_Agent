'use client';

/**
 * LegendPanel - GIS图层图例组件
 *
 * 根据活动图层动态生成图例，支持多图层分组显示。
 * 样式与几何类型匹配（面/线/点）。
 */

import { useMemo } from 'react';
import {
  getLegendForLayerType,
  LegendItem,
  LayerType,
  PLANNING_COLORS,
} from '@/lib/constants/gis';

interface LegendPanelProps {
  /** List of active layer types to display */
  layerTypes?: LayerType[];
  /** Position of legend panel */
  position?: 'bottom-right' | 'bottom-left' | 'top-right' | 'top-left';
  /** Whether to show all legends (default: only show if layerTypes provided) */
  showAll?: boolean;
  /** Custom title for legend */
  title?: string;
  /** Custom class name */
  className?: string;
}

// Position styles mapping
const POSITION_STYLES: Record<string, string> = {
  'bottom-right': 'bottom: 50px; right: 10px;',
  'bottom-left': 'bottom: 50px; left: 10px;',
  'top-right': 'top: 10px; right: 10px;',
  'top-left': 'top: 10px; left: 10px;',
};

// Layer type display names
const LAYER_TYPE_NAMES: Record<LayerType, string> = {
  function_zone: '功能区',
  facility_point: '设施点',
  development_axis: '发展轴线',
  sensitivity_zone: '敏感区',
  isochrone: '等时圈',
  boundary: '边界',
  settlement_zone: '居民点分类',
  infrastructure: '基础设施',
};

export default function LegendPanel({
  layerTypes,
  position = 'bottom-right',
  showAll = false,
  title = '图例',
  className = '',
}: LegendPanelProps) {
  // Determine which layer types to display
  const displayLayerTypes = useMemo(() => {
    if (showAll) {
      return Object.keys(PLANNING_COLORS) as LayerType[];
    }
    if (layerTypes && layerTypes.length > 0) {
      return layerTypes;
    }
    return [];
  }, [layerTypes, showAll]);

  // Build legend data grouped by layer type
  const legendData = useMemo(() => {
    const result: Partial<Record<LayerType, LegendItem[]>> = {};

    for (const layerType of displayLayerTypes) {
      const items = getLegendForLayerType(layerType);
      if (items.length > 0) {
        result[layerType] = items;
      }
    }

    return result;
  }, [displayLayerTypes]);

  // Don't render if no legends
  if (Object.keys(legendData).length === 0) {
    return null;
  }

  return (
    <div
      className={`legend-panel ${className}`}
      style={{
        position: 'absolute',
        backgroundColor: 'white',
        padding: '10px 15px',
        borderRadius: '5px',
        boxShadow: '0 0 10px rgba(0,0,0,0.3)',
        maxHeight: '400px',
        overflowY: 'auto',
        zIndex: 100,
        ...(POSITION_STYLES[position]
          ? { bottom: 50, right: 10 }
          : {}),
      }}
    >
      {/* Title */}
      <div
        style={{
          fontWeight: 'bold',
          marginBottom: '10px',
          fontSize: '14px',
        }}
      >
        {title}
      </div>

      {/* Legend items grouped by layer type */}
      {Object.entries(legendData).map(([layerType, items]) => (
        <div key={layerType} style={{ marginBottom: '15px' }}>
          {/* Layer group header */}
          <div
            style={{
              fontWeight: '600',
              marginTop: '10px',
              marginBottom: '5px',
              fontSize: '12px',
              color: '#666',
            }}
          >
            {LAYER_TYPE_NAMES[layerType as LayerType] || layerType}
          </div>

          {/* Legend items */}
          {items.map((item, index) => (
            <LegendItemRenderer key={`${layerType}-${index}`} item={item} />
          ))}
        </div>
      ))}
    </div>
  );
}

/**
 * Render a single legend item based on geometry type
 */
function LegendItemRenderer({ item }: { item: LegendItem }) {
  const { label, color, type, borderColor, lineWidth } = item;

  if (type === 'line') {
    // Line legend item
    return (
      <div style={{ margin: '5px 0', display: 'flex', alignItems: 'center' }}>
        <span
          style={{
            background: color,
            width: 20 + (lineWidth || 2) * 2,
            height: lineWidth || 2,
            display: 'inline-block',
            borderRadius: '2px',
          }}
        />
        <span style={{ marginLeft: '5px', fontSize: '12px' }}>{label}</span>
      </div>
    );
  }

  if (type === 'point') {
    // Point legend item (circle)
    return (
      <div style={{ margin: '5px 0', display: 'flex', alignItems: 'center' }}>
        <span
          style={{
            background: color,
            width: 16,
            height: 16,
            display: 'inline-block',
            border: `2px solid ${borderColor || color}`,
            borderRadius: '50%',
          }}
        />
        <span style={{ marginLeft: '5px', fontSize: '12px' }}>{label}</span>
      </div>
    );
  }

  // Polygon legend item (filled rectangle)
  return (
    <div style={{ margin: '5px 0', display: 'flex', alignItems: 'center' }}>
      <span
        style={{
          background: color,
          width: 20,
          height: 20,
          display: 'inline-block',
          border: `1px solid ${borderColor || '#666'}`,
          borderRadius: '3px',
          opacity: 0.7,
        }}
      />
      <span style={{ marginLeft: '5px', fontSize: '12px' }}>{label}</span>
    </div>
  );
}

/**
 * Compact legend for single layer type
 */
export function SingleLayerLegend({
  layerType,
  title,
}: {
  layerType: LayerType;
  title?: string;
}) {
  const items = useMemo(() => getLegendForLayerType(layerType), [layerType]);

  if (items.length === 0) {
    return null;
  }

  return (
    <div
      style={{
        backgroundColor: 'white',
        padding: '8px 12px',
        borderRadius: '4px',
        boxShadow: '0 0 8px rgba(0,0,0,0.2)',
      }}
    >
      {title && (
        <div
          style={{
            fontWeight: 'bold',
            marginBottom: '5px',
            fontSize: '12px',
          }}
        >
          {title}
        </div>
      )}
      {items.map((item, index) => (
        <LegendItemRenderer key={index} item={item} />
      ))}
    </div>
  );
}