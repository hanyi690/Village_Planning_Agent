'use client';

/**
 * PlanningTextViewer - 规划文本查看界面
 *
 * 显示生成的规划文本内容，支持：
 * - 版本切换
 * - 导出为 DOCX/JSON
 * - 重新生成
 */
import React, { memo, useState, useEffect, useCallback, useMemo, useRef } from 'react';
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
import { usePlanningStore } from '../store/planningStore';
import { downloadBlob } from '../utils/download';
import OverviewGuidePanel from './layout/OverviewGuidePanel';
import MarkdownRenderer from './ui/MarkdownRenderer';
import type {
  PlanningTextDocument,
  PlanningTextVersion,
} from '../api/types';
import { useAnalysisCompletion } from '../hooks/useAnalysisCompletion';

interface PlanningTextViewerProps {
  sessionId: string;
  embedded?: boolean;
}

interface DocumentHeading {
  level: number;
  title: string;
  ordinal: number;
}

interface DocumentEvidence {
  title: string;
  snippet?: string;
}

function extractHeadings(markdown: string): DocumentHeading[] {
  let ordinal = 0;
  return markdown
    .split('\n')
    .map((line) => {
      const match = /^(#{1,3})\s+(.+?)\s*$/.exec(line);
      if (!match) return null;
      const heading = { level: match[1].length, title: match[2].replace(/[*_`]/g, ''), ordinal };
      ordinal += 1;
      return heading;
    })
    .filter((heading): heading is DocumentHeading => Boolean(heading));
}

function extractEvidence(jsonContent?: Record<string, unknown>): DocumentEvidence[] {
  if (!jsonContent) return [];
  const candidate = jsonContent.sources ?? jsonContent.evidence ?? jsonContent.citations ?? jsonContent.references;
  if (!Array.isArray(candidate)) return [];
  return candidate.slice(0, 12).map((item, index) => {
    if (typeof item === 'string') return { title: item };
    if (!item || typeof item !== 'object') return { title: `依据 ${index + 1}` };
    const record = item as Record<string, unknown>;
    return {
      title: String(record.title ?? record.name ?? record.source ?? record.document_name ?? `依据 ${index + 1}`),
      snippet: record.snippet || record.content || record.summary
        ? String(record.snippet ?? record.content ?? record.summary)
        : undefined,
    };
  });
}

function releaseColumnResizeGlobals() {
  if (typeof globalThis.document === 'undefined') return;
  globalThis.document.body.style.userSelect = '';
  globalThis.document.body.style.cursor = '';
}

const PlanningDocumentMarkdown = memo(function PlanningDocumentMarkdown({ content }: { content: string }) {
  return (
    <MarkdownRenderer
      className="planning-document-markdown"
      content={content}
    />
  );
});

interface PlanningTextEmptyStateProps {
  embedded: boolean;
  isGenerating: boolean;
  regenNotice: string | null;
  error: string | null;
  onGenerate: () => void;
}

const PlanningTextEmptyState = memo(function PlanningTextEmptyState({
  embedded,
  isGenerating,
  regenNotice,
  error,
  onGenerate,
}: PlanningTextEmptyStateProps) {
  const { isComplete: analysisComplete, completedDimensions, totalDimensions, progressPercent } = useAnalysisCompletion();

  if (embedded) {
    if (!analysisComplete) {
      return (
        <OverviewGuidePanel
          variant="document-waiting"
          completedDimensions={completedDimensions}
          totalDimensions={totalDimensions}
          progressPercent={progressPercent}
        />
      );
    }

    if (isGenerating) {
      return (
        <OverviewGuidePanel
          variant="document-generating"
          completedDimensions={completedDimensions}
          totalDimensions={totalDimensions}
          progressPercent={progressPercent}
          isGenerating
          notice={regenNotice}
          error={error}
        />
      );
    }

    return (
      <OverviewGuidePanel
        variant="document-ready"
        completedDimensions={completedDimensions}
        totalDimensions={totalDimensions}
        progressPercent={progressPercent}
        error={error}
        onRetryGenerate={onGenerate}
      />
    );
  }

  return (
    <div className="flex-1 h-full flex flex-col bg-[#faf9f6]">
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

      <div className="flex-1 flex items-center justify-center p-8">
        <div className="text-center max-w-md">
          <div className="w-16 h-16 rounded-full bg-slate-100 flex items-center justify-center mb-4 mx-auto">
            <FontAwesomeIcon icon={faFileAlt} className="text-slate-300" style={{ width: 24, height: 24 }} />
          </div>
          <h3 className="text-lg font-medium text-slate-700 mb-2">
            {analysisComplete ? '尚未生成规划文本' : '等待分层分析完成'}
          </h3>
          <p className="text-sm text-slate-500 mb-6">
            {analysisComplete
              ? '分层分析已完成，系统会汇总智能体专题报告生成规划文档'
              : `分析进行中（${completedDimensions}/${totalDimensions}），完成后请先审查专题成果，再手动生成规划文本`}
          </p>
          {analysisComplete && (
            <button
              onClick={onGenerate}
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
          )}
        </div>
      </div>
    </div>
  );
});

const PlanningTextViewer = memo(function PlanningTextViewer({ sessionId, embedded = false }: PlanningTextViewerProps) {
  const [document, setDocument] = useState<PlanningTextDocument | null>(null);
  const [versions, setVersions] = useState<PlanningTextVersion[]>([]);
  const [selectedVersion, setSelectedVersion] = useState<number | null>(null);
  const [isInitialLoading, setIsInitialLoading] = useState(true);
  const [isVersionLoading, setIsVersionLoading] = useState(false);
  const [isGenerating, setIsGenerating] = useState(false);
  const [isExporting, setIsExporting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showVersionDropdown, setShowVersionDropdown] = useState(false);
  const [regenNotice, setRegenNotice] = useState<string | null>(null);
  const [tocWidth, setTocWidth] = useState(220);
  const [evidenceWidth, setEvidenceWidth] = useState(280);
  const [showToc, setShowToc] = useState(true);
  const [showEvidence, setShowEvidence] = useState(true);
  const contentRef = useRef<HTMLDivElement>(null);
  const columnResizeRef = useRef<{ kind: 'toc' | 'evidence'; start: number; value: number } | null>(null);
  const [revisionNotice, setRevisionNotice] = useState<string | null>(null);
  const planningTextRegenRequest = usePlanningStore((state) => state.planningTextRegenRequest);
  const clearPlanningTextRegenRequest = usePlanningStore((state) => state.clearPlanningTextRegenRequest);
  const projectName = usePlanningStore((state) => state.projectName);

  const isAnalysisComplete = useCallback(() => {
    const state = usePlanningStore.getState();
    const completed = (['layer1', 'layer2', 'layer3'] as const).reduce(
      (sum, layerKey) => sum + (state.completedDimensions[layerKey]?.length ?? 0),
      0,
    );
    return state.status === 'completed'
      || state.phase === 'completed'
      || completed >= 28;
  }, []);
  const headings = useMemo(() => extractHeadings(document?.markdown_content || ''), [document?.markdown_content]);
  const evidence = useMemo(() => extractEvidence(document?.json_content), [document?.json_content]);

  const gridTemplateColumns = useMemo(() => {
    const columns: string[] = [];
    if (showToc) {
      columns.push(`${tocWidth}px`, '6px');
    }
    columns.push('minmax(0,1fr)');
    if (showEvidence) {
      columns.push('6px', `${evidenceWidth}px`);
    }
    return columns.join(' ');
  }, [showToc, showEvidence, tocWidth, evidenceWidth]);

  const beginColumnResize = useCallback((kind: 'toc' | 'evidence', event: React.PointerEvent<HTMLDivElement>) => {
    event.preventDefault();
    const handle = event.currentTarget;
    handle.setPointerCapture(event.pointerId);
    columnResizeRef.current = {
      kind,
      start: event.clientX,
      value: kind === 'toc' ? tocWidth : evidenceWidth,
    };
    globalThis.document.body.style.userSelect = 'none';
    globalThis.document.body.style.cursor = 'col-resize';
    const move = (moveEvent: PointerEvent) => {
      const active = columnResizeRef.current;
      if (!active) return;
      const delta = moveEvent.clientX - active.start;
      if (active.kind === 'toc') {
        setTocWidth(Math.max(160, Math.min(360, active.value + delta)));
      } else {
        setEvidenceWidth(Math.max(200, Math.min(440, active.value - delta)));
      }
    };
    const up = () => {
      columnResizeRef.current = null;
      releaseColumnResizeGlobals();
      handle.removeEventListener('pointermove', move);
      handle.removeEventListener('pointerup', up);
      handle.removeEventListener('pointercancel', up);
    };
    handle.addEventListener('pointermove', move);
    handle.addEventListener('pointerup', up);
    handle.addEventListener('pointercancel', up);
  }, [evidenceWidth, tocWidth]);

  useEffect(() => {
    const release = () => {
      columnResizeRef.current = null;
      releaseColumnResizeGlobals();
    };
    window.addEventListener('blur', release);
    window.addEventListener('pointerup', release);
    window.addEventListener('pointercancel', release);
    globalThis.document.addEventListener('visibilitychange', release);
    return release;
  }, []);

  useEffect(() => {
    setDocument(null);
    setVersions([]);
    setSelectedVersion(null);
    setIsInitialLoading(true);
    setIsVersionLoading(false);
    setIsGenerating(false);
    setError(null);
    setRegenNotice(null);
    setShowVersionDropdown(false);
    releaseColumnResizeGlobals();
  }, [sessionId]);

  const scrollToHeading = useCallback((ordinal: number) => {
    const element = contentRef.current?.querySelectorAll('h1, h2, h3')[ordinal];
    element?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }, []);

  // Fetch document on mount / session change
  useEffect(() => {
    if (!sessionId) return;

    let cancelled = false;
    const fetchData = async () => {
      setIsInitialLoading(true);
      setError(null);

      try {
        const doc = await planningApi.getPlanningText(sessionId);
        if (cancelled) return;
        setDocument(doc);

        const versionList = await planningApi.getPlanningTextVersions(sessionId);
        if (cancelled) return;
        setVersions(versionList.versions);
      } catch (err) {
        if (cancelled) return;
        console.error('[PlanningText] Failed to fetch:', err);
        setError('加载规划文本失败');
      } finally {
        if (!cancelled) setIsInitialLoading(false);
      }
    };

    void fetchData();
    return () => { cancelled = true; };
  }, [sessionId]);

  // Handle version change
  const handleVersionChange = useCallback(async (version: number) => {
    if (version === selectedVersion) return;

    setIsVersionLoading(true);
    setShowVersionDropdown(false);

    try {
      const doc = await planningApi.getPlanningText(sessionId, version);
      setDocument(doc);
      setSelectedVersion(version);
    } catch (err) {
      console.error('[PlanningText] Failed to fetch version:', err);
      setError('加载版本失败');
    } finally {
      setIsVersionLoading(false);
    }
  }, [sessionId, selectedVersion]);

  // Handle generate
  const runGenerate = useCallback(async (options?: {
    trigger_reason?: 'initial' | 'dimension_change' | 'manual';
    changed_dimensions?: string[];
    notice?: string;
    use_llm?: boolean;
  }) => {
    if (!sessionId || isGenerating) return;
    if (!isAnalysisComplete()) {
      setError('请等待分层分析全部完成后再生成规划文本');
      return;
    }

    setIsGenerating(true);
    setError(null);
    setRegenNotice(options?.notice || null);

    try {
      await planningApi.generatePlanningText(sessionId, {
        trigger_reason: options?.trigger_reason || (document ? 'manual' : 'initial'),
        changed_dimensions: options?.changed_dimensions,
        use_llm: options?.use_llm ?? true,
      });

      const doc = await planningApi.getPlanningText(sessionId);
      setDocument(doc);
      if (doc) {
        setSelectedVersion(doc.version);
      }

      const versionList = await planningApi.getPlanningTextVersions(sessionId);
      setVersions(versionList.versions);
    } catch (err) {
      console.error('[PlanningText] Failed to generate:', err);
      setError(options?.trigger_reason === 'dimension_change'
        ? '根据修订成果更新规划文本失败'
        : '生成规划文本失败，请确认分层分析已全部完成');
    } finally {
      setIsGenerating(false);
      setRegenNotice(null);
    }
  }, [isAnalysisComplete, sessionId, isGenerating, document]);

  const handleGenerate = useCallback(() => {
    void runGenerate();
  }, [runGenerate]);

  // Auto-regenerate planning text after dimension revisions complete.
  useEffect(() => {
    if (!sessionId || !planningTextRegenRequest || !isAnalysisComplete()) return;

    const { changedDimensions } = planningTextRegenRequest;
    clearPlanningTextRegenRequest();
    void runGenerate({
      trigger_reason: 'dimension_change',
      changed_dimensions: changedDimensions,
      notice: changedDimensions?.length
        ? `正在根据 ${changedDimensions.length} 项修订成果自动更新规划文本…`
        : '正在根据修订成果自动更新规划文本…',
    });
  }, [isAnalysisComplete, sessionId, planningTextRegenRequest, clearPlanningTextRegenRequest, runGenerate]);

  const handleExportDocx = useCallback(async () => {
    if (!document || isExporting) return;

    setIsExporting(true);
    setError(null);

    try {
      const exportName = projectName?.trim() || '村庄规划';
      await planningApi.exportPlanningTextDocx(sessionId, exportName);
    } catch (err) {
      console.error('[PlanningText] Failed to export DOCX:', err);
      setError(err instanceof Error ? err.message : '导出 DOCX 失败');
    } finally {
      setIsExporting(false);
    }
  }, [sessionId, document, isExporting, projectName]);

  const handleExportMarkdown = useCallback(() => {
    if (!document?.markdown_content || isExporting) return;

    setIsExporting(true);
    setError(null);
    try {
      const exportName = projectName?.trim() || '村庄规划';
      const blob = new Blob([document.markdown_content], { type: 'text/markdown;charset=utf-8' });
      downloadBlob(blob, `${exportName}_规划文本.md`);
    } finally {
      setIsExporting(false);
    }
  }, [document, isExporting, projectName]);

  // Loading state
  if (isInitialLoading) {
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
      <PlanningTextEmptyState
        embedded={embedded}
        isGenerating={isGenerating}
        regenNotice={regenNotice}
        error={error}
        onGenerate={handleGenerate}
      />
    );
  }

  // Document view
  return (
    <div className={`flex-1 h-full flex flex-col ${embedded ? 'bg-[#fbfcfb]' : 'bg-[#faf9f6]'}`}>
      {/* Header */}
      <div className={`flex flex-wrap items-center justify-between gap-3 shrink-0 border-b ${
        embedded ? 'border-[#e5efe9] bg-white px-4 py-2.5' : 'border-slate-200/80 bg-white/80 px-6 lg:px-8 py-4 backdrop-blur-sm'
      }`}>
        <div className="flex items-center gap-3 min-w-0">
          {!embedded && (
            <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-emerald-100 to-teal-100 flex items-center justify-center">
              <FontAwesomeIcon icon={faFileAlt} className="text-emerald-600" style={{ width: 16, height: 16 }} />
            </div>
          )}
          <div className="min-w-0">
            <h2 className={`font-semibold truncate ${embedded ? 'text-[15px] text-[#244c40]' : 'text-lg text-slate-800'}`}>规划文本</h2>
            <p className={`truncate ${embedded ? 'text-[10px] text-[#9ab2a8]' : 'text-xs text-slate-400'}`}>
              {document.article_count} 条条文 · 版本 {document.version}
            </p>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={() => setShowToc((open) => !open)}
            className={`rounded-lg px-2.5 py-1.5 text-[10px] font-medium transition-colors ${
              showToc
                ? embedded ? 'bg-[#e8f5ef] text-[#1f7a59]' : 'bg-emerald-100 text-emerald-700'
                : embedded ? 'border border-[#dcebe4] text-[#5d7f72]' : 'border border-slate-200 text-slate-600'
            }`}
          >
            {showToc ? '收起目录' : '显示目录'}
          </button>
          <button
            type="button"
            onClick={() => setShowEvidence((open) => !open)}
            className={`rounded-lg px-2.5 py-1.5 text-[10px] font-medium transition-colors ${
              showEvidence
                ? embedded ? 'bg-[#e8f5ef] text-[#1f7a59]' : 'bg-emerald-100 text-emerald-700'
                : embedded ? 'border border-[#dcebe4] text-[#5d7f72]' : 'border border-slate-200 text-slate-600'
            }`}
          >
            依据
          </button>

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

          {/* Export */}
          <button
            onClick={() => void handleExportMarkdown()}
            disabled={isExporting}
            className="px-3 py-2 rounded-lg text-sm bg-slate-100 text-slate-600 hover:bg-slate-200 transition-colors disabled:opacity-50 flex items-center gap-2"
          >
            <FontAwesomeIcon icon={faDownload} style={{ width: 12, height: 12 }} />
            <span>Markdown</span>
          </button>
          <button
            onClick={() => void handleExportDocx()}
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

      {revisionNotice && (
        <div className="flex items-center justify-between gap-3 border-b border-amber-200 bg-amber-50 px-6 py-2.5 text-sm text-amber-900">
          <span>{revisionNotice}</span>
          <button
            type="button"
            onClick={() => setRevisionNotice(null)}
            className="shrink-0 text-xs text-amber-700 hover:text-amber-900"
          >
            知道了
          </button>
        </div>
      )}

      {regenNotice && (
        <div className="flex items-center gap-2 border-b border-emerald-200 bg-emerald-50 px-6 py-2.5 text-sm text-emerald-800">
          <FontAwesomeIcon icon={faSpinner} className="animate-spin" style={{ width: 14, height: 14 }} />
          <span>{regenNotice}</span>
        </div>
      )}

      {/* Three-column document workbench with adjustable panels */}
      <div className="relative flex-1 min-h-0 overflow-hidden">
        {isVersionLoading && (
          <div className="absolute inset-0 z-20 flex items-center justify-center bg-white/70 backdrop-blur-[1px]">
            <div className="text-center">
              <FontAwesomeIcon icon={faSpinner} className="text-slate-400 animate-spin mb-3" style={{ width: 24, height: 24 }} />
              <p className="text-sm text-slate-500">切换版本中...</p>
            </div>
          </div>
        )}
        <div
          className="grid h-full min-h-0"
          style={{ gridTemplateColumns }}
        >
          {showToc && (
            <>
              <aside className="min-h-0 min-w-0 overflow-y-auto border-r border-emerald-100 bg-[#f7faf5] p-4">
                <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-emerald-700">文档目录</div>
                <div className="mt-3 space-y-0.5">
                  {headings.length > 0 ? headings.map((heading) => (
                    <button
                      key={`${heading.ordinal}-${heading.title}`}
                      type="button"
                      onClick={() => scrollToHeading(heading.ordinal)}
                      className={`block w-full rounded-md py-1.5 pr-2 text-left text-xs leading-5 text-slate-600 hover:bg-emerald-50 hover:text-emerald-800 ${heading.level === 1 ? 'pl-2 font-semibold' : heading.level === 2 ? 'pl-4' : 'pl-7 text-[11px]'}`}
                    >
                      {heading.title}
                    </button>
                  )) : <p className="rounded-lg bg-white p-3 text-xs leading-5 text-slate-400">文档暂未包含可识别的章节标题。</p>}
                </div>
              </aside>

              <div
                onPointerDown={(event) => beginColumnResize('toc', event)}
                className="group relative touch-none cursor-col-resize"
                title="拖动调整目录宽度"
              >
                <span className="absolute inset-y-0 left-1/2 w-px -translate-x-1/2 bg-emerald-100 transition-all group-hover:w-1 group-hover:bg-emerald-400" />
              </div>
            </>
          )}

          <main ref={contentRef} className={`min-h-0 min-w-0 overflow-y-auto p-4 sm:p-5 lg:p-6 ${embedded ? 'bg-[#f6faf7]' : 'bg-[#f3f8f2]'}`}>
            <div className="mx-auto w-full max-w-none">
              {error && (
                <div className="mb-4 p-4 bg-red-50 border border-red-200 rounded-xl text-red-600 text-sm flex items-center gap-2">
                  <FontAwesomeIcon icon={faTimes} style={{ width: 14, height: 14 }} />
                  <span>{error}</span>
                </div>
              )}

              <article className={`bg-white border border-emerald-100 p-5 sm:p-7 lg:p-9 ${
                embedded ? 'rounded-xl shadow-[0_8px_24px_rgba(38,95,74,0.05)]' : 'rounded-2xl shadow-sm'
              }`}>
                <PlanningDocumentMarkdown content={document.markdown_content || '暂无内容'} />
              </article>

              {/* Version Info */}
              <div className="mt-4 text-xs text-slate-400 text-center">
                生成于 {new Date(document.generated_at).toLocaleString('zh-CN')}
                {document.generation_duration_seconds && (
                  <span className="ml-2">· 耗时 {document.generation_duration_seconds.toFixed(1)}s</span>
                )}
              </div>
            </div>
          </main>

          {showEvidence && (
            <>
              <div
                onPointerDown={(event) => beginColumnResize('evidence', event)}
                className="group relative touch-none cursor-col-resize"
                title="拖动调整依据栏宽度"
              >
                <span className="absolute inset-y-0 left-1/2 w-px -translate-x-1/2 bg-emerald-100 transition-all group-hover:w-1 group-hover:bg-emerald-400" />
              </div>

              <aside className="min-h-0 min-w-0 overflow-y-auto border-l border-emerald-100 bg-white p-4">
            <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-emerald-700">检索依据</div>
            <p className="mt-1 text-[11px] leading-5 text-slate-500">仅呈现后端随本版本返回的来源，不补写或猜测引用。</p>
            <div className="mt-4 space-y-3">
              {evidence.length > 0 ? evidence.map((item, index) => (
                <div key={`${item.title}-${index}`} className="rounded-xl border border-emerald-100 bg-[#f8fbf7] p-3">
                  <div className="flex gap-2">
                    <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-emerald-100 text-[10px] font-semibold text-emerald-800">{index + 1}</span>
                    <div className="min-w-0">
                      <div className="break-words text-xs font-medium leading-5 text-slate-700">{item.title}</div>
                      {item.snippet && <p className="mt-1 line-clamp-4 text-[11px] leading-5 text-slate-500">{item.snippet}</p>}
                    </div>
                  </div>
                </div>
              )) : (
                <div className="rounded-xl border border-dashed border-amber-200 bg-amber-50/60 p-3 text-[11px] leading-5 text-amber-800">
                  当前版本未返回逐条检索依据。前端不会用静态法规或虚构来源填充此区域。
                </div>
              )}
            </div>

            <div className="mt-5 border-t border-slate-100 pt-4">
              <div className="text-xs font-medium text-slate-700">版本信息</div>
              <dl className="mt-2 space-y-2 text-[11px]">
                <div className="flex justify-between gap-3"><dt className="text-slate-400">文档版本</dt><dd className="text-slate-700">v{document.version}</dd></div>
                <div className="flex justify-between gap-3"><dt className="text-slate-400">条文数量</dt><dd className="text-slate-700">{document.article_count}</dd></div>
                <div className="flex justify-between gap-3"><dt className="text-slate-400">生成原因</dt><dd className="text-right text-slate-700">{document.trigger_reason === 'dimension_change' ? '维度更新' : document.trigger_reason === 'manual' ? '手动生成' : '初始生成'}</dd></div>
              </dl>
            </div>
          </aside>
            </>
          )}
        </div>
      </div>
    </div>
  );
});

export default PlanningTextViewer;
