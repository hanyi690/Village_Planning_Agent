'use client';

import React, { useCallback, useMemo } from 'react';
import { motion } from 'framer-motion';
import { faBars, faFileExport, faPlus } from '@fortawesome/free-solid-svg-icons';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';

import { usePlanningStore } from '../../store';
import { useStatus, useCurrentLayer, useDimensionProgressAll } from '../../hooks';
import { LAYER_IDS } from '@/features/planning/constants';

interface AppHeaderProps {
  onToggleLeftNav: () => void;
}

export default function AppHeader({ onToggleLeftNav }: AppHeaderProps) {
  const projectName = usePlanningStore((state) => state.projectName);
  const currentLayer = useCurrentLayer();
  const dimensionProgress = useDimensionProgressAll();
  const status = useStatus();

  const layerProgress = useMemo(() => {
    const result: Record<number, { done: number; total: number }> = {
      1: { done: 0, total: 0 },
      2: { done: 0, total: 0 },
      3: { done: 0, total: 0 },
    };
    Object.entries(dimensionProgress).forEach(([key, item]) => {
      const layer = item.layer;
      if (layer >= 1 && layer <= 3) {
        result[layer].total += 1;
        if (item.status === 'completed') result[layer].done += 1;
      }
    });
    return result;
  }, [dimensionProgress]);

  return (
    <header className="flex items-center justify-between h-[56px] px-4 lg:px-6 bg-white/90 backdrop-blur-sm border-b border-slate-200 shrink-0">
      <div className="flex items-center gap-3">
        <button
          onClick={onToggleLeftNav}
          className="p-2 rounded-lg hover:bg-slate-100 text-slate-500 transition-colors"
        >
          <FontAwesomeIcon icon={faBars} style={{ width: 16, height: 16 }} />
        </button>
        <h1 className="font-semibold text-base lg:text-lg bg-gradient-to-r from-emerald-500 to-teal-500 bg-clip-text text-transparent">
          {projectName || '村庄规划'}
        </h1>
      </div>

      <div className="flex items-center gap-4">
        {LAYER_IDS.map((layer) => {
          const progress = layerProgress[layer];
          const pct = progress.total > 0 ? (progress.done / progress.total) * 100 : 0;
          const isActive = currentLayer === layer;
          const isComplete = progress.total > 0 && progress.done === progress.total;

          return (
            <div key={layer} className="flex items-center gap-1.5">
              <span
                className={`text-xs font-medium uppercase tracking-wider ${
                  isActive ? 'text-emerald-600' : isComplete ? 'text-slate-400' : 'text-slate-300'
                }`}
              >
                L{layer}
              </span>
              <div className="w-20 h-2 bg-slate-100 rounded-full overflow-hidden">
                <motion.div
                  className={`h-full rounded-full ${
                    isComplete ? 'bg-emerald-400' : 'bg-emerald-400/60'
                  }`}
                  initial={{ width: 0 }}
                  animate={{ width: `${pct}%` }}
                  transition={{ duration: 0.3 }}
                />
              </div>
            </div>
          );
        })}
      </div>

      <div className="flex items-center gap-2">
        {status !== 'idle' && (
          <button className="flex items-center gap-1.5 px-3 py-2 rounded-lg border border-slate-200 text-slate-500 text-sm hover:bg-slate-50 transition-colors">
            <FontAwesomeIcon icon={faFileExport} style={{ width: 14, height: 14 }} />
            <span>导出</span>
          </button>
        )}
        <button className="flex items-center gap-1.5 px-3 py-2 rounded-lg border border-emerald-200 text-emerald-600 text-sm hover:bg-emerald-50 transition-colors">
          <FontAwesomeIcon icon={faPlus} style={{ width: 14, height: 14 }} />
          <span>新会话</span>
        </button>
      </div>
    </header>
  );
}
