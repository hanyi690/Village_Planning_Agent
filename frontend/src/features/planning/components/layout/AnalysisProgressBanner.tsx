'use client';

import React from 'react';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { faSpinner } from '@fortawesome/free-solid-svg-icons';

import { LAYER_VALUE_MAP } from '@/features/planning/constants';
import type { ActiveAnalysisFocus } from '../../hooks/useActiveAnalysisFocus';

const PHASE_LABELS: Record<ActiveAnalysisFocus['phase'], string> = {
  executing: '正在分析',
  streaming: '正在生成报告',
  queued: '即将分析',
  paused: '已暂停',
};

interface AnalysisProgressBannerProps {
  focus: ActiveAnalysisFocus;
  completedCount: number;
  totalCount: number;
  compact?: boolean;
}

export default function AnalysisProgressBanner({
  focus,
  completedCount,
  totalCount,
  compact = false,
}: AnalysisProgressBannerProps) {
  const layerLabel = LAYER_VALUE_MAP[focus.layer] ?? `L${focus.layer}`;
  const phaseLabel = PHASE_LABELS[focus.phase];
  const isActive = focus.phase === 'executing' || focus.phase === 'streaming';

  if (compact) {
    return (
      <div className="flex min-w-0 flex-1 items-center gap-2 rounded-lg border border-[#c9e8db] bg-[#eef8f3] px-2.5 py-1.5">
        {isActive && (
          <FontAwesomeIcon icon={faSpinner} spin className="shrink-0 text-[#3fb288]" style={{ width: 12, height: 12 }} />
        )}
        <div className="min-w-0 flex-1">
          <p className="truncate text-[11px] font-medium text-[#1f7a59]">
            {phaseLabel}：{focus.name}
          </p>
          <p className="truncate text-[10px] text-[#78968b]">
            L{focus.layer} · {layerLabel} · {completedCount}/{totalCount}
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="overflow-hidden rounded-xl border border-[#c9e8db] bg-gradient-to-r from-[#eef8f3] to-white px-4 py-3 shadow-sm">
      <div className="flex items-start gap-3">
        {isActive ? (
          <div className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-[#dff3ea]">
            <FontAwesomeIcon icon={faSpinner} spin className="text-[#2d8c6d]" style={{ width: 16, height: 16 }} />
          </div>
        ) : (
          <div className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-[#f3f8f5] text-[11px] font-semibold text-[#3a8f6f]">
            L{focus.layer}
          </div>
        )}
        <div className="min-w-0 flex-1">
          <p className="text-[11px] font-semibold uppercase tracking-wide text-[#3a8f6f]">
            {phaseLabel}
          </p>
          <p className="mt-0.5 truncate text-[15px] font-semibold text-[#244c40]">
            {focus.name}
          </p>
          <p className="mt-1 text-[12px] text-[#78968b]">
            {layerLabel} · 整体进度 {completedCount}/{totalCount}
          </p>
        </div>
      </div>
    </div>
  );
}
