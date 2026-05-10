'use client';

import React, { useMemo, useCallback, useRef, useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  faTimes,
  faComments,
  faWrench,
  faMap,
  faProjectDiagram,
} from '@fortawesome/free-solid-svg-icons';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';

import { usePlanningStore } from '../../store';
import type { ProcessPanelTab } from '../../store/planningStore';
import {
  useMessages,
  useCascadeChain,
  useDimensionProgressAll,
} from '../../hooks';
import MapView from '../gis/MapView';
import CascadePanel from '../CascadePanel';
import MessageList from '../chat/MessageList';
import ChatInput from '../ChatInput';
import DimensionCard from '../DimensionCard';
import ToolStatusCard from '../chat/ToolStatusCard';
import { planningApi } from '../../api';
import { isToolStatusMessage } from '@/types/message/message-guards';

const TABS: { key: ProcessPanelTab; label: string; icon: typeof faComments }[] = [
  { key: 'messages', label: '消息', icon: faComments },
  { key: 'tools', label: '工具', icon: faWrench },
  { key: 'map', label: '地图', icon: faMap },
  { key: 'cascade', label: '级联', icon: faProjectDiagram },
];

const MIN_WIDTH = 280;
const DEFAULT_WIDTH = 320;
const MAX_WIDTH = 480;

export default function ProcessPanel() {
  const isRightPanelExpanded = usePlanningStore((state) => state.isRightPanelExpanded);
  const setRightPanelExpanded = usePlanningStore((state) => state.setRightPanelExpanded);
  const processPanelTab = usePlanningStore((state) => state.processPanelTab);
  const setProcessPanelTab = usePlanningStore((state) => state.setProcessPanelTab);
  const gisLayers = usePlanningStore((state) => state.gisLayers);
  const sessionId = usePlanningStore((state) => state.sessionId);

  const messages = useMessages();
  const cascadeChain = useCascadeChain();
  const dimensionProgress = useDimensionProgressAll();

  const [panelWidth, setPanelWidth] = useState(DEFAULT_WIDTH);
  const [isDragging, setIsDragging] = useState(false);
  const dragStartX = useRef(0);
  const dragStartWidth = useRef(DEFAULT_WIDTH);

  const flatLayers = useMemo(() => Object.values(gisLayers).flat(), [gisLayers]);
  const hasGisLayers = gisLayers && Object.keys(gisLayers).length > 0;

  const toolStatusMessages = useMemo(
    () => messages.filter(isToolStatusMessage),
    [messages]
  );
  const hasRunningTools = toolStatusMessages.length > 0;

  const handleMouseDown = useCallback(
    (e: React.MouseEvent) => {
      e.preventDefault();
      setIsDragging(true);
      dragStartX.current = e.clientX;
      dragStartWidth.current = panelWidth;
    },
    [panelWidth]
  );

  useEffect(() => {
    if (!isDragging) return;
    const handleMouseMove = (e: MouseEvent) => {
      const delta = dragStartX.current - e.clientX;
      const newWidth = Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, dragStartWidth.current + delta));
      setPanelWidth(newWidth);
    };
    const handleMouseUp = () => setIsDragging(false);
    window.addEventListener('mousemove', handleMouseMove);
    window.addEventListener('mouseup', handleMouseUp);
    return () => {
      window.removeEventListener('mousemove', handleMouseMove);
      window.removeEventListener('mouseup', handleMouseUp);
    };
  }, [isDragging]);

  const handleSendMessage = useCallback(
    async (msg: string) => {
      if (!sessionId) return;
      try {
        await planningApi.sendChatMessage(sessionId, msg);
      } catch (error) {
        console.error('Send message failed:', error);
      }
    },
    [sessionId]
  );

  const dimensionEntries = useMemo(
    () => Object.entries(dimensionProgress),
    [dimensionProgress]
  );

  return (
    <AnimatePresence>
      {isRightPanelExpanded && (
        <motion.aside
          className="h-full bg-white border-l border-slate-200 flex flex-col shrink-0 overflow-hidden relative"
          initial={{ width: 0, opacity: 0 }}
          animate={{ width: panelWidth, opacity: 1 }}
          exit={{ width: 0, opacity: 0 }}
          transition={{ duration: 0.2 }}
        >
          {/* Drag handle */}
          <div
            onMouseDown={handleMouseDown}
            className="absolute left-0 top-0 bottom-0 w-1.5 cursor-col-resize hover:bg-emerald-200 transition-colors z-10"
            style={{ userSelect: 'none' }}
          />

          {/* Header */}
          <div className="flex items-center justify-between px-4 py-3 border-b border-slate-100 shrink-0">
            <span className="text-sm font-medium text-slate-500 uppercase tracking-wider">
              过程面板
            </span>
            <button
              onClick={() => setRightPanelExpanded(false)}
              className="p-1 rounded hover:bg-slate-100 text-slate-400 transition-colors"
            >
              <FontAwesomeIcon icon={faTimes} style={{ width: 14, height: 14 }} />
            </button>
          </div>

          {/* Tab bar */}
          <div className="flex border-b border-slate-100 shrink-0">
            {TABS.map((tab) => (
              <button
                key={tab.key}
                onClick={() => setProcessPanelTab(tab.key)}
                className={`flex-1 flex items-center justify-center gap-1.5 py-2 text-xs font-medium transition-colors relative ${
                  processPanelTab === tab.key
                    ? 'text-emerald-600'
                    : 'text-slate-400 hover:text-slate-600'
                }`}
              >
                <FontAwesomeIcon icon={tab.icon} style={{ width: 12, height: 12 }} />
                <span>{tab.label}</span>
                {tab.key === 'cascade' && cascadeChain && (
                  <span className="absolute -top-0.5 right-1 w-2 h-2 rounded-full bg-amber-400" />
                )}
                {processPanelTab === tab.key && (
                  <motion.div
                    layoutId="tab-indicator"
                    className="absolute bottom-0 left-2 right-2 h-0.5 bg-emerald-500 rounded-full"
                  />
                )}
              </button>
            ))}
          </div>

          {/* Tab content */}
          <div className="flex-1 overflow-hidden flex flex-col">
            {/* Messages tab */}
            {processPanelTab === 'messages' && (
              <div className="flex-1 flex flex-col min-h-0">
                {dimensionEntries.length > 0 && (
                  <div className="shrink-0 px-3 py-2 space-y-1.5 border-b border-slate-50 max-h-[200px] overflow-y-auto">
                    {dimensionEntries.map(([key, progress]) => (
                      <DimensionCard key={key} {...progress} />
                    ))}
                  </div>
                )}

                <div className="flex-1 overflow-y-auto min-h-0">
                  <MessageList messages={messages} />
                </div>

                <div className="shrink-0 border-t border-slate-100">
                  <ChatInput
                    disabled={!sessionId}
                    onSend={handleSendMessage}
                  />
                </div>
              </div>
            )}

            {/* Tools tab */}
            {processPanelTab === 'tools' && (
              <div className="flex-1 overflow-y-auto p-3 space-y-2">
                {hasRunningTools ? (
                  toolStatusMessages.map((msg) => (
                    <ToolStatusCard key={msg.toolName} message={msg} />
                  ))
                ) : (
                  <div className="flex items-center justify-center h-32 text-sm text-slate-400">
                    暂无运行中的工具
                  </div>
                )}
              </div>
            )}

            {/* Map tab */}
            {processPanelTab === 'map' && (
              <div className="flex-1 overflow-hidden">
                {hasGisLayers ? (
                  <MapView
                    height="100%"
                    layers={flatLayers as any[]}
                    showLegend={true}
                    legendPosition="bottom-right"
                  />
                ) : (
                  <div className="flex items-center justify-center h-full text-sm text-slate-400">
                    暂无地图数据
                  </div>
                )}
              </div>
            )}

            {/* Cascade tab */}
            {processPanelTab === 'cascade' && (
              <div className="flex-1 overflow-y-auto p-3">
                {cascadeChain ? (
                  <CascadePanel
                    trigger={cascadeChain.trigger}
                    impacted={cascadeChain.impacted}
                  />
                ) : (
                  <div className="flex items-center justify-center h-32 text-sm text-slate-400">
                    暂无级联修复链
                  </div>
                )}
              </div>
            )}
          </div>
        </motion.aside>
      )}
    </AnimatePresence>
  );
}
