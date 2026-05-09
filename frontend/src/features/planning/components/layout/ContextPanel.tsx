'use client';

import React, { useMemo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { faTimes, faWrench, faBookOpen } from '@fortawesome/free-solid-svg-icons';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';

import { usePlanningStore } from '../../store';
import { useCascadeChain, useRunningTools, useAllRagSources } from '../../hooks';
import MapView from '../gis/MapView';
import CascadePanel from '../CascadePanel';

export default function ContextPanel() {
  const isRightPanelExpanded = usePlanningStore((state) => state.isRightPanelExpanded);
  const setRightPanelExpanded = usePlanningStore((state) => state.setRightPanelExpanded);
  const gisLayers = usePlanningStore((state) => state.gisLayers);
  const cascadeChain = useCascadeChain();
  const runningTools = useRunningTools();
  const allRagSources = useAllRagSources();

  const flatLayers = useMemo(() => Object.values(gisLayers).flat(), [gisLayers]);
  const hasGisLayers = gisLayers && Object.keys(gisLayers).length > 0;
  const hasRunningTools = runningTools && runningTools.length > 0;
  const hasRagSources = allRagSources && Object.keys(allRagSources).length > 0;

  return (
    <AnimatePresence>
      {isRightPanelExpanded && (
        <motion.aside
          className="w-[280px] h-full bg-white border-l border-slate-200 flex flex-col shrink-0 overflow-y-auto"
          initial={{ width: 0, opacity: 0 }}
          animate={{ width: 280, opacity: 1 }}
          exit={{ width: 0, opacity: 0 }}
          transition={{ duration: 0.2 }}
        >
          <div className="flex items-center justify-between px-4 py-3 border-b border-slate-100">
            <span className="text-sm font-medium text-slate-500 uppercase tracking-wider">上下文</span>
            <button
              onClick={() => setRightPanelExpanded(false)}
              className="p-1 rounded hover:bg-slate-100 text-slate-400 transition-colors"
            >
              <FontAwesomeIcon icon={faTimes} style={{ width: 14, height: 14 }} />
            </button>
          </div>

          <div className="flex-1 overflow-y-auto p-4 space-y-4">
            {hasGisLayers && (
              <div className="rounded-xl overflow-hidden border border-slate-200">
                <div className="h-[240px]">
                  <MapView
                    height="100%"
                    layers={flatLayers as any[]}
                    showLegend={true}
                    legendPosition="bottom-right"
                  />
                </div>
              </div>
            )}

            {cascadeChain && (
              <div className="rounded-xl border border-amber-200 overflow-hidden">
                <CascadePanel trigger={cascadeChain.trigger} impacted={cascadeChain.impacted} />
              </div>
            )}

            {hasRunningTools && (
              <div className="rounded-xl border border-slate-200 p-3">
                <div className="flex items-center gap-1.5 mb-2">
                  <FontAwesomeIcon icon={faWrench} className="text-blue-500" style={{ width: 14, height: 14 }} />
                  <h4 className="text-sm font-medium text-slate-500 uppercase tracking-wider">运行中的工具</h4>
                </div>
                <div className="space-y-1">
                  {runningTools.map((toolName) => (
                    <div
                      key={toolName}
                      className="px-3 py-2 bg-blue-50 border border-blue-100 rounded-md text-sm text-blue-700"
                    >
                      <span className="inline-block w-2 h-2 bg-blue-400 rounded-full animate-pulse mr-1.5" />
                      {toolName}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {hasRagSources && (
              <div className="rounded-xl border border-slate-200 p-3">
                <div className="flex items-center gap-1.5 mb-2">
                  <FontAwesomeIcon icon={faBookOpen} className="text-purple-500" style={{ width: 14, height: 14 }} />
                  <h4 className="text-sm font-medium text-slate-500 uppercase tracking-wider">知识来源</h4>
                </div>
                <div className="space-y-2">
                  {Object.entries(allRagSources).map(([dimKey, source]) => (
                    <div key={dimKey} className="text-sm">
                      <div className="font-medium text-slate-600 mb-1">
                        {dimKey}
                      </div>
                      {source.documents.slice(0, 3).map((doc, idx) => (
                        <div
                          key={idx}
                          className="px-3 py-1.5 bg-slate-50 border border-slate-100 rounded mb-1 text-slate-500 text-sm"
                        >
                          <div className="truncate">{doc.title}</div>
                        </div>
                      ))}
                      {source.documents.length > 3 && (
                        <div className="text-slate-400">+{source.documents.length - 3} 更多</div>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {!hasGisLayers && !hasRunningTools && !hasRagSources && !cascadeChain && (
              <div className="flex items-center justify-center h-32 text-sm text-slate-400">
                暂无上下文数据
              </div>
            )}
          </div>
        </motion.aside>
      )}
    </AnimatePresence>
  );
}
