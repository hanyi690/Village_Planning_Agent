'use client';

/**
 * PlanningTextViewer - 规划文本查看界面
 *
 * 显示生成的规划文本内容，支持：
 * - 版本切换
 * - 导出为 DOCX/JSON
 * - 重新生成
 */
import React, { memo, useState, useEffect, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  faFileAlt,
  faSpinner,
  faDownload,
  faRedo,
  faChevronDown,
  faCheck,
  faTimes,
} from '@fortawesome/free-solid-svg-icons';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';

import { planningApi } from '../api/planning-api';
import MarkdownRenderer from './ui/MarkdownRenderer';
import type {
  PlanningTextDocument,
  PlanningTextVersion,
} from '../api/types';

interface PlanningTextViewerProps {
  sessionId: string;
}

const PlanningTextViewer = memo(function PlanningTextViewer({ sessionId }: PlanningTextViewerProps) {
  const [document, setDocument] = useState<PlanningTextDocument | null>(null);
  const [versions, setVersions] = useState<PlanningTextVersion[]>([]);
  const [selectedVersion, setSelectedVersion] = useState<number | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isGenerating, setIsGenerating] = useState(false);
  const [isExporting, setIsExporting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showVersionDropdown, setShowVersionDropdown] = useState(false);

  // Fetch document on mount
  useEffect(() => {
    if (!sessionId) return;

    const fetchData = async () => {
      setIsLoading(true);
      setError(null);

      try {
        // Fetch latest document
        const doc = await planningApi.getPlanningText(sessionId);
        setDocument(doc);

        // Fetch versions list
        const versionList = await planningApi.getPlanningTextVersions(sessionId);
        setVersions(versionList.versions);
      } catch (err) {
        console.error('[PlanningText] Failed to fetch:', err);
        setError('加载规划文本失败');
      } finally {
        setIsLoading(false);
      }
    };

    fetchData();
  }, [sessionId]);

  // Handle version change
  const handleVersionChange = useCallback(async (version: number) => {
    if (version === selectedVersion) return;

    setIsLoading(true);
    setShowVersionDropdown(false);

    try {
      const doc = await planningApi.getPlanningText(sessionId, version);
      setDocument(doc);
      setSelectedVersion(version);
    } catch (err) {
      console.error('[PlanningText] Failed to fetch version:', err);
      setError('加载版本失败');
    } finally {
      setIsLoading(false);
    }
  }, [sessionId, selectedVersion]);

  // Handle generate
  const handleGenerate = useCallback(async () => {
    if (!sessionId || isGenerating) return;

    setIsGenerating(true);
    setError(null);

    try {
      await planningApi.generatePlanningText(sessionId, {
        trigger_reason: document ? 'manual' : 'initial',
      });

      // Refresh data
      const doc = await planningApi.getPlanningText(sessionId);
      setDocument(doc);

      const versionList = await planningApi.getPlanningTextVersions(sessionId);
      setVersions(versionList.versions);
    } catch (err) {
      console.error('[PlanningText] Failed to generate:', err);
      setError('生成规划文本失败');
    } finally {
      setIsGenerating(false);
    }
  }, [sessionId, isGenerating, document]);

  // Handle export
  const handleExport = useCallback(async () => {
    if (!document || isExporting) return;

    setIsExporting(true);

    try {
      await planningApi.exportPlanningTextDocx(sessionId, '村庄规划');
    } catch (err) {
      console.error('[PlanningText] Failed to export:', err);
      setError('导出失败');
    } finally {
      setIsExporting(false);
    }
  }, [sessionId, document, isExporting]);

  // Loading state
  if (isLoading) {
    return (
      <div className="flex-1 h-full flex items-center justify-center bg-[#faf9f6]">
        <div className="text-center">
          <FontAwesomeIcon icon={faSpinner} className="text-slate-400 animate-spin mb-4" style={{ width: 32, height: 32 }} />
          <p className="text-slate-500">加载规划文本...</p>
        </div>
      </div>
    );
  }

  // No document yet
  if (!document) {
    return (
      <div className="flex-1 h-full flex flex-col bg-[#faf9f6]">
        {/* Header */}
        <div className="flex items-center justify-between px-6 lg:px-8 py-4 border-b border-slate-200/80 bg-white/80 backdrop-blur-sm shrink-0">
          <div className="flex items-center gap-4">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-emerald-100 to-teal-100 flex items-center justify-center">
              <FontAwesomeIcon icon={faFileAlt} className="text-emerald-600" style={{ width: 16, height: 16 }} />
            </div>
            <div>
              <h2 className="text-lg font-semibold text-slate-800">规划文本</h2>
              <p className="text-xs text-slate-400">生成法定规划文档</p>
            </div>
          </div>
        </div>

        {/* Generate Prompt */}
        <div className="flex-1 flex items-center justify-center p-8">
          <div className="text-center max-w-md">
            <div className="w-16 h-16 rounded-full bg-slate-100 flex items-center justify-center mb-4 mx-auto">
              <FontAwesomeIcon icon={faFileAlt} className="text-slate-300" style={{ width: 24, height: 24 }} />
            </div>
            <h3 className="text-lg font-medium text-slate-700 mb-2">尚未生成规划文本</h3>
            <p className="text-sm text-slate-500 mb-6">
              点击下方按钮，基于已完成的维度分析生成完整的规划文档
            </p>
            <button
              onClick={handleGenerate}
              disabled={isGenerating}
              className="px-6 py-3 rounded-xl bg-emerald-500 text-white text-sm font-medium hover:bg-emerald-600 transition-colors disabled:opacity-50 flex items-center gap-2 mx-auto"
            >
              {isGenerating ? (
                <>
                  <FontAwesomeIcon icon={faSpinner} className="animate-spin" style={{ width: 14, height: 14 }} />
                  <span>生成中...</span>
                </>
              ) : (
                <>
                  <FontAwesomeIcon icon={faFileAlt} style={{ width: 14, height: 14 }} />
                  <span>生成规划文本</span>
                </>
              )}
            </button>
          </div>
        </div>
      </div>
    );
  }

  // Document view
  return (
    <div className="flex-1 h-full flex flex-col bg-[#faf9f6]">
      {/* Header */}
      <div className="flex items-center justify-between px-6 lg:px-8 py-4 border-b border-slate-200/80 bg-white/80 backdrop-blur-sm shrink-0">
        <div className="flex items-center gap-4">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-emerald-100 to-teal-100 flex items-center justify-center">
            <FontAwesomeIcon icon={faFileAlt} className="text-emerald-600" style={{ width: 16, height: 16 }} />
          </div>
          <div>
            <h2 className="text-lg font-semibold text-slate-800">规划文本</h2>
            <p className="text-xs text-slate-400">
              {document.article_count} 条条文 · 版本 {document.version}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {/* Version Dropdown */}
          {versions.length > 1 && (
            <div className="relative">
              <button
                onClick={() => setShowVersionDropdown(!showVersionDropdown)}
                className="px-3 py-2 rounded-lg text-sm bg-white border border-slate-200 text-slate-700 hover:bg-slate-50 flex items-center gap-2"
              >
                <span>v{document.version}</span>
                <FontAwesomeIcon icon={faChevronDown} style={{ width: 10, height: 10 }} />
              </button>

              <AnimatePresence>
                {showVersionDropdown && (
                  <motion.div
                    initial={{ opacity: 0, y: -4 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, y: -4 }}
                    className="absolute top-full right-0 mt-1 bg-white border border-slate-200 rounded-lg shadow-lg z-10 min-w-[120px]"
                  >
                    {versions.map((v) => (
                      <button
                        key={v.version}
                        onClick={() => handleVersionChange(v.version)}
                        className={`w-full px-3 py-2 text-left text-sm hover:bg-slate-50 flex items-center justify-between ${
                          v.version === document.version ? 'bg-emerald-50 text-emerald-700' : 'text-slate-700'
                        }`}
                      >
                        <span>v{v.version}</span>
                        {v.version === document.version && (
                          <FontAwesomeIcon icon={faCheck} className="text-emerald-500" style={{ width: 12, height: 12 }} />
                        )}
                      </button>
                    ))}
                  </motion.div>
                )}
              </AnimatePresence>
            </div>
          )}

          {/* Export DOCX */}
          <button
            onClick={() => handleExport()}
            disabled={isExporting}
            className="px-3 py-2 rounded-lg text-sm bg-slate-100 text-slate-600 hover:bg-slate-200 transition-colors disabled:opacity-50 flex items-center gap-2"
          >
            <FontAwesomeIcon icon={faDownload} style={{ width: 12, height: 12 }} />
            <span>DOCX</span>
          </button>

          {/* Regenerate */}
          <button
            onClick={handleGenerate}
            disabled={isGenerating}
            className="px-3 py-2 rounded-lg text-sm bg-emerald-100 text-emerald-700 hover:bg-emerald-200 transition-colors disabled:opacity-50 flex items-center gap-2"
          >
            {isGenerating ? (
              <>
                <FontAwesomeIcon icon={faSpinner} className="animate-spin" style={{ width: 12, height: 12 }} />
                <span>生成中</span>
              </>
            ) : (
              <>
                <FontAwesomeIcon icon={faRedo} style={{ width: 12, height: 12 }} />
                <span>重新生成</span>
              </>
            )}
          </button>
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-6 lg:p-8">
        <div className="max-w-4xl mx-auto">
          {error && (
            <div className="mb-4 p-4 bg-red-50 border border-red-200 rounded-xl text-red-600 text-sm flex items-center gap-2">
              <FontAwesomeIcon icon={faTimes} style={{ width: 14, height: 14 }} />
              <span>{error}</span>
            </div>
          )}

          <div className="bg-white rounded-2xl shadow-sm border border-slate-200/60 p-6 lg:p-8">
            <MarkdownRenderer content={document.markdown_content || '暂无内容'} />
          </div>

          {/* Version Info */}
          <div className="mt-4 text-xs text-slate-400 text-center">
            生成于 {new Date(document.generated_at).toLocaleString('zh-CN')}
            {document.generation_duration_seconds && (
              <span className="ml-2">· 耗时 {document.generation_duration_seconds.toFixed(1)}s</span>
            )}
          </div>
        </div>
      </div>
    </div>
  );
});

export default PlanningTextViewer;
