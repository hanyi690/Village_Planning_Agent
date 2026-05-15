'use client';

/**
 * Dashboard - Report Workbench Layout
 *
 * Layout:
 * - AppHeader (56px top bar)
 * - LayerNav (280px left) + ReportViewer (flex:1) + ProcessPanel (320px right, collapsible)
 * - ChatBar (fixed bottom-0, always rendered)
 * - Responsive: mobile overlay drawer for LayerNav at lg breakpoint
 */

import React, { useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { faChevronLeft } from '@fortawesome/free-solid-svg-icons';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';

import { usePlanningStore } from '../store';
import { AppHeader, LayerNav, FocusArea, ProcessPanel } from './layout';

export default function Dashboard() {
  const isLeftNavCollapsed = usePlanningStore((state) => state.isLeftNavCollapsed);
  const setLeftNavCollapsed = usePlanningStore((state) => state.setLeftNavCollapsed);
  const isRightPanelExpanded = usePlanningStore((state) => state.isRightPanelExpanded);
  const setRightPanelExpanded = usePlanningStore((state) => state.setRightPanelExpanded);
  const setProcessPanelTab = usePlanningStore((state) => state.setProcessPanelTab);

  const handleToggleLeftNav = useCallback(() => {
    setLeftNavCollapsed(!isLeftNavCollapsed);
  }, [isLeftNavCollapsed, setLeftNavCollapsed]);

  const handleOpenRightPanel = useCallback(() => {
    setProcessPanelTab('messages');
    setRightPanelExpanded(true);
  }, [setProcessPanelTab, setRightPanelExpanded]);

  return (
    <div className="h-screen overflow-hidden bg-[#f8fafc]">
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
        <ProcessPanel />
      </div>

      {/* Right panel reopen button */}
      <AnimatePresence>
        {!isRightPanelExpanded && (
          <motion.button
            onClick={handleOpenRightPanel}
            className="fixed right-4 top-1/2 -translate-y-1/2 z-40 w-8 h-20 rounded-l-lg bg-white border border-slate-200 shadow-md hover:bg-slate-50 transition-colors flex items-center justify-center group"
            initial={{ opacity: 0, x: 20 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: 20 }}
            title="打开过程面板"
          >
            <FontAwesomeIcon
              icon={faChevronLeft}
              className="text-slate-400 group-hover:text-[#0ea5e9] transition-colors"
              style={{ width: 14, height: 14 }}
            />
          </motion.button>
        )}
      </AnimatePresence>
    </div>
  );
}
