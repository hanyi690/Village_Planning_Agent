'use client';

import React, { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { faLink, faChevronDown, faChevronUp } from '@fortawesome/free-solid-svg-icons';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';

import { usePlanningStore } from '../../store';
import {
  useStatus,
  useIsPaused,
  useCurrentLayer,
  useReports,
  useDimensionProgressAll,
  useDimensionRagSources,
} from '../../hooks';
import VillageInputForm from '../VillageInputForm';
import MarkdownRenderer from '../ui/MarkdownRenderer';
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
  onLoadSession?: (villageName: string, sessionId: string) => void;
}

export default function ReportViewer({ onStartPlanning, onViewProcess, onLoadSession }: ReportViewerProps) {
  const selectedNavigationKey = usePlanningStore((state) => state.selectedNavigationKey);
  const streamingContent = usePlanningStore((state) => state.streamingContent);
  const status = useStatus();
  const isPaused = useIsPaused();
  const currentLayer = useCurrentLayer();
  const reports = useReports();
  const dimensionProgress = useDimensionProgressAll();

  const [ragExpanded, setRagExpanded] = useState(true);

  // Compute at top level to avoid conditional hook call violation
  const dimProgressKey = selectedNavigationKey?.startsWith('dim:')
    ? selectedNavigationKey.slice(4)
    : '';
  const ragSources = useDimensionRagSources(dimProgressKey);

  if ((status as string) === 'idle') {
    return (
      <div className="flex-1 h-full bg-slate-50">
        <VillageInputForm
          onSubmit={(data) =>
            onStartPlanning({
              projectName: data.projectName,
              villageData: data.villageData || '',
              villageName: data.projectName,
              taskDescription: data.taskDescription,
              constraints: data.constraints,
              villageDataFiles: data.villageDataFiles,
              taskFiles: data.taskFiles,
              constraintFiles: data.constraintFiles,
            })
          }
          onLoadSession={onLoadSession}
        />
      </div>
    );
  }

  if (selectedNavigationKey?.startsWith('dim:')) {
    const dimKey = selectedNavigationKey.slice(4);
    const layer = parseInt(dimKey.split('_')[0], 10);
    const layerReports = reports[`layer${layer}` as 'layer1' | 'layer2' | 'layer3'] || {};
    const dimKeyPart = dimKey.split('_').slice(1).join('_');

    const dimProgressKey = `${layer}_${dimKeyPart}`;
    const progress = dimensionProgress[dimProgressKey];
    const reportContent = streamingContent[dimProgressKey] || layerReports[dimKeyPart] || '';

    return (
      <div className="flex-1 h-full flex flex-col bg-white">
        <div className="flex items-center justify-between px-4 lg:px-6 py-3 border-b border-slate-100 shrink-0">
          <div className="flex items-center gap-3">
            <h2 className="text-lg font-semibold text-slate-800">
              {dimKeyPart}
            </h2>
            <span className="px-2 py-0.5 rounded-full bg-slate-100 text-xs text-slate-500">
              Layer {layer}: {LAYER_VALUE_MAP[layer] || ''}
            </span>
          </div>
          <button
            onClick={onViewProcess}
            className="px-3 py-1.5 rounded-lg border border-slate-200 text-sm text-slate-500 hover:bg-slate-50 transition-colors"
          >
            查看过程
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-4 lg:p-6">
          <div className="max-w-3xl lg:max-w-4xl mx-auto">
            {reportContent ? (
              <>
                {/* RAG knowledge sources */}
                {ragSources && ragSources.documents.length > 0 && (
                  <div className="mb-6 rounded-xl border border-slate-200 bg-slate-50 p-4">
                    <button
                      onClick={() => setRagExpanded((prev) => !prev)}
                      className="flex items-center gap-2 w-full text-left"
                    >
                      <FontAwesomeIcon icon={faLink} className="text-emerald-500" style={{ width: 14, height: 14 }} />
                      <span className="text-sm font-medium text-slate-700">
                        知识来源 ({ragSources.documents.length}条)
                      </span>
                      <FontAwesomeIcon
                        icon={ragExpanded ? faChevronUp : faChevronDown}
                        className="text-slate-400 ml-auto"
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
                          <div className="mt-2 pt-2 border-t border-slate-200">
                            <div className="mb-2">
                              <span className="text-xs text-slate-500">检索词：</span>
                              <span className="text-xs text-emerald-600 font-mono">{ragSources.query}</span>
                            </div>
                            <div className="space-y-1.5">
                              {ragSources.documents.map((doc, idx) => (
                                <div key={idx} className="px-3 py-2 rounded-lg bg-white border border-slate-200">
                                  <div className="text-xs font-medium text-slate-700 mb-0.5">{doc.title}</div>
                                  {doc.snippet && (
                                    <p className="text-xs text-slate-500 line-clamp-3">{doc.snippet}</p>
                                  )}
                                </div>
                              ))}
                            </div>
                          </div>
                        </motion.div>
                      )}
                    </AnimatePresence>
                  </div>
                )}

                <MarkdownRenderer content={reportContent} />
              </>
            ) : (
              <div className="text-slate-400 text-sm">
                {progress?.status === 'streaming'
                  ? '正在生成报告...'
                  : '该维度尚未生成报告。'}
              </div>
            )}
          </div>
        </div>
      </div>
    );
  }

  const allDimensionCount = Object.keys(dimensionProgress).length;

  return (
    <div className="flex-1 h-full flex flex-col bg-slate-50">
      <div className="flex items-center justify-between px-4 lg:px-6 py-3 border-b border-slate-100 bg-white shrink-0">
        <div>
          <h2 className="text-lg font-semibold text-slate-800">规划总览</h2>
          <p className="text-xs text-slate-400">
            当前阶段: {currentLayer ? `Layer ${currentLayer}` : '初始化中'} | 维度数: {allDimensionCount}
          </p>
        </div>
        <button
          onClick={onViewProcess}
          className="px-3 py-1.5 rounded-lg border border-slate-200 text-sm text-slate-500 hover:bg-slate-50 transition-colors"
        >
          查看过程
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-4 lg:p-6">
        <div className="max-w-3xl lg:max-w-4xl mx-auto">
          <div className="space-y-3">
            {LAYER_IDS.map((layer) => {
              const layerReports = reports[`layer${layer}`] || {};
              const reportKeys = Object.keys(layerReports);
              if (reportKeys.length === 0) return null;
              return (
                <div key={layer} className="bg-white rounded-xl border border-slate-200 p-4">
                  <h3 className="text-base font-medium text-slate-700 mb-2">
                    Layer {layer}: {LAYER_VALUE_MAP[layer]}
                  </h3>
                  <div className="text-sm text-slate-500">{reportKeys.length} 份报告完成</div>
                </div>
              );
            })}
          </div>

          {isPaused && (
            <div className="mt-4 p-4 bg-amber-50 border border-amber-200 rounded-xl">
              <p className="text-sm text-amber-700">
                规划已暂停，等待审批。请使用底部操作栏批准或提交修订意见。
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
