'use client';

/**
 * GisResultCard - GIS analysis result card for MessageList
 *
 * Uses lazy-load fold mode: map only renders when expanded,
 * and at most 2 map instances are active simultaneously.
 * Consumes incremental layer updates from store + auto-validates.
 */

import React, { useState, useCallback, useRef, useEffect } from 'react';
import type { GisResultMessage } from '../../types';
import type { GISLayerConfig } from '@/types/message/message-types';
import { parseTimestamp } from '@/features/planning/utils';
import MarkdownRenderer from '@/features/planning/components/ui/MarkdownRenderer';
import { MapView, ValidationPanel } from '../gis';
import { useGisLayers } from '../../hooks';
import { gisTestApi, type LayoutValidationResult } from '@/features/gis-test/api/gis-test-api';

// Track active map instances globally (limit to 2)
const activeMaps = new Set<symbol>();
const MAX_ACTIVE_MAPS = 2;

interface GisResultCardProps {
  message: GisResultMessage;
}

function GisResultCard({ message }: GisResultCardProps) {
  const [expanded, setExpanded] = useState(false);
  const mapId = useRef(Symbol('gis-map'));
  const [validationResult, setValidationResult] = useState<LayoutValidationResult | null>(null);

  // Consume incremental layers from store (populated by gis_layer_update SSE)
  const storeLayers = useGisLayers();

  // Prefer message.layers (final result), fall back to store incremental layers
  const allLayers: GISLayerConfig[] = message.layers && message.layers.length > 0
    ? message.layers
    : storeLayers;

  // Auto-validate when planning_zone layers appear
  useEffect(() => {
    if (!allLayers || allLayers.length === 0) return;
    const planningLayers = allLayers.filter(l => l.layerType === 'planning_zone');
    if (planningLayers.length === 0) return;
    gisTestApi.validateLayout({ layout_configs: planningLayers, use_jintian_data: true })
      .then(setValidationResult)
      .catch(() => {});
  }, [allLayers]);

  // When expanding, enforce the global active map limit
  const handleToggle = useCallback(() => {
    if (!expanded) {
      // Evict oldest map if at limit
      if (activeMaps.size >= MAX_ACTIVE_MAPS) {
        const oldest = activeMaps.values().next().value;
        if (oldest) activeMaps.delete(oldest);
      }
      activeMaps.add(mapId.current);
      setExpanded(true);
    } else {
      activeMaps.delete(mapId.current);
      setExpanded(false);
    }
  }, [expanded]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      activeMaps.delete(mapId.current);
    };
  }, []);

  const hasLayers = allLayers && allLayers.length > 0;
  const layerCount = hasLayers ? allLayers!.length : 0;

  return (
    <div className="flex justify-start mb-4">
      <div className="max-w-[85%] bg-white border border-gray-200 rounded-2xl px-4 py-3 shadow-sm">
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

        {/* Map - lazy load with fold */}
        {hasLayers && (
          <div className="mb-3">
            <button
              onClick={handleToggle}
              className="w-full flex items-center justify-between px-3 py-2 bg-gray-50 hover:bg-gray-100 rounded-lg text-sm text-gray-700 transition-colors"
            >
              <span className="flex items-center gap-2">
                <i className="fas fa-map" />
                {expanded ? '收起地图' : `查看地图 (${layerCount} 图层)`}
              </span>
              <i className={`fas fa-chevron-${expanded ? 'up' : 'down'} text-xs`} />
            </button>
            {expanded && (
              <div className="mt-2">
                <MapView
                  layers={allLayers!}
                  center={message.mapOptions?.center}
                  zoom={message.mapOptions?.zoom}
                  height="300px"
                />
              </div>
            )}
          </div>
        )}

        {/* Validation result */}
        {validationResult && (
          <div className="mb-3 border-t border-gray-100 pt-2">
            <ValidationPanel result={validationResult} />
          </div>
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
