'use client';

import React, { useCallback } from 'react';
import type { GISLayerConfig } from '@/types/message/message-types';
import { LAYER_TYPE_LABELS, type LayerType } from '../../constants/gis';

interface LayerTogglePanelProps {
  layers: GISLayerConfig[];
  visibleTypes: Set<LayerType>;
  onToggle: (type: LayerType) => void;
}

export default function LayerTogglePanel({
  layers,
  visibleTypes,
  onToggle,
}: LayerTogglePanelProps) {
  const presentTypes = Array.from(
    new Set(layers.map((l) => l.layerType as LayerType))
  );

  const allVisible = presentTypes.every((t) => visibleTypes.has(t));
  const noneVisible = presentTypes.every((t) => !visibleTypes.has(t));

  const toggleAll = useCallback(() => {
    presentTypes.forEach((t) => {
      const shouldBeVisible = noneVisible;
      if (shouldBeVisible !== visibleTypes.has(t)) {
        onToggle(t);
      }
    });
  }, [presentTypes, visibleTypes, noneVisible, onToggle]);

  if (presentTypes.length === 0) return null;

  return (
    <div className="px-2 py-1.5 border-b border-slate-100">
      <div className="flex items-center justify-between mb-1">
        <span className="text-[10px] font-medium text-slate-400 uppercase tracking-wider">
          图层
        </span>
        <button
          onClick={toggleAll}
          className="text-[10px] text-[#0ea5e9] hover:text-[#0284c7] transition-colors"
        >
          {noneVisible ? '全显' : allVisible ? '全隐' : '全显'}
        </button>
      </div>
      <div className="flex flex-wrap gap-1">
        {presentTypes.map((type) => {
          const label = LAYER_TYPE_LABELS[type] || type;
          const visible = visibleTypes.has(type);
          return (
            <button
              key={type}
              onClick={() => onToggle(type)}
              className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] transition-colors ${
                visible
                  ? 'bg-[#0ea5e9]/10 text-[#0ea5e9] border border-[#0ea5e9]/30'
                  : 'bg-slate-50 text-slate-400 border border-slate-200'
              }`}
            >
              <span
                className={`w-1.5 h-1.5 rounded-full ${
                  visible ? 'bg-[#0ea5e9]' : 'bg-slate-300'
                }`}
              />
              {label}
            </button>
          );
        })}
      </div>
    </div>
  );
}
