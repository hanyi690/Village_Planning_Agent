'use client';

/**
 * GisResultCard - GIS analysis result card for MessageList
 *
 * Uses lazy-load fold mode: map only renders when expanded,
 * and at most 2 map instances are active simultaneously.
 */

import React, { useState, useCallback, useRef, useEffect } from 'react';
import type { GisResultMessage } from '../../types';
import { parseTimestamp } from '@/features/planning/utils';
import MarkdownRenderer from '@/features/planning/components/ui/MarkdownRenderer';
import { MapView } from '../gis';

// Track active map instances globally (limit to 2)
const activeMaps = new Set<symbol>();
const MAX_ACTIVE_MAPS = 2;

interface GisResultCardProps {
  message: GisResultMessage;
}

function GisResultCard({ message }: GisResultCardProps) {
  const [expanded, setExpanded] = useState(false);
  const mapId = useRef(Symbol('gis-map'));

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

  const hasLayers = message.layers && message.layers.length > 0;

  return (
    <div className="flex justify-start mb-4">
      <div className="max-w-[85%] bg-white border border-gray-200 rounded-2xl px-4 py-3 shadow-sm">
        {/* Title */}
        <div className="flex items-center gap-2 mb-3 pb-2 border-b border-gray-100">
          <i className="fas fa-map-marked-alt text-blue-600" />
          <span className="font-medium text-gray-800">
            {message.dimensionName} - GIS Analysis
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
                <span className="text-gray-500">Score:</span>
                <span className="font-medium ml-1">{message.analysisData.overallScore}/100</span>
              </div>
            )}
            {message.analysisData.suitabilityLevel && (
              <div className="bg-gray-50 rounded px-2 py-1">
                <span className="text-gray-500">Suitability:</span>
                <span className="font-medium ml-1">{message.analysisData.suitabilityLevel}</span>
              </div>
            )}
            {message.analysisData.sensitivityClass && (
              <div className="bg-gray-50 rounded px-2 py-1">
                <span className="text-gray-500">Sensitivity:</span>
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
                {expanded ? 'Collapse Map' : `Show Map (${message.layers!.length} layers)`}
              </span>
              <i className={`fas fa-chevron-${expanded ? 'up' : 'down'} text-xs`} />
            </button>
            {expanded && (
              <div className="mt-2">
                <MapView
                  layers={message.layers!}
                  center={message.mapOptions?.center}
                  zoom={message.mapOptions?.zoom}
                  height="300px"
                />
              </div>
            )}
          </div>
        )}

        {/* Recommendations */}
        {message.analysisData?.recommendations &&
          message.analysisData.recommendations.length > 0 && (
            <div className="text-sm text-gray-600">
              <div className="font-medium mb-1">Recommendations:</div>
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
            return date ? date.toLocaleTimeString() : 'Just now';
          })()}
        </div>
      </div>
    </div>
  );
}

export default React.memo(GisResultCard);
