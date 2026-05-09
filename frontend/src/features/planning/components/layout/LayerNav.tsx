'use client';

import React, { useCallback, useMemo, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { faComments, faCompass, faChevronDown } from '@fortawesome/free-solid-svg-icons';
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

function getStatusColor(status: string, isExecuting: boolean): string {
  if (isExecuting) return 'bg-amber-400 animate-pulse';
  if (status === 'completed') return 'bg-emerald-400';
  if (status === 'streaming') return 'bg-blue-400 animate-pulse';
  return 'bg-slate-300';
}

export default function LayerNav() {
  const selectedNavigationKey = usePlanningStore((state) => state.selectedNavigationKey);
  const setSelectedNavigationKey = usePlanningStore((state) => state.setSelectedNavigationKey);
  const dimensionProgress = useDimensionProgressAll();
  const currentLayer = useCurrentLayer();
  const completedLayers = useCompletedLayers();
  const executingDimensions = useExecutingDimensions();

  const [expandedLayers, setExpandedLayers] = useState<Set<number>>(new Set([1, 2, 3]));

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
    return result;
  }, [dimensionProgress]);

  const navItems = [
    { key: NAV_KEYS.OVERVIEW, icon: faCompass, label: '总览' },
    { key: NAV_KEYS.CHAT, icon: faComments, label: '对话' },
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
                ? 'bg-emerald-50 text-emerald-700 font-medium'
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
                  isCurrentLayer ? 'bg-emerald-50/70 text-emerald-700' : 'hover:bg-slate-50 text-slate-500'
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
                  {layerComplete && <span className="text-xs text-emerald-400">OK</span>}
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
                                ? 'bg-emerald-50 text-emerald-700 font-medium'
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
    </nav>
  );
}
