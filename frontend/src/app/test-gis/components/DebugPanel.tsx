'use client';

import type { GISLayerConfig } from '@/types/message/message-types';
import { PLANNING_COLORS } from '@/lib/constants/gis';

interface DebugPanelProps {
  layers: GISLayerConfig[];
}

export default function DebugPanel({ layers }: DebugPanelProps) {
  if (layers.length === 0) return null;

  return (
    <div className="mt-6 p-4 bg-gray-50 rounded-lg border border-gray-200">
      <h2 className="text-lg font-semibold mb-4">图层调试信息</h2>

      <div className="space-y-4">
        {layers.map((layer, index) => (
          <div key={index} className="p-3 bg-white rounded border">
            <div className="flex items-center gap-2 mb-2">
              <span className="font-medium text-sm">{layer.layerName}</span>
              <span className="text-xs bg-blue-100 text-blue-800 px-2 py-0.5 rounded">
                {layer.layerType}
              </span>
              <span className="text-xs text-gray-500">
                {layer.geojson?.features?.length ?? 0} features
              </span>
            </div>

            {/* First feature properties */}
            {layer.geojson?.features?.[0] && (
              <div className="mt-2">
                <p className="text-xs text-gray-500 mb-1">首个要素属性:</p>
                <pre className="text-xs bg-gray-100 p-2 rounded overflow-auto max-h-24">
                  {JSON.stringify(layer.geojson.features[0].properties, null, 2)}
                </pre>
              </div>
            )}

            {/* Color mapping result */}
            <div className="mt-2">
              <p className="text-xs text-gray-500 mb-1">样式映射:</p>
              <div className="flex flex-wrap gap-2">
                {layer.layerType === 'infrastructure' && (
                  <>
                    <span className="text-xs bg-gray-200 px-2 py-0.5 rounded">
                      道路: {PLANNING_COLORS.infrastructure['道路']?.stroke}
                    </span>
                    <span className="text-xs bg-gray-300 px-2 py-0.5 rounded">
                      乡道: {PLANNING_COLORS.infrastructure['乡道']?.stroke}
                    </span>
                    <span className="text-xs bg-blue-200 px-2 py-0.5 rounded">
                      河流: {PLANNING_COLORS.infrastructure['河流']?.stroke}
                    </span>
                  </>
                )}
                {layer.layerType === 'facility_point' && (
                  <span className="text-xs bg-green-200 px-2 py-0.5 rounded">
                    现状保留: {PLANNING_COLORS.facility_point['现状保留']?.fill}
                  </span>
                )}
                {layer.layerType === 'boundary' && (
                  <span className="text-xs bg-gray-400 px-2 py-0.5 rounded">
                    行政边界: {PLANNING_COLORS.boundary['行政边界']?.stroke}
                  </span>
                )}
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}