'use client';

import { useState } from 'react';

interface LayerGroup {
  name: string;
  color: string;
  layers: Array<{
    id: string;
    name: string;
    records: number;
    geometry_type: string;
    visible: boolean;
  }>;
}

interface StandardLayersPanelProps {
  layerGroups: LayerGroup[];
  onToggleLayer: (layerId: string) => void;
  onSetVisibility: (layerId: string, visible: boolean) => void;
  loading?: boolean;
}

export default function StandardLayersPanel({
  layerGroups,
  onToggleLayer,
  onSetVisibility,
  loading,
}: StandardLayersPanelProps) {
  const [expandedGroup, setExpandedGroup] = useState<string | null>('status');

  if (loading) {
    return (
      <div className="bg-white rounded-lg p-4 shadow-sm">
        <h3 className="font-semibold text-gray-800 mb-3">标准图层</h3>
        <div className="animate-pulse space-y-2">
          <div className="h-4 bg-gray-200 rounded w-3/4" />
          <div className="h-4 bg-gray-200 rounded w-1/2" />
          <div className="h-4 bg-gray-200 rounded w-2/3" />
        </div>
      </div>
    );
  }

  const totalLayers = layerGroups.reduce((sum, g) => sum + g.layers.length, 0);
  const visibleLayers = layerGroups.reduce(
    (sum, g) => sum + g.layers.filter(l => l.visible).length,
    0
  );

  return (
    <div className="bg-white rounded-lg shadow-sm">
      <div className="p-4 border-b">
        <h3 className="font-semibold text-gray-800">标准图层</h3>
        <p className="text-sm text-gray-500 mt-1">
          {totalLayers} 个图层 · {visibleLayers} 个可见
        </p>
      </div>

      <div className="divide-y">
        {layerGroups.map(group => (
          <div key={group.name}>
            <button
              onClick={() => setExpandedGroup(expandedGroup === group.name ? null : group.name)}
              className="w-full px-4 py-3 flex items-center justify-between hover:bg-gray-50"
            >
              <div className="flex items-center gap-2">
                <span
                  className="w-3 h-3 rounded-full"
                  style={{ backgroundColor: group.color }}
                />
                <span className="font-medium text-gray-700">{group.name}</span>
                <span className="text-sm text-gray-500">
                  ({group.layers.length})
                </span>
              </div>
              <svg
                className={`w-4 h-4 text-gray-400 transition-transform ${
                  expandedGroup === group.name ? 'rotate-180' : ''
                }`}
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
              >
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
              </svg>
            </button>

            {expandedGroup === group.name && (
              <div className="px-4 pb-3 space-y-1">
                {group.layers.map(layer => (
                  <div
                    key={layer.id}
                    className="flex items-center justify-between py-1"
                  >
                    <label className="flex items-center gap-2 cursor-pointer">
                      <input
                        type="checkbox"
                        checked={layer.visible}
                        onChange={() => onToggleLayer(layer.id)}
                        className="w-4 h-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                      />
                      <span className="text-sm text-gray-600">{layer.name}</span>
                    </label>
                    <span className="text-xs text-gray-400">
                      {layer.records} {layer.geometry_type}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>

      <div className="p-3 border-t bg-gray-50">
        <button
          onClick={() => {
            layerGroups.forEach(g => {
              g.layers.forEach(l => onSetVisibility(l.id, false));
            });
          }}
          className="text-xs text-gray-500 hover:text-gray-700"
        >
          清除所有
        </button>
        <span className="mx-2 text-gray-300">|</span>
        <button
          onClick={() => {
            layerGroups.forEach(g => {
              g.layers.forEach(l => onSetVisibility(l.id, true));
            });
          }}
          className="text-xs text-gray-500 hover:text-gray-700"
        >
          显示所有
        </button>
      </div>
    </div>
  );
}