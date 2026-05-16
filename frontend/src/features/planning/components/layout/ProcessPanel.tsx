'use client';

import React, { useMemo, useCallback, useRef, useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  faTimes,
  faComments,
  faMap,
  faHistory,
  faCog,
} from '@fortawesome/free-solid-svg-icons';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';

import { usePlanningStore, usePlanningActions } from '../../store';
import type { ProcessPanelTab } from '../../store/planningStore';
import {
  useMessages,
  useVillages,
  useHistoryLoading,
  useStatus,
} from '../../hooks';
import MapView from '../gis/MapView';
import MessageList from '../chat/MessageList';
import ChatInput from '../ChatInput';
import { SettingsPanel } from '../settings';
import { planningApi } from '../../api';

const TABS: { key: ProcessPanelTab; label: string; icon: typeof faComments }[] = [
  { key: 'messages', label: '消息', icon: faComments },
  { key: 'map', label: '地图', icon: faMap },
  { key: 'history', label: '历史', icon: faHistory },
  { key: 'settings', label: '设置', icon: faCog },
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

  const [panelWidth, setPanelWidth] = useState(DEFAULT_WIDTH);
  const [isDragging, setIsDragging] = useState(false);
  const dragStartX = useRef(0);
  const dragStartWidth = useRef(DEFAULT_WIDTH);

  const flatLayers = useMemo(() => Object.values(gisLayers).flat(), [gisLayers]);
  const hasGisLayers = gisLayers && Object.keys(gisLayers).length > 0;

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

  const villages = useVillages();
  const historyLoading = useHistoryLoading();
  const status = useStatus();
  const { loadVillagesHistory, loadHistoricalSession } = usePlanningActions();

  useEffect(() => {
    if (status === 'idle') {
      setProcessPanelTab('history');
    }
  }, [status, setProcessPanelTab]);

  useEffect(() => {
    loadVillagesHistory();
  }, [loadVillagesHistory]);

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
            className="absolute left-0 top-0 bottom-0 w-1.5 cursor-col-resize hover:bg-[#0ea5e9]/30 transition-colors z-10"
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
                    ? 'text-[#0ea5e9]'
                    : 'text-slate-400 hover:text-slate-600'
                }`}
              >
                <FontAwesomeIcon icon={tab.icon} style={{ width: 12, height: 12 }} />
                <span>{tab.label}</span>
                {processPanelTab === tab.key && (
                  <motion.div
                    layoutId="tab-indicator"
                    className="absolute bottom-0 left-2 right-2 h-0.5 bg-[#0ea5e9] rounded-full"
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
                  <div className="flex items-center justify-center h-full text-sm text-[#6e7681]">
                    暂无地图数据
                  </div>
                )}
              </div>
            )}

            {/* History tab */}
            {processPanelTab === 'history' && (
              <div className="flex-1 overflow-y-auto p-3">
                {historyLoading ? (
                  <div className="flex items-center justify-center h-32">
                    <div className="w-5 h-5 border-2 border-[#0ea5e9] border-t-transparent rounded-full animate-spin" />
                  </div>
                ) : villages.length > 0 ? (
                  <div className="space-y-3">
                    {villages.map((village) =>
                      village.sessions.length > 0 ? (
                        <div key={village.name} className="bg-slate-50 rounded-lg border border-slate-200 p-3">
                          <div className="flex items-center justify-between mb-2">
                            <h3 className="text-sm font-medium text-slate-800">
                              {village.display_name || village.name}
                            </h3>
                            <span className="text-xs text-slate-400">
                              {village.session_count} 次会话
                            </span>
                          </div>
                          <div className="space-y-1.5">
                            {village.sessions.slice(0, 5).map((session) => {
                              const date = new Date(session.timestamp);
                              const formattedDate = isNaN(date.getTime())
                                ? session.timestamp
                                : date.toLocaleDateString('zh-CN', {
                                    year: 'numeric',
                                    month: '2-digit',
                                    day: '2-digit',
                                    hour: '2-digit',
                                    minute: '2-digit',
                                  });
                              return (
                                <div
                                  key={session.session_id}
                                  className="flex items-center justify-between px-2.5 py-1.5 rounded-lg bg-white border border-slate-200 hover:border-[#0ea5e9]/50 hover:bg-[#e0f2fe]/30 transition-all cursor-pointer group"
                                  onClick={() => loadHistoricalSession(village.name, session.session_id)}
                                  draggable
                                  onDragStart={(e) => {
                                    e.dataTransfer.setData('application/json', JSON.stringify({
                                      sessionId: session.session_id,
                                      villageName: village.name,
                                      villageDisplayName: village.display_name,
                                      timestamp: session.timestamp,
                                    }));
                                    e.dataTransfer.effectAllowed = 'copy';
                                  }}
                                >
                                  <div className="flex items-center gap-2 min-w-0">
                                    <span className="text-xs text-slate-500 whitespace-nowrap">
                                      {formattedDate}
                                    </span>
                                    {session.has_final_report && (
                                      <span className="px-1 py-0.5 rounded text-[10px] font-medium bg-emerald-100 text-emerald-700">
                                        已完结
                                      </span>
                                    )}
                                  </div>
                                  <span className="text-xs text-[#0ea5e9] opacity-0 group-hover:opacity-100 transition-opacity shrink-0">
                                    恢复
                                  </span>
                                </div>
                              );
                            })}
                          </div>
                        </div>
                      ) : null
                    )}
                  </div>
                ) : (
                  <div className="flex items-center justify-center h-32 text-sm text-slate-400">
                    暂无历史会话
                  </div>
                )}
              </div>
            )}

            {/* Settings tab */}
            {processPanelTab === 'settings' && (
              <div className="flex-1 overflow-hidden">
                <SettingsPanel />
              </div>
            )}
          </div>
        </motion.aside>
      )}
    </AnimatePresence>
  );
}