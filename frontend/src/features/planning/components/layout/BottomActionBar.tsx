'use client';

import React from 'react';
import { faCheck, faTimes, faComments } from '@fortawesome/free-solid-svg-icons';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';

import { usePlanningStore } from '../../store';
import { useIsPaused, useCurrentLayer, useApprovalActions } from '../../hooks';
import { NAV_KEYS } from '@/features/planning/constants';

export default function BottomActionBar() {
  const isPaused = useIsPaused();
  const currentLayer = useCurrentLayer();
  const setSelectedNavigationKey = usePlanningStore((state) => state.setSelectedNavigationKey);
  const { approve, reject, isSubmitting } = useApprovalActions();

  if (isPaused && currentLayer) {
    return (
      <div className="h-[64px] flex items-center justify-center gap-3 px-4 lg:px-6 bg-amber-50/80 backdrop-blur-sm border-t border-amber-200">
        <span className="text-sm text-amber-700 font-medium">Layer {currentLayer} 审查</span>
        <button
          onClick={approve}
          disabled={isSubmitting}
          className="flex items-center gap-1.5 px-4 py-2.5 rounded-lg bg-emerald-500 text-white text-base hover:bg-emerald-600 transition-colors disabled:opacity-50"
        >
          <FontAwesomeIcon icon={faCheck} style={{ width: 16, height: 16 }} />
          <span>批准</span>
        </button>
        <button
          onClick={reject}
          disabled={isSubmitting}
          className="flex items-center gap-1.5 px-4 py-2.5 rounded-lg border border-red-300 bg-white text-red-600 text-base hover:bg-red-50 transition-colors disabled:opacity-50"
        >
          <FontAwesomeIcon icon={faTimes} style={{ width: 16, height: 16 }} />
          <span>驳回</span>
        </button>
        <button
          onClick={() => setSelectedNavigationKey(NAV_KEYS.CHAT)}
          className="flex items-center gap-1.5 px-4 py-2.5 rounded-lg border border-amber-300 bg-white text-amber-600 text-base hover:bg-amber-50 transition-colors"
        >
          <FontAwesomeIcon icon={faComments} style={{ width: 16, height: 16 }} />
          <span>反馈</span>
        </button>
      </div>
    );
  }

  return (
    <div className="h-[64px] flex items-center justify-center px-4 lg:px-6 bg-white/80 backdrop-blur-sm border-t border-slate-200">
      <button
        onClick={() => setSelectedNavigationKey(NAV_KEYS.CHAT)}
        className="flex items-center gap-2 px-4 py-2.5 rounded-lg border border-slate-200 text-slate-500 text-base hover:bg-slate-50 transition-colors"
      >
        <FontAwesomeIcon icon={faComments} style={{ width: 16, height: 16 }} />
        <span>打开对话</span>
      </button>
    </div>
  );
}
