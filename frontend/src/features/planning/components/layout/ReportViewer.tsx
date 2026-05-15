'use client';

import React, { memo, useCallback, useState } from 'react';
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
} from '../../hooks';
import VillageInputForm from '../VillageInputForm';
import MarkdownRenderer from '../ui/MarkdownRenderer';
import { ReportCompareModal, mockCompareSessions } from '../compare';
import { LAYER_VALUE_MAP, LAYER_IDS } from '@/features/planning/constants';

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

  const [showCompare, setShowCompare] = useState(false);
  const [feedback, setFeedback] = useState('');
  const [ragExpanded, setRagExpanded] = useState(true);
  const [selectedDocIndex, setSelectedDocIndex] = useState<number | null>(null);

  const dimProgressKeyForRag = selectedNavigationKey?.startsWith('dim:')
    ? selectedNavigationKey.slice(4)
    : '';
  const ragSources = useDimensionRagSources(dimProgressKeyForRag);

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
      });
      setFeedback('');
    } catch (error) {
      console.error('Reject with feedback failed:', error);
    }
  }, [sessionId, isSubmitting, feedback]);

  const showInputForm = (status as string) === 'idle';

  if (selectedNavigationKey?.startsWith('dim:') && !showInputForm) {
    const dimKey = selectedNavigationKey.slice(4);
    const layer = parseInt(dimKey.split('_')[0], 10);
    const layerReports = reports[`layer${layer}` as 'layer1' | 'layer2' | 'layer3'] || {};
    const dimKeyPart = dimKey.split('_').slice(1).join('_');

    const dimProgressKey = `${layer}_${dimKeyPart}`;
    const progress = dimensionProgress[dimProgressKey];
    const reportContent = streamingContent[dimProgressKey] || layerReports[dimKeyPart] || '';

    return (
      <div className="flex-1 h-full flex bg-[#faf9f6]">
        {/* Main Report Area */}
        <div className="flex-1 h-full flex flex-col overflow-hidden">
          {/* Header */}
          <div className="flex items-center justify-between px-6 lg:px-8 py-4 border-b border-slate-200/80 bg-white/80 backdrop-blur-sm shrink-0">
            <div className="flex items-center gap-4">
              <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-amber-100 to-orange-100 flex items-center justify-center">
                <FontAwesomeIcon icon={faLayerGroup} className="text-amber-600" style={{ width: 16, height: 16 }} />
              </div>
              <div>
                <h2 className="text-lg font-semibold text-slate-800">
                  {dimKeyPart}
                </h2>
                <p className="text-xs text-slate-400">
                  Layer {layer}: {LAYER_VALUE_MAP[layer] || ''}
                </p>
              </div>
            </div>
            <div className="flex items-center gap-2">
              {/* Compare Button */}
              <button
                onClick={() => setShowCompare(true)}
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
            </div>
          </div>

          {/* Content */}
          <div className="flex-1 overflow-y-auto">
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

              {/* RAG Knowledge Sources Panel - at bottom of report */}
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
                                    <div className="text-sm font-medium text-slate-700 truncate">{doc.title}</div>
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
        </div>

        {/* Document Detail Drawer - right side */}
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
                    <div className="text-sm text-slate-600 leading-relaxed">
                      {ragSources.documents[selectedDocIndex].snippet}
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

        {/* Compare Modal */}
        <ReportCompareModal
          dimensionKey={dimProgressKey}
          currentSessionId={sessionId || ''}
          currentContent={reportContent}
          availableSessions={mockCompareSessions}
          isOpen={showCompare}
          onClose={() => setShowCompare(false)}
        />
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
            </motion.div>
          )}
        </div>
      </div>
    </div>
  );
});

export default ReportViewer;