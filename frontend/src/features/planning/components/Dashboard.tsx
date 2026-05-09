'use client';

/**
 * Dashboard - Three-Panel Workbench Layout
 *
 * Layout:
 * - AppHeader (56px top bar)
 * - LayerNav (280px left) + FocusArea (flex:1) + ContextPanel (280px right, collapsible)
 * - BottomActionBar (64px conditional bottom)
 * - Responsive: mobile overlay drawer for LayerNav at lg breakpoint
 */

import React, { useCallback } from 'react';

import { usePlanningStore } from '../store';
import { useStatus } from '../hooks';
import { AppHeader, LayerNav, FocusArea, ContextPanel, BottomActionBar } from './layout';

export default function Dashboard() {
  const status = useStatus();
  const isLeftNavCollapsed = usePlanningStore((state) => state.isLeftNavCollapsed);
  const setLeftNavCollapsed = usePlanningStore((state) => state.setLeftNavCollapsed);

  const handleToggleLeftNav = useCallback(() => {
    setLeftNavCollapsed(!isLeftNavCollapsed);
  }, [isLeftNavCollapsed, setLeftNavCollapsed]);

  return (
    <div className="h-screen overflow-hidden bg-slate-50">
      <AppHeader onToggleLeftNav={handleToggleLeftNav} />

      <div className="flex" style={{ height: 'calc(100vh - 56px)' }}>
        {/* Desktop: inline sidebar */}
        <div className="hidden lg:block shrink-0">
          {!isLeftNavCollapsed && <LayerNav />}
        </div>
        {/* Mobile: overlay drawer */}
        {!isLeftNavCollapsed && (
          <div className="lg:hidden fixed inset-0 z-30">
            <div className="fixed inset-0 bg-black/30" onClick={handleToggleLeftNav} />
            <div className="fixed left-0 top-[56px] bottom-0 z-40 w-[280px] shadow-xl">
              <LayerNav />
            </div>
          </div>
        )}
        <FocusArea />
        <ContextPanel />
      </div>

      {status !== 'idle' && <BottomActionBar />}
    </div>
  );
}
