'use client';

/**
 * LegendPanel - GIS图层图例组件
 *
 * 根据活动图层动态生成图例，支持多图层分组显示。
 * 样式与几何类型匹配（面/线/点）。
 */

import { useEffect, useMemo, useState, type CSSProperties } from 'react';
import { faChevronDown, faChevronRight, faList } from '@fortawesome/free-solid-svg-icons';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import {
  getLegendForLayerType,
  getLegendItemsForLayers,
  LegendItem,
  LayerType,
  PLANNING_COLORS,
  LAYER_TYPE_LABELS,
} from '@/features/planning/constants/gis';
import type { GISLayerConfig } from '@/types/message/message-types';

interface LegendPanelProps {
  /** List of active layer types to display */
  layerTypes?: LayerType[];
  /** Active layer data; when provided, only categories present in GeoJSON are shown. */
  layers?: GISLayerConfig[];
  /** Position of legend panel */
  position?: 'bottom-right' | 'bottom-left' | 'top-right' | 'top-left';
  /** Whether to show all legends (default: only show if layerTypes provided) */
  showAll?: boolean;
  /** Custom title for legend */
  title?: string;
  /** Custom class name */
  className?: string;
  /** Collapse the legend into a small map control when space is limited. */
  collapsible?: boolean;
  /** Initial state for a collapsible legend. */
  defaultCollapsed?: boolean;
}

// Position styles mapping
const POSITION_STYLES: Record<string, CSSProperties> = {
  'bottom-right': { bottom: 32, right: 10 },
  'bottom-left': { bottom: 32, left: 10 },
  'top-right': { top: 10, right: 10 },
  'top-left': { top: 10, left: 10 },
};

export default function LegendPanel({
  layerTypes,
  layers,
  position = 'bottom-right',
  showAll = false,
  title = '图例',
  className = '',
  collapsible = false,
  defaultCollapsed = false,
}: LegendPanelProps) {
  const [collapsed, setCollapsed] = useState(collapsible && defaultCollapsed);
  const [isNarrow, setIsNarrow] = useState(false);
  const [openGroups, setOpenGroups] = useState<Set<LayerType>>(new Set());
  const canCollapse = collapsible || isNarrow;

  useEffect(() => {
    const media = window.matchMedia('(max-width: 640px)');
    const sync = () => {
      setIsNarrow(media.matches);
      if (media.matches) setCollapsed(true);
    };
    sync();
    media.addEventListener('change', sync);
    return () => media.removeEventListener('change', sync);
  }, []);
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

  useEffect(() => {
    setOpenGroups(new Set(displayLayerTypes));
  }, [displayLayerTypes]);

  // Build legend data grouped by layer type
  const legendData = useMemo(() => {
    const result: Partial<Record<LayerType, LegendItem[]>> = {};

    for (const layerType of displayLayerTypes) {
      const matchingLayers = layers?.filter((layer) => layer.layerType === layerType) || [];
      const items = matchingLayers.length > 0
        ? getLegendItemsForLayers(layerType, matchingLayers)
        : getLegendForLayerType(layerType);
      if (items.length > 0) {
        result[layerType] = items;
      }
    }

    return result;
  }, [displayLayerTypes, layers]);

  // Don't render if no legends
  if (Object.keys(legendData).length === 0) {
    return null;
  }

  if (canCollapse && collapsed) {
    return (
      <button
        type="button"
        onClick={() => setCollapsed(false)}
        className={`legend-panel flex h-8 w-8 items-center justify-center rounded border border-slate-200 bg-white/95 text-slate-600 shadow-md hover:bg-white ${className}`}
        style={{ position: 'absolute', zIndex: 20, ...POSITION_STYLES[position] }}
        title="展开图例"
        aria-label="展开图例"
      >
        <FontAwesomeIcon icon={faList} style={{ width: 13, height: 13 }} />
      </button>
    );
  }

  return (
    <div
      className={`legend-panel ${className}`}
      style={{
        position: 'absolute',
        backgroundColor: 'white',
        padding: '8px 10px',
        borderRadius: '4px',
        border: '1px solid #e2e8f0',
        boxShadow: '0 4px 14px rgba(15,23,42,0.16)',
        width: 210,
        maxWidth: 'calc(100% - 20px)',
        maxHeight: 'min(320px, calc(100% - 64px))',
        overflowY: 'auto',
        zIndex: 20,
        ...POSITION_STYLES[position],
      }}
    >
      {/* Title */}
      <div
        className="flex items-center justify-between gap-3"
        style={{
          fontWeight: 'bold',
          marginBottom: '6px',
          fontSize: '12px',
        }}
      >
        <span>{title} · {Object.keys(legendData).length} 层</span>
        {canCollapse && (
          <button
            type="button"
            onClick={() => setCollapsed(true)}
            className="w-6 h-6 flex items-center justify-center rounded hover:bg-slate-100 text-slate-500"
            title="收起图例"
            aria-label="收起图例"
          >
            <FontAwesomeIcon icon={faChevronDown} style={{ width: 10, height: 10 }} />
          </button>
        )}
      </div>

      {/* Legend items grouped by layer type */}
      {Object.entries(legendData).map(([layerType, items]) => (
        <div key={layerType} className="border-t border-slate-100 first:border-t-0">
          <button
            type="button"
            onClick={() => setOpenGroups((current) => {
              const next = new Set(current);
              if (next.has(layerType as LayerType)) next.delete(layerType as LayerType);
              else next.add(layerType as LayerType);
              return next;
            })}
            className="flex w-full items-center gap-1.5 py-1.5 text-left text-[11px] font-medium text-slate-600 hover:text-slate-900"
            aria-expanded={openGroups.has(layerType as LayerType)}
          >
            <FontAwesomeIcon
              icon={openGroups.has(layerType as LayerType) ? faChevronDown : faChevronRight}
              className="shrink-0 text-slate-400"
              style={{ width: 8, height: 8 }}
            />
            <span className="min-w-0 flex-1 truncate">
              {LAYER_TYPE_LABELS[layerType as LayerType] || layerType}
            </span>
            <span className="flex shrink-0 -space-x-0.5" aria-hidden="true">
              {items.slice(0, 4).map((item, index) => (
                <span
                  key={`${item.label}-${index}`}
                  className="h-2.5 w-2.5 rounded-sm border border-white"
                  style={{ backgroundColor: item.color }}
                />
              ))}
            </span>
            <span className="w-4 shrink-0 text-right text-[9px] text-slate-400">{items.length}</span>
          </button>

          {openGroups.has(layerType as LayerType) && (
            <div className="pb-1 pl-3">
              {renderGroupedLegendItems(items)}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

function renderGroupedLegendItems(items: LegendItem[]) {
  const groups = new Map<string, LegendItem[]>();
  for (const item of items) {
    const key = item.group || '';
    const bucket = groups.get(key) || [];
    bucket.push(item);
    groups.set(key, bucket);
  }

  return Array.from(groups.entries()).map(([group, groupItems]) => (
    <div key={group || 'default'}>
      {group && (
        <div className="mb-1 mt-1 truncate text-[10px] font-medium text-slate-500" title={group}>
          {group}
        </div>
      )}
      {groupItems.map((item, index) => (
        <LegendItemRenderer key={`${group}-${item.label}-${index}`} item={item} />
      ))}
    </div>
  ));
}

/**
 * Render a single legend item based on geometry type
 */
function LegendItemRenderer({ item }: { item: LegendItem }) {
  const { label, color, type, borderColor, lineWidth, dashed, fillOpacity } = item;

  if (type === 'line') {
    // Line legend item
    return (
      <div style={{ margin: '5px 0', display: 'flex', alignItems: 'center' }}>
        <span
          style={{
            background: dashed
              ? `repeating-linear-gradient(to right, ${color} 0 7px, transparent 7px 12px)`
              : color,
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
  const opacity = typeof fillOpacity === 'number' ? Math.max(fillOpacity, 0.12) : 0.7;
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
          opacity,
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
