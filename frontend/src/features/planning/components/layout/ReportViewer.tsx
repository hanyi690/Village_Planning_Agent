'use client';

import React, { memo, useCallback, useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  faLayerGroup,
  faExchangeAlt,
  faCheck,
  faTimes,
  faPauseCircle,
  faLink,
  faChevronDown,
  faChevronUp,
  faExternalLinkAlt,
  faArrowLeft,
  faSpinner,
} from '@fortawesome/free-solid-svg-icons';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';

import { usePlanningStore } from '../../store';
import {
  useStatus,
  useIsPaused,
  useCurrentLayer,
  useReports,
  useDimensionProgressAll,
  useApprovalActions,
  useDimensionRagSources,
  useProjectName,
  usePendingReviewLayer,
} from '../../hooks';
import { dataApi } from '../../api';
import type { CompareSession, KnowledgeSourceItem, DimensionVersion } from '../../api/types';
import VillageInputForm from '../VillageInputForm';
import MarkdownRenderer from '../ui/MarkdownRenderer';
import { LAYER_VALUE_MAP, LAYER_IDS } from '@/features/planning/constants';
import { DIMENSION_NAMES } from '../../config/dimensions';
import { cn } from '../../utils/cn';

interface ReportViewerProps {
  onStartPlanning: (data: {
    projectName: string;
    villageData?: string;
    villageName?: string;
    taskDescription?: string;
    constraints?: string;
    villageDataFiles?: File[];
    taskFiles?: File[];
    constraintFiles?: File[];
  }) => void;
  onViewProcess: () => void;
}

const ReportViewer = memo(function ReportViewer({ onStartPlanning, onViewProcess }: ReportViewerProps) {
  const selectedNavigationKey = usePlanningStore((state) => state.selectedNavigationKey);
  const streamingContent = usePlanningStore((state) => state.streamingContent);
  const sessionId = usePlanningStore((state) => state.sessionId);
  const status = useStatus();
  const isPaused = useIsPaused();
  const currentLayer = useCurrentLayer();
  const reports = useReports();
  const dimensionProgress = useDimensionProgressAll();
  const { approve, reject, isSubmitting } = useApprovalActions();
  const projectName = useProjectName();

  // Compare mode state
  const [compareMode, setCompareMode] = useState(false);
  const [availableSessions, setAvailableSessions] = useState<CompareSession[]>([]);
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(null);
  const [compareContent, setCompareContent] = useState<string>('');
  const [compareKnowledgeSources, setCompareKnowledgeSources] = useState<KnowledgeSourceItem[]>([]);
  const [isLoadingSessions, setIsLoadingSessions] = useState(false);
  const [isLoadingCompare, setIsLoadingCompare] = useState(false);

  // Version history state
  const [availableVersions, setAvailableVersions] = useState<DimensionVersion[]>([]);
  const [selectedVersion, setSelectedVersion] = useState<number | null>(null);
  const [isLoadingVersions, setIsLoadingVersions] = useState(false);

  // Drag and drop state
  const [isDragOver, setIsDragOver] = useState(false);

  const [feedback, setFeedback] = useState('');
  const [ragExpanded, setRagExpanded] = useState(true);
  const [selectedDocIndex, setSelectedDocIndex] = useState<number | null>(null);

  // Dimension selector state for cascade revision
  const [selectedDimensions, setSelectedDimensions] = useState<string[]>([]);
  const [showDimensionSelector, setShowDimensionSelector] = useState(false);

  // Get completed dimensions for current review layer
  const pendingReviewLayer = usePendingReviewLayer();
  const completedDimensions = usePlanningStore((state) => state.completedDimensions);
  const currentLayerCompletedDims = pendingReviewLayer
    ? completedDimensions[`layer${pendingReviewLayer}` as 'layer1' | 'layer2' | 'layer3'] || []
    : [];

  const dimProgressKeyForRag = selectedNavigationKey?.startsWith('dim:')
    ? selectedNavigationKey.slice(4)
    : '';
  const ragSources = useDimensionRagSources(dimProgressKeyForRag);

  // Fetch sessions when entering compare mode
  useEffect(() => {
    if (compareMode && projectName) {
      setIsLoadingSessions(true);
      dataApi.getVillageSessions(projectName)
        .then(sessions => {
          const compareSessions = sessions
            .filter(s => s.session_id !== sessionId)
            .map(s => ({
              id: s.session_id,
              name: `${projectName} - ${new Date(s.created_at).toLocaleDateString('zh-CN')}`,
              timestamp: s.created_at,
              isCompleted: s.completed_at !== null,
            }));
          setAvailableSessions(compareSessions);
        })
        .catch(console.error)
        .finally(() => setIsLoadingSessions(false));
    }
  }, [compareMode, projectName, sessionId]);

  // Fetch version history when entering compare mode with current session
  useEffect(() => {
    if (compareMode && sessionId && dimProgressKeyForRag) {
      const dimKey = dimProgressKeyForRag.split('_').slice(1).join('_') || dimProgressKeyForRag;
      setIsLoadingVersions(true);
      dataApi.getDimensionVersions(sessionId, dimKey)
        .then(setAvailableVersions)
        .catch(console.error)
        .finally(() => setIsLoadingVersions(false));
    }
  }, [compareMode, sessionId, dimProgressKeyForRag]);

  // Handle session selection for compare
  const handleSessionSelect = useCallback(async (targetSessionId: string, version?: number) => {
    if (!projectName || !dimProgressKeyForRag) return;

    // Extract pure dimKey from format "layer_dimKey"
    const dimKey = dimProgressKeyForRag.split('_').slice(1).join('_') || dimProgressKeyForRag;

    setSelectedSessionId(targetSessionId);
    setIsLoadingCompare(true);

    try {
      const report = await dataApi.getCrossSessionReport(
        projectName,
        dimKey,
        targetSessionId,
        version
      );
      setCompareContent(report.content || '');
      setCompareKnowledgeSources(report.knowledge_sources || []);
    } catch (error) {
      console.error('[Compare] Failed to fetch compare report:', error);
      setCompareContent('');
      setCompareKnowledgeSources([]);
    } finally {
      setIsLoadingCompare(false);
    }
  }, [projectName, dimProgressKeyForRag]);

  // Handle version selection for current session compare
  const handleVersionSelect = useCallback(async (version: number) => {
    if (!sessionId) return;
    setSelectedVersion(version);
    await handleSessionSelect(sessionId, version);
  }, [sessionId, handleSessionSelect]);

  // Handle compare button click
  const handleCompareClick = useCallback(() => {
    setCompareMode(true);
    setSelectedSessionId(null);
    setSelectedVersion(null);
    setCompareContent('');
    setCompareKnowledgeSources([]);
  }, []);

  // Handle exit compare mode
  const handleExitCompare = useCallback(() => {
    setCompareMode(false);
    setSelectedSessionId(null);
    setSelectedVersion(null);
    setCompareContent('');
    setCompareKnowledgeSources([]);
  }, []);

  // Handle drag and drop for compare
  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'copy';
    setIsDragOver(true);
  }, []);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragOver(false);
  }, []);

  const handleDrop = useCallback(async (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragOver(false);

    try {
      const data = JSON.parse(e.dataTransfer.getData('application/json'));

      if (data.sessionId && data.villageName) {
        // Enter compare mode and select the dropped session
        setCompareMode(true);
        setSelectedVersion(null);
        await handleSessionSelect(data.sessionId);
      }
    } catch (error) {
      console.error('[Compare] Failed to parse drop data:', error);
    }
  }, [handleSessionSelect]);

  const handleSubmit = useCallback(
    (data: { projectName: string; villageData?: string; taskDescription?: string; constraints?: string; villageDataFiles?: File[]; taskFiles?: File[]; constraintFiles?: File[] }) =>
      onStartPlanning({
        projectName: data.projectName,
        villageData: data.villageData || '',
        villageName: data.projectName,
        taskDescription: data.taskDescription,
        constraints: data.constraints,
        villageDataFiles: data.villageDataFiles,
        taskFiles: data.taskFiles,
        constraintFiles: data.constraintFiles,
      }),
    [onStartPlanning]
  );

  const handleRejectWithFeedback = useCallback(async () => {
    if (!sessionId || isSubmitting) return;
    try {
      const { planningApi } = await import('../../api');
      await planningApi.submitFeedback(sessionId, {
        approve: false,
        feedback: feedback.trim() || '需要修改',
        dimensions: selectedDimensions.length > 0 ? selectedDimensions : undefined,
      });
      setFeedback('');
      setSelectedDimensions([]);
      setShowDimensionSelector(false);
    } catch (error) {
      console.error('Reject with feedback failed:', error);
    }
  }, [sessionId, isSubmitting, feedback, selectedDimensions]);

  const showInputForm = (status as string) === 'idle';

  if (selectedNavigationKey?.startsWith('dim:') && !showInputForm) {
    const dimKey = selectedNavigationKey.slice(4);
    const layer = parseInt(dimKey.split('_')[0], 10);
    const layerReports = reports[`layer${layer}` as 'layer1' | 'layer2' | 'layer3'] || {};
    const dimKeyPart = dimKey.split('_').slice(1).join('_');

    const dimProgressKey = `${layer}_${dimKeyPart}`;
    const progress = dimensionProgress[dimProgressKey];
    const isCompleted = progress?.status === 'completed';
    const reportContent = isCompleted
      ? (layerReports[dimKeyPart] || streamingContent[dimProgressKey] || '')
      : (streamingContent[dimProgressKey] || layerReports[dimKeyPart] || '');

    return (
      <div className="flex-1 h-full flex bg-[#faf9f6]">
        {/* Main Report Area */}
        <div className="flex-1 h-full flex flex-col overflow-hidden">
          {/* Header */}
          <div className="flex items-center justify-between px-6 lg:px-8 py-4 border-b border-slate-200/80 bg-white/80 backdrop-blur-sm shrink-0">
            <div className="flex items-center gap-4">
              {compareMode ? (
                <>
                  <button
                    onClick={handleExitCompare}
                    className="w-10 h-10 rounded-xl bg-slate-100 flex items-center justify-center hover:bg-slate-200 transition-colors"
                  >
                    <FontAwesomeIcon icon={faArrowLeft} className="text-slate-600" style={{ width: 16, height: 16 }} />
                  </button>
                  <div>
                    <h2 className="text-lg font-semibold text-slate-800">报告对比</h2>
                    <p className="text-xs text-slate-400">{dimKeyPart}</p>
                  </div>
                </>
              ) : (
                <>
                  <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-amber-100 to-orange-100 flex items-center justify-center">
                    <FontAwesomeIcon icon={faLayerGroup} className="text-amber-600" style={{ width: 16, height: 16 }} />
                  </div>
                  <div>
                    <h2 className="text-lg font-semibold text-slate-800">{dimKeyPart}</h2>
                    <p className="text-xs text-slate-400">
                      Layer {layer}: {LAYER_VALUE_MAP[layer] || ''}
                    </p>
                  </div>
                </>
              )}
            </div>
            <div className="flex items-center gap-2">
              {compareMode ? (
                <>
                  {/* Version Selector (for current session) */}
                  {availableVersions.length > 0 && (
                    <select
                      value={selectedVersion || ''}
                      onChange={(e) => handleVersionSelect(Number(e.target.value))}
                      className="px-3 py-2 rounded-lg text-sm bg-white border border-slate-200 text-slate-700 focus:outline-none focus:ring-2 focus:ring-cyan-300"
                      disabled={isLoadingVersions}
                    >
                      <option value="">当前版本</option>
                      {availableVersions.map((v) => (
                        <option key={v.version} value={v.version}>
                          v{v.version} ({new Date(v.created_at).toLocaleDateString('zh-CN')})
                        </option>
                      ))}
                    </select>
                  )}
                  {/* Session Selector */}
                  <select
                    value={selectedSessionId || ''}
                    onChange={(e) => {
                      setSelectedVersion(null);
                      handleSessionSelect(e.target.value);
                    }}
                    className="px-4 py-2 rounded-lg text-sm bg-white border border-slate-200 text-slate-700 focus:outline-none focus:ring-2 focus:ring-cyan-300"
                    disabled={isLoadingSessions}
                  >
                    <option value="">选择对比会话...</option>
                    <option value={sessionId || ''}>当前会话</option>
                    {availableSessions.map((s) => (
                      <option key={s.id} value={s.id}>
                        {s.name} {s.isCompleted ? '✓' : '○'}
                      </option>
                    ))}
                  </select>
                </>
              ) : (
                <>
                  {/* Compare Button */}
                  <button
                    onClick={handleCompareClick}
                    className="px-4 py-2 rounded-lg text-sm bg-slate-100 text-slate-600 hover:bg-slate-200 transition-all flex items-center gap-2"
                  >
                    <FontAwesomeIcon icon={faExchangeAlt} style={{ width: 14, height: 14 }} />
                    <span>对比</span>
                  </button>
                  <button
                    onClick={onViewProcess}
                    className="px-4 py-2 rounded-lg text-sm bg-slate-100 text-slate-600 hover:bg-slate-200 transition-all"
                  >
                    查看过程
                  </button>
                </>
              )}
            </div>
          </div>

          {/* Content - Compare Mode or Single Report */}
          {compareMode ? (
            <div className="flex-1 flex overflow-hidden">
              {/* Left: Current Report */}
              <div className="w-1/2 flex flex-col border-r border-slate-200 overflow-hidden">
                <div className="px-4 py-3 bg-cyan-50 border-b border-slate-200 shrink-0">
                  <span className="text-sm font-medium text-cyan-700">当前报告</span>
                </div>
                <div className="flex-1 overflow-y-auto p-4">
                  <div className="bg-white rounded-xl shadow-sm border border-slate-200/60 p-4">
                    <MarkdownRenderer content={reportContent || '暂无内容'} />
                  </div>
                  {/* Current Knowledge Sources */}
                  {ragSources && ragSources.documents.length > 0 && (
                    <div className="mt-4 bg-white rounded-xl shadow-sm border border-slate-200/60 p-4">
                      <div className="flex items-center gap-2 mb-3">
                        <FontAwesomeIcon icon={faLink} className="text-emerald-600" style={{ width: 12, height: 12 }} />
                        <span className="text-sm font-medium text-slate-700">知识来源 ({ragSources.documents.length})</span>
                      </div>
                      <div className="space-y-2">
                        {ragSources.documents.slice(0, 5).map((doc, idx) => (
                          <div key={idx} className="text-xs text-slate-600 truncate">
                            📄 {doc.title}
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              </div>

              {/* Right: Compare Report */}
              <div
                className={`w-1/2 flex flex-col overflow-hidden transition-all ${isDragOver ? 'bg-cyan-50 ring-2 ring-cyan-400' : ''}`}
                onDragOver={handleDragOver}
                onDragLeave={handleDragLeave}
                onDrop={handleDrop}
              >
                <div className="px-4 py-3 bg-amber-50 border-b border-slate-200 shrink-0">
                  <span className="text-sm font-medium text-amber-700">
                    {selectedSessionId ? '对比报告' : '选择会话查看对比'}
                  </span>
                </div>
                <div className="flex-1 overflow-y-auto p-4">
                  {isLoadingCompare ? (
                    <div className="flex items-center justify-center h-full">
                      <FontAwesomeIcon icon={faSpinner} className="text-slate-400 animate-spin" style={{ width: 24, height: 24 }} />
                    </div>
                  ) : selectedSessionId ? (
                    <>
                      <div className="bg-white rounded-xl shadow-sm border border-slate-200/60 p-4">
                        <MarkdownRenderer content={compareContent || '暂无内容'} />
                      </div>
                      {/* Compare Knowledge Sources */}
                      {compareKnowledgeSources.length > 0 && (
                        <div className="mt-4 bg-white rounded-xl shadow-sm border border-slate-200/60 p-4">
                          <div className="flex items-center gap-2 mb-3">
                            <FontAwesomeIcon icon={faLink} className="text-emerald-600" style={{ width: 12, height: 12 }} />
                            <span className="text-sm font-medium text-slate-700">知识来源 ({compareKnowledgeSources.length})</span>
                          </div>
                          <div className="space-y-2">
                            {compareKnowledgeSources.slice(0, 5).map((doc, idx) => (
                              <div key={idx} className="text-xs text-slate-600 truncate">
                                📄 {doc.title}
                              </div>
                            ))}
                          </div>
                        </div>
                      )}
                    </>
                  ) : (
                    <div className="flex items-center justify-center h-full">
                      <p className="text-sm text-slate-400">请选择一个会话进行对比</p>
                    </div>
                  )}
                </div>
              </div>
            </div>
          ) : (
            /* Single Report View */
            <div
              className={`flex-1 overflow-y-auto transition-all ${isDragOver ? 'bg-cyan-50 ring-2 ring-cyan-400 ring-inset' : ''}`}
              onDragOver={handleDragOver}
              onDragLeave={handleDragLeave}
              onDrop={handleDrop}
            >
              <div className="max-w-4xl mx-auto p-6 lg:p-8 space-y-4">
                {reportContent ? (
                  <div className="bg-white rounded-2xl shadow-sm border border-slate-200/60 p-6 lg:p-8">
                    <MarkdownRenderer content={reportContent} />
                  </div>
                ) : (
                  <div className="flex items-center justify-center h-64">
                    <div className="text-center">
                      <div className="w-16 h-16 rounded-full bg-slate-100 flex items-center justify-center mb-4 mx-auto">
                        <FontAwesomeIcon icon={faLayerGroup} className="text-slate-300" style={{ width: 24, height: 24 }} />
                      </div>
                      <p className="text-slate-400 text-sm">
                        {progress?.status === 'streaming'
                          ? '正在生成报告...'
                          : '该维度尚未生成报告。'}
                      </p>
                    </div>
                  </div>
                )}

                {/* RAG Knowledge Sources Panel */}
                {ragSources && ragSources.documents.length > 0 && (
                  <div className="bg-white rounded-2xl shadow-sm border border-slate-200/60 overflow-hidden">
                    <button
                      onClick={() => setRagExpanded((prev) => !prev)}
                      className="flex items-center gap-3 w-full px-5 py-4 text-left hover:bg-slate-50 transition-colors"
                    >
                      <div className="w-8 h-8 rounded-lg bg-emerald-100 flex items-center justify-center">
                        <FontAwesomeIcon icon={faLink} className="text-emerald-600" style={{ width: 14, height: 14 }} />
                      </div>
                      <div className="flex-1">
                        <span className="text-sm font-medium text-slate-700">知识来源</span>
                        <span className="text-xs text-slate-400 ml-2">({ragSources.documents.length}条)</span>
                      </div>
                      <FontAwesomeIcon
                        icon={ragExpanded ? faChevronUp : faChevronDown}
                        className="text-slate-400"
                        style={{ width: 12, height: 12 }}
                      />
                    </button>

                    <AnimatePresence initial={false}>
                      {ragExpanded && (
                        <motion.div
                          initial={{ opacity: 0, height: 0 }}
                          animate={{ opacity: 1, height: 'auto' }}
                          exit={{ opacity: 0, height: 0 }}
                          transition={{ duration: 0.2 }}
                          className="overflow-hidden"
                        >
                          <div className="px-5 pb-4 pt-2 border-t border-slate-100">
                            <div className="mb-3">
                              <span className="text-xs text-slate-500">检索词：</span>
                              <span className="text-xs text-emerald-600 font-mono ml-1">{ragSources.query}</span>
                            </div>
                            <div className="space-y-2">
                              {ragSources.documents.map((doc, idx) => (
                                <button
                                  key={idx}
                                  onClick={() => setSelectedDocIndex(selectedDocIndex === idx ? null : idx)}
                                  className="w-full text-left px-4 py-3 rounded-xl bg-slate-50 border border-slate-200 hover:border-emerald-300 hover:bg-emerald-50/30 transition-all"
                                >
                                  <div className="flex items-start justify-between gap-2">
                                    <div className="flex-1 min-w-0">
                                      <div className="flex items-center gap-2">
                                        <div className="text-sm font-medium text-slate-700 truncate">{doc.title}</div>
                                        {doc.score !== undefined && doc.score > 0 && (
                                          <span className="text-xs text-emerald-600 bg-emerald-50 px-1.5 py-0.5 rounded shrink-0">
                                            {doc.score.toFixed(2)}
                                          </span>
                                        )}
                                      </div>
                                      {doc.matched_query && (
                                        <div className="text-xs text-cyan-600 mt-1 truncate">
                                          匹配: {doc.matched_query}
                                        </div>
                                      )}
                                      {doc.snippet && (
                                        <p className="text-xs text-slate-500 mt-1 line-clamp-2">{doc.snippet}</p>
                                      )}
                                    </div>
                                    <FontAwesomeIcon
                                      icon={faExternalLinkAlt}
                                      className="text-slate-300 shrink-0 mt-1"
                                      style={{ width: 10, height: 10 }}
                                    />
                                  </div>
                                </button>
                              ))}
                            </div>
                          </div>
                        </motion.div>
                      )}
                    </AnimatePresence>
                  </div>
                )}
              </div>
            </div>
          )}
        </div>

        {/* Document Detail Drawer - right side (only in single report mode) */}
        {!compareMode && (
          <AnimatePresence>
            {selectedDocIndex !== null && ragSources && (
              <motion.div
                initial={{ width: 0, opacity: 0 }}
                animate={{ width: 400, opacity: 1 }}
                exit={{ width: 0, opacity: 0 }}
                transition={{ duration: 0.25 }}
                className="h-full bg-white border-l border-slate-200 shrink-0 overflow-hidden"
              >
                <div className="h-full flex flex-col">
                  <div className="flex items-center justify-between px-5 py-4 border-b border-slate-100 shrink-0">
                    <span className="text-sm font-medium text-slate-700">知识详情</span>
                    <button
                      onClick={() => setSelectedDocIndex(null)}
                      className="p-1.5 rounded-lg hover:bg-slate-100 text-slate-400 transition-colors"
                    >
                      <FontAwesomeIcon icon={faTimes} style={{ width: 14, height: 14 }} />
                    </button>
                  </div>
                  <div className="flex-1 overflow-y-auto p-5">
                    <div className="text-base font-medium text-slate-800 mb-3">
                      {ragSources.documents[selectedDocIndex]?.title}
                    </div>
                    {ragSources.documents[selectedDocIndex]?.snippet && (
                      <div className="text-sm text-slate-600 leading-relaxed prose prose-sm max-w-none">
                        <MarkdownRenderer content={ragSources.documents[selectedDocIndex].snippet || ''} />
                      </div>
                    )}
                    {ragSources.documents[selectedDocIndex]?.source && (
                      <div className="mt-4 text-xs text-slate-400">
                        来源：{ragSources.documents[selectedDocIndex].source}
                      </div>
                    )}
                  </div>
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        )}
      </div>
    );
  }

  const allDimensionCount = Object.keys(dimensionProgress).length;

  return (
    <div className="flex-1 h-full flex flex-col bg-[#faf9f6]">
      {/* Header */}
      <div className="flex items-center justify-between px-6 lg:px-8 py-4 border-b border-slate-200/80 bg-white/80 backdrop-blur-sm shrink-0">
        <div className="flex items-center gap-4">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-cyan-100 to-teal-100 flex items-center justify-center">
            <FontAwesomeIcon icon={faLayerGroup} className="text-cyan-600" style={{ width: 16, height: 16 }} />
          </div>
          <div>
            <h2 className="text-lg font-semibold text-slate-800">规划总览</h2>
            <p className="text-xs text-slate-400">
              当前阶段: {currentLayer ? `Layer ${currentLayer}` : '初始化中'} | 维度数: {allDimensionCount}
            </p>
          </div>
        </div>
        <button
          onClick={onViewProcess}
          className="px-4 py-2 rounded-lg text-sm bg-slate-100 text-slate-600 hover:bg-slate-200 transition-all"
        >
          查看过程
        </button>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-6 lg:p-8">
        <div className="max-w-4xl mx-auto space-y-4">
          {/* Input Form Card (idle state) */}
          {showInputForm && (
            <VillageInputForm onSubmit={handleSubmit} />
          )}

          {/* Layer Reports (non-idle state) */}
          {!showInputForm && LAYER_IDS.map((layer) => {
            const layerReports = reports[`layer${layer}`] || {};
            const reportKeys = Object.keys(layerReports);
            if (reportKeys.length === 0) return null;
            return (
              <motion.div
                key={layer}
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                className="bg-white rounded-2xl shadow-sm border border-slate-200/60 p-6"
              >
                <div className="flex items-center gap-3 mb-3">
                  <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-amber-100 to-orange-100 flex items-center justify-center">
                    <span className="text-sm font-semibold text-amber-600">{layer}</span>
                  </div>
                  <h3 className="text-base font-medium text-slate-800">
                    Layer {layer}: {LAYER_VALUE_MAP[layer]}
                  </h3>
                </div>
                <div className="flex items-center gap-2">
                  <div className="flex-1 h-2 bg-slate-100 rounded-full overflow-hidden">
                    <div
                      className="h-full bg-gradient-to-r from-amber-400 to-orange-400 rounded-full"
                      style={{ width: '100%' }}
                    />
                  </div>
                  <span className="text-sm text-slate-500">{reportKeys.length} 份报告完成</span>
                </div>
              </motion.div>
            );
          })}

          {isPaused && currentLayer && (
            <motion.div
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              className="p-6 bg-gradient-to-r from-amber-50 to-orange-50 border border-amber-200 rounded-2xl"
            >
              <div className="flex items-center gap-3 mb-4">
                <div className="w-10 h-10 rounded-xl bg-amber-100 flex items-center justify-center">
                  <FontAwesomeIcon icon={faPauseCircle} className="text-amber-600" style={{ width: 20, height: 20 }} />
                </div>
                <div>
                  <h3 className="text-base font-semibold text-amber-800">Layer {currentLayer} 审查</h3>
                  <p className="text-sm text-amber-600">规划已暂停，请审批后继续</p>
                </div>
              </div>

              <div className="flex flex-wrap items-center gap-3">
                <button
                  onClick={approve}
                  disabled={isSubmitting}
                  className="flex items-center gap-2 px-5 py-2.5 rounded-xl bg-[#0ea5e9] text-white text-sm font-medium hover:bg-[#0284c7] transition-colors disabled:opacity-50"
                >
                  <FontAwesomeIcon icon={faCheck} style={{ width: 14, height: 14 }} />
                  <span>批准继续</span>
                </button>

                <button
                  onClick={reject}
                  disabled={isSubmitting}
                  className="flex items-center gap-2 px-5 py-2.5 rounded-xl border border-red-300 bg-white text-red-600 text-sm font-medium hover:bg-red-50 transition-colors disabled:opacity-50"
                >
                  <FontAwesomeIcon icon={faTimes} style={{ width: 14, height: 14 }} />
                  <span>需要修订</span>
                </button>

                <div className="flex-1 min-w-[200px] flex items-center gap-2">
                  <input
                    type="text"
                    value={feedback}
                    onChange={(e) => setFeedback(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' && !e.shiftKey) {
                        e.preventDefault();
                        handleRejectWithFeedback();
                      }
                    }}
                    placeholder="输入修订意见..."
                    className="flex-1 px-4 py-2.5 rounded-xl border border-amber-200 bg-white text-sm text-slate-700 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-amber-300"
                  />
                  <button
                    onClick={handleRejectWithFeedback}
                    disabled={isSubmitting || !feedback.trim()}
                    className="px-4 py-2.5 rounded-xl bg-amber-100 text-amber-700 text-sm font-medium hover:bg-amber-200 transition-colors disabled:opacity-50"
                  >
                    提交反馈
                  </button>
                </div>
              </div>

              {/* Dimension Selector for Cascade Revision */}
              {currentLayerCompletedDims.length > 0 && (
                <div className="mt-3">
                  <button
                    onClick={() => setShowDimensionSelector(!showDimensionSelector)}
                    className="text-xs text-amber-600 hover:text-amber-700 flex items-center gap-1 transition-colors"
                  >
                    <FontAwesomeIcon
                      icon={faChevronDown}
                      className={cn("transition-transform", showDimensionSelector && "rotate-180")}
                      style={{ width: 10, height: 10 }}
                    />
                    <span>
                      {selectedDimensions.length > 0
                        ? `已选择 ${selectedDimensions.length} 个维度进行修订`
                        : `选择修订维度 (${currentLayerCompletedDims.length} 个已完成)`}
                    </span>
                  </button>

                  <AnimatePresence initial={false}>
                    {showDimensionSelector && (
                      <motion.div
                        initial={{ opacity: 0, height: 0 }}
                        animate={{ opacity: 1, height: 'auto' }}
                        exit={{ opacity: 0, height: 0 }}
                        transition={{ duration: 0.2 }}
                        className="overflow-hidden"
                      >
                        <div className="mt-3 p-4 bg-white rounded-xl border border-amber-200">
                          <div className="flex items-center justify-between mb-3">
                            <span className="text-xs text-amber-600">
                              选择需要重新分析的维度（将自动级联修改下游依赖）
                            </span>
                            <button
                              onClick={() => {
                                if (selectedDimensions.length === currentLayerCompletedDims.length) {
                                  setSelectedDimensions([]);
                                } else {
                                  setSelectedDimensions([...currentLayerCompletedDims]);
                                }
                              }}
                              className="text-xs text-amber-500 hover:text-amber-600 underline"
                            >
                              {selectedDimensions.length === currentLayerCompletedDims.length ? '取消全选' : '全选'}
                            </button>
                          </div>
                          <div className="grid grid-cols-2 lg:grid-cols-3 gap-2">
                            {currentLayerCompletedDims.map((dimKey) => (
                              <label
                                key={dimKey}
                                className={cn(
                                  "flex items-center gap-2 px-3 py-2 rounded-lg cursor-pointer transition-all",
                                  selectedDimensions.includes(dimKey)
                                    ? "bg-amber-100 border border-amber-300"
                                    : "bg-slate-50 border border-slate-200 hover:border-amber-200"
                                )}
                              >
                                <input
                                  type="checkbox"
                                  checked={selectedDimensions.includes(dimKey)}
                                  onChange={(e) => {
                                    if (e.target.checked) {
                                      setSelectedDimensions([...selectedDimensions, dimKey]);
                                    } else {
                                      setSelectedDimensions(selectedDimensions.filter(d => d !== dimKey));
                                    }
                                  }}
                                  className="w-4 h-4 rounded border-amber-300 text-amber-500 focus:ring-amber-300"
                                />
                                <span className="text-sm text-slate-700 truncate">
                                  {DIMENSION_NAMES[dimKey] || dimKey}
                                </span>
                              </label>
                            ))}
                          </div>
                        </div>
                      </motion.div>
                    )}
                  </AnimatePresence>
                </div>
              )}
            </motion.div>
          )}
        </div>
      </div>
    </div>
  );
});

export default ReportViewer;