'use client';

import React, { useMemo } from 'react';
import type { DimensionStatus } from '../types';
import { getDimensionName } from '../config/dimensions';

const STATUS_COLORS: Record<string, string> = {
  pending: 'bg-slate-300',
  streaming: 'bg-sky-500 animate-pulse',
  completed: 'bg-emerald-500',
  failed: 'bg-red-500',
  resetting: 'bg-amber-500 animate-pulse',
};

interface DimensionCardProps {
  dimensionKey: string;
  dimensionName: string;
  layer: number;
  status: DimensionStatus;
  isExecuting?: boolean;
  isResetting?: boolean;
  onClick?: () => void;
}

export default function DimensionCard({
  dimensionKey,
  dimensionName,
  status,
  isExecuting,
  isResetting,
  onClick,
}: DimensionCardProps) {
  const displayName = useMemo(() => {
    const keyPart = dimensionKey.split('_').slice(1).join('_');
    return dimensionName || getDimensionName(keyPart);
  }, [dimensionKey, dimensionName]);

  const statusClass = useMemo(() => {
    if (isResetting) return STATUS_COLORS.resetting;
    if (isExecuting) return STATUS_COLORS.streaming;
    return STATUS_COLORS[status] || STATUS_COLORS.pending;
  }, [status, isExecuting, isResetting]);

  return (
    <button
      onClick={onClick}
      className="w-full flex items-center gap-3 px-3 py-2 rounded-lg bg-white border border-slate-200 hover:border-slate-300 hover:shadow-sm transition-all text-left"
    >
      <span className={`w-2 h-2 rounded-full shrink-0 ${statusClass}`} />
      <span className="text-sm text-slate-700 truncate">{displayName}</span>
    </button>
  );
}