'use client';

/**
 * GisResultCard - GIS analysis result card for MessageList
 *
 * The message card is intentionally lightweight. The complete spatial layout
 * belongs to the Map tab, which avoids mounting a second map inside chat.
 */

import React from 'react';
import type { GisResultMessage } from '../../types';
import type { GISLayerConfig } from '@/types/message/message-types';
import { parseTimestamp } from '@/features/planning/utils';
import MarkdownRenderer from '@/features/planning/components/ui/MarkdownRenderer';
import { useGisLayers } from '../../hooks';
import { usePlanningStore } from '../../store';

interface GisResultCardProps {
  message: GisResultMessage;
}

function GisResultCard({ message }: GisResultCardProps) {
  const storeLayers = useGisLayers();
  const setProcessPanelTab = usePlanningStore((s) => s.setProcessPanelTab);
  const setRightPanelExpanded = usePlanningStore((s) => s.setRightPanelExpanded);
  const addGisLayersFromUpload = usePlanningStore((s) => s.addGisLayersFromUpload);

  // Prefer message.layers (final result), fall back to store incremental layers
  const allLayers: GISLayerConfig[] = message.layers && message.layers.length > 0
    ? message.layers
    : storeLayers;

  const hasLayers = allLayers && allLayers.length > 0;
  const layerCount = hasLayers ? allLayers!.length : 0;

  const openMap = () => {
    // Historical GIS messages may contain layers before the map store is restored.
    if (storeLayers.length === 0 && message.layers?.length) {
      addGisLayersFromUpload(message.layers as unknown as Array<Record<string, unknown>>);
    }
    setRightPanelExpanded(true);
    setProcessPanelTab('map');
  };

  return (
    <div className="flex justify-start mb-4">
      <div className="w-full bg-white border border-slate-200 rounded-lg px-3 py-3 shadow-sm">
        {/* Title */}
        <div className="flex items-center gap-2 mb-3 pb-2 border-b border-gray-100">
          <i className="fas fa-map-marked-alt text-blue-600" />
          <span className="font-medium text-gray-800">
            {message.dimensionName} - GIS 分析
          </span>
        </div>

        {/* Summary */}
        {message.summary && (
          <div className="mb-3 text-sm text-gray-600">
            <MarkdownRenderer content={message.summary} />
          </div>
        )}

        {/* Analysis Data */}
        {message.analysisData && (
          <div className="mb-3 grid grid-cols-2 gap-2 text-sm">
            {message.analysisData.overallScore !== undefined && (
              <div className="bg-gray-50 rounded px-2 py-1">
                <span className="text-gray-500">评分:</span>
                <span className="font-medium ml-1">{message.analysisData.overallScore}/100</span>
              </div>
            )}
            {message.analysisData.suitabilityLevel && (
              <div className="bg-gray-50 rounded px-2 py-1">
                <span className="text-gray-500">适宜性:</span>
                <span className="font-medium ml-1">{message.analysisData.suitabilityLevel}</span>
              </div>
            )}
            {message.analysisData.sensitivityClass && (
              <div className="bg-gray-50 rounded px-2 py-1">
                <span className="text-gray-500">敏感性:</span>
                <span className="font-medium ml-1">{message.analysisData.sensitivityClass}</span>
              </div>
            )}
          </div>
        )}

        {/* Spatial results are rendered in the dedicated Map tab. */}
        {hasLayers && (
          <button
            onClick={openMap}
            className="w-full flex items-center justify-between px-3 py-2.5 bg-sky-50 hover:bg-sky-100 border border-sky-200 rounded-lg text-sm text-sky-700 transition-colors"
          >
            <span className="flex items-center gap-2">
              <i className="fas fa-map" />
              在地图中查看
            </span>
            <span className="text-xs text-sky-600">{layerCount} 个图层</span>
          </button>
        )}

        {/* Recommendations */}
        {message.analysisData?.recommendations &&
          message.analysisData.recommendations.length > 0 && (
            <div className="text-sm text-gray-600">
              <div className="font-medium mb-1">建议:</div>
              <ul className="list-disc list-inside space-y-1">
                {message.analysisData.recommendations.slice(0, 3).map((rec, i) => (
                  <li key={i}>{rec}</li>
                ))}
              </ul>
            </div>
          )}

        {/* Timestamp */}
        <div className="text-xs opacity-60 mt-2 text-right">
          {(() => {
            const date = parseTimestamp(message.timestamp);
            return date ? date.toLocaleTimeString() : '刚刚';
          })()}
        </div>
      </div>
    </div>
  );
}

export default React.memo(GisResultCard);
