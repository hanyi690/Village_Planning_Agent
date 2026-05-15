'use client';

import React, { useCallback, useMemo, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { faCompass, faChevronDown, faChevronUp } from '@fortawesome/free-solid-svg-icons';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';

import { usePlanningStore } from '../../store';
import {
  useDimensionProgressAll,
  useCurrentLayer,
  useCompletedLayers,
  useExecutingDimensions,
} from '../../hooks';
import { getDimensionName } from '../../config/dimensions';
import { LAYER_VALUE_MAP, LAYER_IDS, NAV_KEYS } from '@/features/planning/constants';
import ToolStatusPanel from '../chat/ToolStatusPanel';

function getStatusColor(status: string, isExecuting: boolean): string {
  if (isExecuting) return 'bg-amber-400 animate-pulse';
  if (status === 'completed') return 'bg-emerald-500';
  if (status === 'streaming') return 'bg-[#0ea5e9] animate-pulse';
  return 'bg-slate-400';
}

export default function LayerNav() {
  const selectedNavigationKey = usePlanningStore((state) => state.selectedNavigationKey);
  const setSelectedNavigationKey = usePlanningStore((state) => state.setSelectedNavigationKey);
  const dimensionProgress = useDimensionProgressAll();
  const currentLayer = useCurrentLayer();
  const completedLayers = useCompletedLayers();
  const executingDimensions = useExecutingDimensions();
  const toolStatuses = usePlanningStore((state) => state.toolStatuses);
  const reports = usePlanningStore((state) => state.reports);

  const [expandedLayers, setExpandedLayers] = useState<Set<number>>(new Set([1, 2, 3]));
  const [showTools, setShowTools] = useState(false);

  const toggleLayer = useCallback((layer: number) => {
    setExpandedLayers((prev) => {
      const next = new Set(prev);
      if (next.has(layer)) next.delete(layer);
      else next.add(layer);
      return next;
    });
  }, []);

  const layerDimensions = useMemo(() => {
    const result: Record<number, Array<{ key: string; name: string; status: string }>> = {
      1: [],
      2: [],
      3: [],
    };

    // 1. From dimensionProgress (executing or completed dimensions)
    Object.entries(dimensionProgress).forEach(([key, item]) => {
      const layer = item.layer;
      if (layer >= 1 && layer <= 3) {
        result[layer].push({
          key,
          name: getDimensionName(item.dimensionKey),
          status: item.status,
        });
      }
    });

    // 2. From reports (defensive: handle page refresh where dimensionProgress is empty)
    for (const layer of [1, 2, 3] as const) {
      const layerKey = `layer${layer}` as const;
      const layerReports = reports[layerKey] || {};
      const existingKeys = result[layer].map((d) => d.key);
      for (const dimKey of Object.keys(layerReports)) {
        const key = `${layer}_${dimKey}`;
        const content = layerReports[dimKey];
        if (!existingKeys.includes(key) && content && typeof content === 'string' && content.length > 0) {
          result[layer].push({
            key,
            name: getDimensionName(dimKey),
            status: 'completed',
          });
        }
      }
    }

    return result;
  }, [dimensionProgress, reports]);

  const navItems = [
    { key: NAV_KEYS.OVERVIEW, icon: faCompass, label: '总览' },
  ];

  return (
    <nav className="w-[280px] h-full bg-white border-r border-slate-200 flex flex-col shrink-0 overflow-y-auto">
      <div className="px-4 py-3 space-y-0.5 border-b border-slate-100">
        {navItems.map((item) => (
          <button
            key={item.key}
            onClick={() => setSelectedNavigationKey(item.key)}
            className={`w-full flex items-center gap-2 px-3 py-2.5 rounded-lg text-base transition-colors ${
              selectedNavigationKey === item.key
                ? 'bg-[#e0f2fe] text-[#0369a1] font-medium'
                : 'text-slate-600 hover:bg-slate-50'
            }`}
          >
            <FontAwesomeIcon icon={item.icon} style={{ width: 16, height: 16 }} />
            <span>{item.label}</span>
          </button>
        ))}
      </div>

      <div className="flex-1 overflow-y-auto px-3 py-3">
        {LAYER_IDS.map((layer) => {
          const dimensions = layerDimensions[layer];
          const isCurrentLayer = currentLayer === layer;
          const layerComplete = completedLayers[layer as 1 | 2 | 3];
          const isExpanded = expandedLayers.has(layer);

          if (dimensions.length === 0 && layerComplete) return null;

          return (
            <div key={layer} className="mb-1">
              <button
                onClick={() => toggleLayer(layer)}
                className={`w-full flex items-center justify-between px-3 py-2 rounded-md text-sm transition-colors ${
                  isCurrentLayer ? 'bg-[#e0f2fe]/70 text-[#0369a1]' : 'hover:bg-slate-50 text-slate-600'
                }`}
              >
                <div className="flex items-center gap-1.5">
                  <motion.span
                    animate={{ rotate: isExpanded ? 0 : -90 }}
                    transition={{ duration: 0.15 }}
                  >
                    <FontAwesomeIcon icon={faChevronDown} style={{ width: 12, height: 12 }} />
                  </motion.span>
                  <span className="font-medium uppercase tracking-wider">L{layer}</span>
                  <span className="text-slate-400">{LAYER_VALUE_MAP[layer]}</span>
                  {layerComplete && <span className="text-xs text-emerald-600">OK</span>}
                </div>
                {dimensions.length > 0 && (
                  <span className="text-xs text-slate-400">{dimensions.length}</span>
                )}
              </button>

              <AnimatePresence>
                {isExpanded && (
                  <motion.div
                    initial={{ height: 0, opacity: 0 }}
                    animate={{ height: 'auto', opacity: 1 }}
                    exit={{ height: 0, opacity: 0 }}
                    transition={{ duration: 0.15 }}
                    className="overflow-hidden"
                  >
                    {dimensions.length === 0 && isCurrentLayer ? (
                      <div className="px-4 py-2 text-xs text-slate-400">等待维度分析...</div>
                    ) : (
                      dimensions.map((dim) => {
                        const navKey = NAV_KEYS.dim(dim.key);
                        const isSelected = selectedNavigationKey === navKey;
                        const isExecuting = executingDimensions.includes(dim.key);

                        return (
                          <button
                            key={dim.key}
                            onClick={() => setSelectedNavigationKey(navKey)}
                            className={`w-full flex items-center gap-2 pl-10 pr-3 py-2 rounded-md text-sm transition-colors ${
                              isSelected
                                ? 'bg-[#e0f2fe] text-[#0369a1] font-medium'
                                : 'text-slate-600 hover:bg-slate-50'
                            }`}
                          >
                            <span
                              className={`w-2 h-2 rounded-full shrink-0 ${getStatusColor(
                                dim.status,
                                isExecuting
                              )}`}
                            />
                            <span className="truncate">{dim.name}</span>
                          </button>
                        );
                      })
                    )}
                  </motion.div>
                )}
              </AnimatePresence>
            </div>
          );
        })}
      </div>

      {/* Bottom: Tool Status Panel */}
      {Object.keys(toolStatuses).length > 0 && (
        <div className="shrink-0 border-t border-slate-200">
          <button
            onClick={() => setShowTools(!showTools)}
            className="w-full flex items-center justify-between px-4 py-2 text-sm text-slate-600 hover:bg-slate-50"
          >
            <span className="flex items-center gap-2">
              <span>🔧 工具</span>
              <span className="text-xs text-slate-400">{Object.keys(toolStatuses).length}</span>
            </span>
            <FontAwesomeIcon
              icon={showTools ? faChevronUp : faChevronDown}
              style={{ width: 12, height: 12 }}
            />
          </button>
          <AnimatePresence>
            {showTools && (
              <motion.div
                initial={{ height: 0, opacity: 0 }}
                animate={{ height: 'auto', opacity: 1 }}
                exit={{ height: 0, opacity: 0 }}
                className="overflow-hidden"
              >
                <div className="px-2 pb-2">
                  <ToolStatusPanel tools={toolStatuses} maxVisible={3} />
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      )}
    </nav>
  );
}
