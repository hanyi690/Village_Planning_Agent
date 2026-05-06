'use client';

import { useState, useCallback } from 'react';

// ============================================
// Types
// ============================================

export type BasemapType = 'vector' | 'image' | 'terrain';

interface LayerVisibility {
  zones: boolean;
  facilities: boolean;
  axes: boolean;
  boundary: boolean;
  roads: boolean;
}

interface MapControlsProps {
  basemap?: BasemapType;
  onBasemapChange?: (basemap: BasemapType) => void;
  zoom?: number;
  onZoomChange?: (zoom: number) => void;
  layerVisibility?: LayerVisibility;
  onLayerVisibilityChange?: (visibility: LayerVisibility) => void;
  center?: [number, number];
}

// ============================================
// Default Values
// ============================================

const DEFAULT_LAYER_VISIBILITY: LayerVisibility = {
  zones: true,
  facilities: true,
  axes: true,
  boundary: true,
  roads: true,
};

// ============================================
// Main Component
// ============================================

export default function MapControls({
  basemap = 'vector',
  onBasemapChange,
  zoom = 14,
  onZoomChange,
  layerVisibility = DEFAULT_LAYER_VISIBILITY,
  onLayerVisibilityChange,
}: MapControlsProps) {
  const [localBasemap, setLocalBasemap] = useState<BasemapType>(basemap);
  const [localZoom, setLocalZoom] = useState(zoom);
  const [localVisibility, setLocalVisibility] = useState(layerVisibility);

  const handleBasemapChange = useCallback((type: BasemapType) => {
    setLocalBasemap(type);
    onBasemapChange?.(type);
  }, [onBasemapChange]);

  const handleZoomChange = useCallback((delta: number) => {
    const newZoom = Math.max(10, Math.min(18, localZoom + delta));
    setLocalZoom(newZoom);
    onZoomChange?.(newZoom);
  }, [localZoom, onZoomChange]);

  const handleVisibilityChange = useCallback((layer: keyof LayerVisibility) => {
    const newVisibility = { ...localVisibility, [layer]: !localVisibility[layer] };
    setLocalVisibility(newVisibility);
    onLayerVisibilityChange?.(newVisibility);
  }, [localVisibility, onLayerVisibilityChange]);

  return (
    <div className="bg-white border rounded-lg p-2 shadow-sm">
      {/* Basemap Toggle */}
      <div className="mb-2">
        <label className="block text-xs text-gray-600 mb-1">底图类型</label>
        <div className="flex gap-1">
          {(['vector', 'image', 'terrain'] as BasemapType[]).map((type) => (
            <button
              key={type}
              onClick={() => handleBasemapChange(type)}
              className={`px-2 py-1 rounded text-xs ${
                localBasemap === type
                  ? 'bg-blue-500 text-white'
                  : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
              }`}
            >
              {type === 'vector' ? '矢量' : type === 'image' ? '影像' : '地形'}
            </button>
          ))}
        </div>
      </div>

      {/* Zoom Control */}
      <div className="mb-2">
        <label className="block text-xs text-gray-600 mb-1">缩放级别: {localZoom}</label>
        <div className="flex gap-1">
          <button
            onClick={() => handleZoomChange(-1)}
            className="w-8 h-8 rounded bg-gray-100 hover:bg-gray-200 text-gray-700 flex items-center justify-center"
          >
            −
          </button>
          <button
            onClick={() => handleZoomChange(1)}
            className="w-8 h-8 rounded bg-gray-100 hover:bg-gray-200 text-gray-700 flex items-center justify-center"
          >
            +
          </button>
          <button
            onClick={() => { setLocalZoom(14); onZoomChange?.(14); }}
            className="px-2 h-8 rounded bg-gray-100 hover:bg-gray-200 text-gray-700 text-xs"
          >
            重置
          </button>
        </div>
      </div>

      {/* Layer Visibility */}
      <div>
        <label className="block text-xs text-gray-600 mb-1">图层可见性</label>
        <div className="grid grid-cols-2 gap-1">
          {([
            { key: 'zones', label: '用地分区', color: '#FFD700' },
            { key: 'facilities', label: '公共设施', color: '#4A90D9' },
            { key: 'axes', label: '发展轴线', color: '#808080' },
            { key: 'boundary', label: '边界', color: '#9370DB' },
            { key: 'roads', label: '道路网络', color: '#333' },
          ] as { key: keyof LayerVisibility; label: string; color: string }[]).map(
            ({ key, label, color }) => (
              <button
                key={key}
                onClick={() => handleVisibilityChange(key)}
                className={`flex items-center gap-1 px-2 py-1 rounded text-xs ${
                  localVisibility[key]
                    ? 'bg-gray-100 text-gray-700'
                    : 'bg-gray-50 text-gray-400'
                }`}
              >
                <span
                  className={`w-3 h-3 rounded ${localVisibility[key] ? '' : 'opacity-30'}`}
                  style={{ backgroundColor: color }}
                />
                <span>{label}</span>
              </button>
            )
          )}
        </div>
      </div>
    </div>
  );
}