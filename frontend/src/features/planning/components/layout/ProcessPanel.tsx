'use client';

import React, { useMemo, useCallback, useRef, useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  faTimes,
  faComments,
  faMap,
  faHistory,
  faCog,
  faTrash,
  faExpand,
  faCompress,
  faUpload,
} from '@fortawesome/free-solid-svg-icons';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';

import { usePlanningStore, usePlanningActions } from '../../store';
import type { ProcessPanelTab } from '../../store/planningStore';
import {
  useMessages,
  useVillages,
  useHistoryLoading,
  useStatus,
  useGisLayers,
  useHasGisLayers,
} from '../../hooks';
import MapView from '../gis/MapView';
import LayerTogglePanel from '../gis/LayerTogglePanel';
import { ValidationPanel } from '../gis';
import { gisTestApi, type LayoutValidationResult } from '@/features/gis-test/api/gis-test-api';
import { LAYER_TYPE_LABELS, type LayerType } from '../../constants/gis';
import type { GISLayerConfig } from '@/types/message/message-types';
import MessageList from '../chat/MessageList';
import ChatInput from '../ChatInput';
import { SettingsPanel } from '../settings';
import { planningApi } from '../../api';
import { createBaseMessage } from '@/features/planning/utils/message-helpers';
import type { Message } from '@/types';

const TABS: { key: ProcessPanelTab; label: string; icon: typeof faComments }[] = [
  { key: 'messages', label: '消息', icon: faComments },
  { key: 'map', label: '地图', icon: faMap },
  { key: 'history', label: '历史', icon: faHistory },
  { key: 'settings', label: '设置', icon: faCog },
];

const MIN_WIDTH = 280;
const DEFAULT_WIDTH = 320;
const MAX_WIDTH = 480;

// All layer types enabled by default
const ALL_LAYER_TYPES = new Set(Object.keys(LAYER_TYPE_LABELS) as LayerType[]);

function GisUploadButton({
  uploading,
  onClick,
  size = 'sm',
}: {
  uploading: boolean;
  onClick: () => void;
  size?: 'sm' | 'md';
}) {
  const cls = size === 'md'
    ? 'p-2 rounded-lg hover:bg-slate-100 text-slate-500 transition-colors disabled:opacity-50'
    : 'p-1.5 rounded bg-white/90 border border-slate-200 hover:bg-white text-slate-500 hover:text-slate-700 transition-colors shadow-sm disabled:opacity-50';
  const spinnerSize = size === 'md' ? 'w-4 h-4' : 'w-3 h-3';
  const iconSize = size === 'md' ? 16 : 12;

  return (
    <button onClick={onClick} disabled={uploading} className={cls} title="上传 GIS 数据">
      {uploading ? (
        <div className={`${spinnerSize} border-2 border-slate-400 border-t-transparent rounded-full animate-spin`} />
      ) : (
        <FontAwesomeIcon icon={faUpload} style={{ width: iconSize, height: iconSize }} />
      )}
    </button>
  );
}

export default function ProcessPanel() {
  const isRightPanelExpanded = usePlanningStore((state) => state.isRightPanelExpanded);
  const setRightPanelExpanded = usePlanningStore((state) => state.setRightPanelExpanded);
  const processPanelTab = usePlanningStore((state) => state.processPanelTab);
  const setProcessPanelTab = usePlanningStore((state) => state.setProcessPanelTab);
  const flatLayers = useGisLayers();
  const hasGisLayers = useHasGisLayers();
  const gisGenerating = usePlanningStore((state) => state.gisGenerating);
  const isFullMapOpen = usePlanningStore((state) => state.isFullMapOpen);
  const setFullMapOpen = usePlanningStore((state) => state.setFullMapOpen);
  const pipelineTrace = usePlanningStore((state) => state.pipelineTrace);
  const villageCenter = usePlanningStore((state) => state.villageCenter);

  // Layer visibility state
  const [visibleLayerTypes, setVisibleLayerTypes] = useState<Set<LayerType>>(ALL_LAYER_TYPES);

  const handleLayerToggle = useCallback((type: LayerType) => {
    setVisibleLayerTypes((prev) => {
      const next = new Set(prev);
      if (next.has(type)) next.delete(type);
      else next.add(type);
      return next;
    });
  }, []);

  // Layout validation state
  const [validationResult, setValidationResult] = useState<LayoutValidationResult | null>(null);
  const [validationLoading, setValidationLoading] = useState(false);

  // GIS upload state
  const [uploading, setUploading] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const sessionId = usePlanningStore((state) => state.sessionId);
  const addMessage = usePlanningStore((state) => state.addMessage);

  const handleGisUpload = useCallback(async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file || !sessionId) return;
    setUploading(true);
    try {
      await planningApi.uploadGisData(sessionId, file);
      const statusData = await planningApi.getStatus(sessionId);
      if (statusData.gis_layout_configs && statusData.gis_layout_configs.length > 0) {
        usePlanningStore.getState().addGisLayersFromUpload(
          statusData.gis_layout_configs as Array<Record<string, unknown>>,
        );
      }
    } catch (err) {
      console.error('GIS upload failed:', err);
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  }, [sessionId]);

  // Auto-validate when planning_zone layers appear
  useEffect(() => {
    const planningLayers = flatLayers.filter(l => l.layerType === 'planning_zone');
    if (planningLayers.length === 0) {
      setValidationResult(null);
      return;
    }
    setValidationLoading(true);
    gisTestApi.validateLayout({ layout_configs: planningLayers, use_jintian_data: true })
      .then(setValidationResult)
      .catch(() => setValidationResult(null))
      .finally(() => setValidationLoading(false));
  }, [flatLayers]);

  const messages = useMessages();

  const [panelWidth, setPanelWidth] = useState(DEFAULT_WIDTH);
  const [isDragging, setIsDragging] = useState(false);
  const dragStartX = useRef(0);
  const dragStartWidth = useRef(DEFAULT_WIDTH);

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

  const pushTextMessage = useCallback(
    (role: 'user' | 'assistant', content: string) => {
      addMessage({
        ...createBaseMessage(role),
        type: 'text',
        content,
      } as Message);
    },
    [addMessage]
  );

  const handleSendMessage = useCallback(
    async (msg: string) => {
      const text = msg.trim();
      if (!text) return;

      // 先把用户输入显示出来。原版本只调用接口，不写入 messages，
      // 所以用户会感觉“发不出去”。
      pushTextMessage('user', text);

      if (!sessionId) {
        pushTextMessage('assistant', '请先启动规划任务，然后再发送反馈或问题。');
        return;
      }

      try {
        const result = await planningApi.sendChatMessage(sessionId, text);
        const reply = result.reply?.trim();

        if (result.draft_feedback || (result.dimensions && result.dimensions.length > 0)) {
          usePlanningStore.getState().setRevisionDraft({
            feedback: result.draft_feedback || text,
            dimensions: result.dimensions || [],
          });
          pushTextMessage(
            'assistant',
            `${reply || '我已生成一条修订建议。'}\n\n已自动填入左侧审查栏，你可以编辑后点击“提交修订”。`
          );
          return;
        }

        pushTextMessage(
          'assistant',
          reply || '已收到你的消息。我会结合当前规划进度处理；如果你想重生成某一部分，请说明具体维度，例如“重新分析道路交通”。'
        );
      } catch (error) {
        console.error('Send message failed:', error);
        const errorMessage = error instanceof Error ? error.message : String(error);
        pushTextMessage('assistant', `发送失败：${errorMessage}`);
      }
    },
    [sessionId, pushTextMessage]
  );

  const villages = useVillages();
  const historyLoading = useHistoryLoading();
  const status = useStatus();
  const { loadVillagesHistory, loadHistoricalSession, deleteSession } = usePlanningActions();

  useEffect(() => {
    if (status === 'idle') {
      setProcessPanelTab('history');
    }
  }, [status, setProcessPanelTab]);

  useEffect(() => {
    loadVillagesHistory();
  }, [loadVillagesHistory]);

  // Map tab badge: show when GIS data exists but user is on another tab
  const showMapBadge = hasGisLayers && processPanelTab !== 'map';

  return (
    <>
      {/* Full-screen map overlay */}
      {isFullMapOpen && hasGisLayers && (
        <div className="fixed inset-0 z-50 bg-white flex flex-col">
          <div className="flex items-center justify-between px-4 py-2 border-b border-slate-200 shrink-0">
            <span className="text-sm font-medium text-slate-700">空间布局</span>
            <div className="flex items-center gap-3">
              <LayerTogglePanel
                layers={flatLayers}
                visibleTypes={visibleLayerTypes}
                onToggle={handleLayerToggle}
              />
              <GisUploadButton
                uploading={uploading}
                onClick={() => fileInputRef.current?.click()}
                size="md"
              />
              <button
                onClick={() => setFullMapOpen(false)}
                className="p-2 rounded-lg hover:bg-slate-100 text-slate-500 transition-colors"
                title="关闭全屏"
              >
                <FontAwesomeIcon icon={faCompress} style={{ width: 16, height: 16 }} />
              </button>
            </div>
          </div>
          <div className="flex-1 min-h-0">
            <MapView
              height="100%"
              layers={flatLayers}
              visibleLayerTypes={visibleLayerTypes}
              showLegend={true}
              legendPosition="bottom-right"
            />
          </div>
          {(validationResult || validationLoading) && (
            <div className="shrink-0 border-t border-slate-100 p-2 max-h-[200px] overflow-y-auto">
              <ValidationPanel result={validationResult} loading={validationLoading} />
            </div>
          )}
        </div>
      )}

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
                  {/* Map tab badge */}
                  {tab.key === 'map' && showMapBadge && (
                    <span className="absolute top-1 right-3 w-2 h-2 bg-[#0ea5e9] rounded-full" />
                  )}
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
                <div className="flex-1 overflow-hidden flex flex-col">
                  {gisGenerating && !hasGisLayers ? (
                    <div className="flex-1 flex flex-col items-center justify-center gap-3">
                      <div className="w-6 h-6 border-2 border-[#0ea5e9] border-t-transparent rounded-full animate-spin" />
                      <span className="text-sm text-slate-500">正在生成空间布局...</span>
                      {pipelineTrace && (
                        <div className="w-48 space-y-1">
                          {([
                            { key: 'parse', label: '意图解析' },
                            { key: 'kg', label: '知识图谱' },
                            { key: 'conflicts', label: '冲突检测' },
                            { key: 'mip', label: '空间优化' },
                            { key: 'validation', label: '验证循环' },
                          ] as const).map(stage => {
                            const data = pipelineTrace[stage.key];
                            const done = !!data;
                            return (
                              <div key={stage.key} className="flex items-center gap-2 text-xs">
                                <span className={done ? 'text-emerald-500' : 'text-slate-300'}>
                                  {done ? '✓' : '○'}
                                </span>
                                <span className="text-slate-600">{stage.label}</span>
                              </div>
                            );
                          })}
                        </div>
                      )}
                    </div>
                  ) : hasGisLayers ? (
                    <>
                      {/* Layer toggle + fullscreen toolbar */}
                      <LayerTogglePanel
                        layers={flatLayers}
                        visibleTypes={visibleLayerTypes}
                        onToggle={handleLayerToggle}
                      />
                      <div className="flex-1 min-h-0 relative">
                        <MapView
                          height="100%"
                          layers={flatLayers}
                          center={villageCenter}
                          visibleLayerTypes={visibleLayerTypes}
                          showLegend={true}
                          legendPosition="bottom-right"
                        />
                        {/* Upload + Fullscreen buttons */}
                        <div className="absolute top-2 right-2 flex flex-col gap-1.5 z-20">
                          <GisUploadButton
                            uploading={uploading}
                            onClick={() => fileInputRef.current?.click()}
                          />
                          <button
                            onClick={() => setFullMapOpen(true)}
                            className="p-1.5 rounded bg-white/90 border border-slate-200 hover:bg-white text-slate-500 hover:text-slate-700 transition-colors shadow-sm"
                            title="全屏查看"
                          >
                            <FontAwesomeIcon icon={faExpand} style={{ width: 12, height: 12 }} />
                          </button>
                        </div>
                      </div>
                      {(validationResult || validationLoading) && (
                        <div className="shrink-0 border-t border-slate-100 p-2 max-h-[200px] overflow-y-auto">
                          <ValidationPanel result={validationResult} loading={validationLoading} />
                        </div>
                      )}
                    </>
                  ) : (
                    <>
                      {/* No GIS layers yet — show base map with village center */}
                      <div className="flex-1 min-h-0 relative">
                        <MapView
                          height="100%"
                          layers={[]}
                          center={villageCenter}
                          zoom={villageCenter ? 13 : 4}
                          showLegend={false}
                        />
                        {/* Upload button */}
                        <div className="absolute top-2 right-2 z-20">
                          <GisUploadButton
                            uploading={uploading}
                            onClick={() => fileInputRef.current?.click()}
                          />
                        </div>
                      </div>
                      <div className="shrink-0 px-3 py-2 border-t border-slate-100 text-center">
                        <p className="text-xs text-slate-400">
                          完成L3详细规划审查后，点击"生成空间布局"生成规划图层
                        </p>
                      </div>
                    </>
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
                                    <div className="flex items-center gap-2">
                                      <button
                                        className="p-1 rounded hover:bg-red-100 text-slate-400 hover:text-red-500 transition-colors opacity-0 group-hover:opacity-100"
                                        onClick={(e) => {
                                          e.stopPropagation();
                                          if (window.confirm('确定要删除此会话吗？此操作不可撤销。')) {
                                            deleteSession(session.session_id, village.name);
                                          }
                                        }}
                                        title="删除会话"
                                      >
                                        <FontAwesomeIcon icon={faTrash} className="w-3 h-3" />
                                      </button>
                                      <span className="text-xs text-[#0ea5e9] opacity-0 group-hover:opacity-100 transition-opacity shrink-0">
                                        恢复
                                      </span>
                                    </div>
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

      {/* Hidden file input for GIS data upload */}
      <input
        ref={fileInputRef}
        type="file"
        accept=".geojson,.json"
        className="hidden"
        onChange={handleGisUpload}
      />
    </>
  );
}
