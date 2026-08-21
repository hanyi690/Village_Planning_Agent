"use client";

import React, { memo, useCallback, useState, useEffect, useMemo, useRef } from "react";
import { motion, AnimatePresence } from "framer-motion";
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
  faMap,
} from "@fortawesome/free-solid-svg-icons";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";

import { usePlanningStore } from "../../store";
import {
  useStatus,
  useCurrentLayer,
  useReports,
  useDimensionProgressAll,
  useApprovalActions,
  useDimensionRagSources,
  useProjectName,
  usePendingReviewLayer,
  useHasGisLayers,
  useCompletedLayers,
  useCascadeChain,
  useRevisionCompletedKeys,
  useExecutingDimensions,
  useIsPaused,
} from "../../hooks";
import { dataApi, planningApi } from "../../api";
import type {
  CompareSession,
  KnowledgeSourceItem,
  DimensionVersion,
  PlanningDependencyGraphResponse,
} from "../../api/types";
import type { LayerCompletedMessage } from "../../types";
import VillageInputForm from "../VillageInputForm";
import MarkdownRenderer from "../ui/MarkdownRenderer";
import {
  LAYER_VALUE_MAP,
  LAYER_IDS,
  NAV_KEYS,
} from "@/features/planning/constants";
import {
  DIMENSIONS_BY_LAYER,
  getDimensionLayer,
  getDimensionName,
  getDimensionIcon,
} from "../../config/dimensions";
import CascadePanel from "../CascadePanel";
import AnalysisSidePanel from "./AnalysisSidePanel";
import AnalysisProgressBanner from "./AnalysisProgressBanner";
import AnalysisNotStartedPlaceholder from "./AnalysisNotStartedPlaceholder";
import { TopicDependencyGraph } from "./TopicDependencyGraph";
import PlanningBootstrapPanel from "./PlanningBootstrapPanel";
import { usePlanningBootstrapStage } from "../../hooks/usePlanningBootstrapStage";
import { useActiveAnalysisFocus } from "../../hooks/useActiveAnalysisFocus";
import { cn } from "../../utils/cn";
import { createErrorMessage, createWarningMessage } from "../../utils";
import {
  isL3HumanReview,
  isSpatialWorkflowPhase,
  shouldAutoStartSpatialPolling,
} from "../../utils/spatial-phase";

interface DimensionDisplayStatus {
  label: string;
  color: string;
  dotColor: string;
  pulse: boolean;
}

type StructuredClaim = Record<string, unknown>;

interface L1FactRecord {
  fact_id?: string;
  dimension_key?: string;
  fact_kind?: string;
  semantic_type?: string;
  statement?: string;
  subject_scope?: string;
  spatial_hint?: string;
  source_span?: string;
  confidence?: number;
  source_refs?: string[];
  attributes?: Record<string, unknown>;
}

interface RAGDisplayDocument {
  title: string;
  snippet: string;
  source?: string;
  score?: number;
  matched_query?: string;
}

interface RAGDisplaySources {
  query: string;
  documents: RAGDisplayDocument[];
}

interface StructuredClaimReport {
  schema_version?: string;
  dimension_key?: string;
  claims: StructuredClaim[];
  diagnostics?: string[];
}

function parseStructuredClaimReport(content: string): StructuredClaimReport | null {
  const trimmed = content.trim();
  if (!trimmed.startsWith('{')) return null;
  try {
    const parsed = JSON.parse(trimmed) as Record<string, unknown>;
    if (!Array.isArray(parsed.claims)) return null;
    return {
      schema_version: typeof parsed.schema_version === 'string' ? parsed.schema_version : undefined,
      dimension_key: typeof parsed.dimension_key === 'string' ? parsed.dimension_key : undefined,
      claims: parsed.claims.filter((claim): claim is StructuredClaim => Boolean(claim && typeof claim === 'object')),
      diagnostics: Array.isArray(parsed.diagnostics)
        ? parsed.diagnostics.filter((item): item is string => typeof item === 'string')
        : [],
    };
  } catch {
    return null;
  }
}

function readableClaimValue(value: unknown): string {
  if (Array.isArray(value)) return value.filter(Boolean).join('、') || '未提供';
  if (value == null || value === '') return '未提供';
  if (typeof value === 'object') return '已提供结构化参数';
  return String(value);
}

function StructuredClaimReportView({ content }: { content: string }) {
  const report = parseStructuredClaimReport(content);
  if (!report) return <MarkdownRenderer content={content || '暂无内容'} />;

  return (
    <div className="space-y-3">
      <div className="rounded-xl border border-[#cfe8dc] bg-[#f4fbf7] px-4 py-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <div className="text-[11px] font-semibold uppercase tracking-wide text-[#3b9673]">结构化规划意图</div>
            <div className="mt-1 text-[13px] font-semibold text-[#244c40]">
              已生成 {report.claims.length} 条带证据的规划判断
            </div>
          </div>
          <span className="rounded-full bg-white px-2.5 py-1 text-[10px] text-[#6f9385]">
            {report.schema_version ? `Schema ${report.schema_version}` : '结构化结果'}
          </span>
        </div>
        <p className="mt-2 text-[11px] leading-5 text-[#66867a]">
          当前后端已返回可供空间编译使用的规划意图，但没有返回叙述性正文；以下内容按规划判断整理展示，未添加任何虚拟几何或成果图层。
        </p>
      </div>

      {report.claims.map((claim, index) => {
        const statement = readableClaimValue(claim.statement);
        const locations = claim.location_hints ?? claim.locationHints;
        const evidence = claim.evidence_refs ?? claim.evidenceRefs;
        const category = claim.suggested_category ?? claim.suggestedCategory;
        const outputKind = claim.suggested_output_kind ?? claim.suggestedOutputKind;
        const action = claim.intervention_action ?? claim.interventionAction;
        return (
          <article key={String(claim.claim_id ?? index)} className="rounded-xl border border-[#e1eee8] bg-white p-3 shadow-[0_5px_18px_rgba(42,102,79,0.04)]">
            <div className="flex items-start gap-2">
              <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-[#e3f4ec] text-[11px] font-semibold text-[#2f8b69]">{index + 1}</span>
              <div className="min-w-0 flex-1">
                <div className="text-[12px] font-semibold leading-5 text-[#2d5d4e]">{statement}</div>
                <div className="mt-2 flex flex-wrap gap-1.5 text-[10px]">
                  <span className="rounded-full bg-[#eef7f2] px-2 py-1 text-[#397a61]">类别：{readableClaimValue(category)}</span>
                  <span className="rounded-full bg-[#f5f4fb] px-2 py-1 text-[#706b91]">输出：{readableClaimValue(outputKind)}</span>
                  <span className="rounded-full bg-[#fff7e8] px-2 py-1 text-[#9a7428]">动作：{readableClaimValue(action)}</span>
                </div>
              </div>
            </div>
            <dl className="mt-3 grid gap-x-4 gap-y-2 border-t border-[#edf4f0] pt-2 text-[11px] sm:grid-cols-2">
              <div><dt className="text-[#9ab2a8]">空间提示</dt><dd className="mt-0.5 text-[#55786b]">{readableClaimValue(locations)}</dd></div>
              <div><dt className="text-[#9ab2a8]">目标引用</dt><dd className="mt-0.5 text-[#55786b]">{readableClaimValue(claim.objective_refs ?? claim.objectiveRefs)}</dd></div>
              <div><dt className="text-[#9ab2a8]">证据引用</dt><dd className="mt-0.5 text-[#55786b]">{readableClaimValue(evidence)}</dd></div>
              <div><dt className="text-[#9ab2a8]">不确定性</dt><dd className="mt-0.5 text-[#55786b]">{readableClaimValue(claim.uncertainty)}</dd></div>
            </dl>
          </article>
        );
      })}

      {report.diagnostics && report.diagnostics.length > 0 && (
        <details className="rounded-xl border border-[#f0dfb7] bg-[#fffaf0] px-3 py-2">
          <summary className="cursor-pointer text-[11px] font-semibold text-[#96722d]">
            规范化诊断（{report.diagnostics.length} 条）
          </summary>
          <ul className="mt-2 space-y-1 text-[10px] leading-5 text-[#8c7446]">
            {report.diagnostics.map((diagnostic, index) => <li key={`${diagnostic}-${index}`}>{diagnostic}</li>)}
          </ul>
        </details>
      )}

      <details className="rounded-xl border border-[#e5eee9] bg-[#fafcfb] px-3 py-2">
        <summary className="cursor-pointer text-[11px] font-medium text-[#6d8c80]">查看原始结构（机器格式）</summary>
        <pre className="mt-2 max-h-80 overflow-auto rounded-lg bg-[#f0f6f3] p-3 font-mono text-[10px] leading-relaxed text-[#4a6a5f]">{JSON.stringify(report, null, 2)}</pre>
      </details>
    </div>
  );
}

function ReportContent({ content, fallback = '暂无内容' }: { content: string; fallback?: string }) {
  if (!content.trim()) return <div className="py-8 text-center text-sm text-[#9ab2a8]">{fallback}</div>;
  const parsed = parseStructuredClaimReport(content);
  if (!parsed) return <MarkdownRenderer content={content} />;

  let reportBody = '';
  try {
    const raw = JSON.parse(content) as Record<string, unknown>;
    reportBody = typeof raw.report_body === 'string' ? raw.report_body.trim() : '';
  } catch {
    // parseStructuredClaimReport already validated the JSON shape.
  }

  if (reportBody) {
    return (
      <div className="space-y-3">
        <MarkdownRenderer content={reportBody} />
        <details className="rounded-xl border border-[#e5eee9] bg-[#fafcfb] px-3 py-2">
          <summary className="cursor-pointer text-[11px] font-medium text-[#6d8c80]">查看内部结构化意图（不作为正文）</summary>
          <div className="mt-3"><StructuredClaimReportView content={content} /></div>
        </details>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="rounded-xl border border-[#f0dfb7] bg-[#fffaf0] px-3 py-2 text-[11px] leading-5 text-[#8a6420]">
        本维度没有返回可阅读的 report_body。下面仅展示后端返回的内部 claims，不能视为规划正文；待后端重新生成双通道结果后再显示正文。
      </div>
      <StructuredClaimReportView content={content} />
    </div>
  );
}

function GroundingEvidencePanel({
  dimensionKey,
  facts,
  rag,
}: {
  dimensionKey: string;
  facts: L1FactRecord[];
  rag?: RAGDisplaySources;
}) {
  const dimensionFacts = facts.filter((fact) => fact.dimension_key === dimensionKey);
  const visibleFacts = (dimensionFacts.length > 0 ? dimensionFacts : facts).slice(0, 10);
  const hasDirectFacts = dimensionFacts.length > 0;

  return (
    <section className="rounded-2xl border border-[#dcebe4] bg-[#f8fcfa] p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <div className="text-[11px] font-semibold uppercase tracking-wide text-[#3b9673]">证据与事实</div>
          <div className="mt-1 text-sm font-semibold text-[#315f50]">L1 fact 与 RAG 检索结果</div>
        </div>
        <div className="flex flex-wrap gap-1.5 text-[10px]">
          <span className="rounded-full bg-white px-2 py-1 text-[#5e8778]">L1 fact {dimensionFacts.length} 条</span>
          <span className="rounded-full bg-white px-2 py-1 text-[#5e8778]">RAG {rag?.documents.length ?? 0} 条</span>
        </div>
      </div>

      <div className="mt-3 space-y-3">
        <div className="rounded-xl border border-[#e2eee8] bg-white p-3">
          <div className="flex items-center justify-between gap-2">
            <div className="text-xs font-semibold text-[#477666]">L1 已审计事实</div>
            {!hasDirectFacts && facts.length > 0 && <span className="text-[10px] text-[#a17c4c]">本维度无直接 fact，显示全局事实</span>}
          </div>
          {visibleFacts.length > 0 ? (
            <div className="mt-2 space-y-2">
              {visibleFacts.map((fact, index) => (
                <div key={fact.fact_id || `${fact.dimension_key}-${index}`} className="rounded-lg bg-[#f5faf7] px-2.5 py-2 text-[11px] leading-5 text-[#55786b]">
                  <div className="font-medium text-[#356c59]">{fact.statement || fact.subject_scope || '未命名事实'}</div>
                  <div className="mt-0.5 flex flex-wrap gap-x-3 gap-y-0.5 text-[10px] text-[#829f93]">
                    <span>来源维度：{fact.dimension_key || 'L1'}</span>
                    {fact.spatial_hint && <span>空间提示：{fact.spatial_hint}</span>}
                    {typeof fact.confidence === 'number' && <span>置信度：{Math.round(fact.confidence * 100)}%</span>}
                  </div>
                  {fact.source_span && <div className="mt-1 line-clamp-2 text-[10px] text-[#78968b]">原文：{fact.source_span}</div>}
                </div>
              ))}
            </div>
          ) : (
            <div className="mt-2 rounded-lg bg-[#fff8e8] px-2.5 py-2 text-[11px] leading-5 text-[#8a6420]">当前会话已返回 L1 快照，但没有可关联的 fact_records。</div>
          )}
        </div>

        <div className="rounded-xl border border-[#e2eee8] bg-white p-3">
          <div className="flex items-center justify-between gap-2">
            <div className="text-xs font-semibold text-[#477666]">RAG 检索证据</div>
            {rag?.query && <span className="max-w-[60%] truncate text-[10px] text-[#829f93]">检索词：{rag.query}</span>}
          </div>
          {rag && rag.documents.length > 0 ? (
            <div className="mt-2 space-y-2">
              {rag.documents.slice(0, 5).map((document, index) => (
                <div key={`${document.title}-${index}`} className="rounded-lg bg-[#f5faf7] px-2.5 py-2 text-[11px] leading-5 text-[#55786b]">
                  <div className="font-medium text-[#356c59]">{document.title || '未命名检索片段'}</div>
                  {document.source && <div className="text-[10px] text-[#829f93]">来源：{document.source}</div>}
                  {document.snippet && <div className="mt-1 line-clamp-3 text-[10px] text-[#78968b]">{document.snippet}</div>}
                </div>
              ))}
            </div>
          ) : (
            <div className="mt-2 rounded-lg bg-[#f1f6f4] px-2.5 py-2 text-[11px] leading-5 text-[#78968b]">当前维度没有 RAG 检索结果：可能未启用检索、知识库不可用，或历史事件没有返回结果。页面不补造检索内容。</div>
          )}
        </div>
      </div>
    </section>
  );
}

function getDimensionDisplayStatus(opts: {
  isInCascade: boolean;
  isRevisionCompleted: boolean;
  isExecuting: boolean;
  isStreaming: boolean;
  isCompleted: boolean;
}): DimensionDisplayStatus {
  const {
    isInCascade,
    isRevisionCompleted,
    isExecuting,
    isStreaming,
    isCompleted,
  } = opts;
  if (isInCascade && isRevisionCompleted) {
    return {
      label: "已修复",
      color: "text-emerald-600",
      dotColor: "bg-emerald-500",
      pulse: false,
    };
  }
  if (isInCascade && isExecuting) {
    return {
      label: "修复中...",
      color: "text-amber-600",
      dotColor: "bg-amber-400",
      pulse: true,
    };
  }
  if (isInCascade && !isCompleted) {
    return {
      label: "待修复",
      color: "text-amber-500",
      dotColor: "bg-amber-300",
      pulse: false,
    };
  }
  if (isExecuting || isStreaming) {
    return {
      label: isStreaming ? "生成中..." : "分析中...",
      color: "text-sky-600",
      dotColor: "bg-sky-400",
      pulse: true,
    };
  }
  if (isCompleted) {
    return {
      label: "已完成",
      color: "text-emerald-600",
      dotColor: "bg-emerald-500",
      pulse: false,
    };
  }
  return {
    label: "待分析",
    color: "text-slate-400",
    dotColor: "bg-slate-300",
    pulse: false,
  };
}

interface ReportViewerProps {
  onStartPlanning: (data: {
    projectName: string;
    villageData?: string;
    villageName?: string;
    province?: string;
    city?: string;
    county?: string;
    township?: string;
    planningPeriod?: string;
    taskDescription?: string;
    constraints?: string;
    villageDataFiles?: File[];
    taskFiles?: File[];
    constraintFiles?: File[];
  }) => void;
  onViewProcess: () => void;
  /** Embedded in planning overview: greener theme, no duplicate nav chrome. */
  variant?: "default" | "embedded";
  /** Hide the all-layer dimension grid in overview mode (navigation lives in sidebar). */
  hideOverviewDimensionGrid?: boolean;
  /** Chat panel slot for embedded analysis side panel. */
  chatPanel?: React.ReactNode;
  sessionConnected?: boolean;
  /** Switch to task settings from embedded analysis idle state. */
  onGoToTaskSettings?: () => void;
}

const ReportViewer = memo(function ReportViewer({
  onStartPlanning,
  onViewProcess,
  variant = "default",
  hideOverviewDimensionGrid = false,
  chatPanel,
  sessionConnected,
  onGoToTaskSettings,
}: ReportViewerProps) {
  const isEmbedded = variant === "embedded";
  const surfaceClass = isEmbedded ? "bg-[#fbfcfb]" : "bg-[#faf9f6]";
  const headerClass = isEmbedded
    ? "border-b border-[#e5efe9] bg-white"
    : "border-b border-slate-200/80 bg-white/80 backdrop-blur-sm";
  const titleClass = isEmbedded ? "text-[#244c40]" : "text-slate-800";
  const mutedClass = isEmbedded ? "text-[#78968b]" : "text-slate-400";
  const iconWrapClass = isEmbedded
    ? "bg-[#e8f5ef] text-[#2d8c6d]"
    : "bg-gradient-to-br from-amber-100 to-orange-100 text-amber-600";
  const secondaryBtnClass = isEmbedded
    ? "bg-[#f3f8f5] text-[#4d7568] hover:bg-[#e8f3ed]"
    : "bg-slate-100 text-slate-600 hover:bg-slate-200";
  const primaryBtnClass = isEmbedded
    ? "bg-[#3fb288] hover:bg-[#359f7b]"
    : "bg-[#0ea5e9] hover:bg-[#0284c7]";
  const selectedNavigationKey = usePlanningStore(
    (state) => state.selectedNavigationKey,
  );
  const streamingContent = usePlanningStore((state) => state.streamingContent);
  const sessionId = usePlanningStore((state) => state.sessionId);
  const status = useStatus();
  const currentLayer = useCurrentLayer();
  const pendingReviewLayer = usePendingReviewLayer();
  const hasGisLayers = useHasGisLayers();
  const gisGenerating = usePlanningStore((state) => state.gisGenerating);
  const gisTriggerPending = usePlanningStore((state) => state.gisTriggerPending);
  const messages = usePlanningStore((state) => state.messages);
  const stepMode = usePlanningStore((state) => state.step_mode);
  const executingDimensions = useExecutingDimensions();
  const revisionDraft = usePlanningStore((state) => state.revisionDraft);
  const clearRevisionDraft = usePlanningStore((state) => state.clearRevisionDraft);
  const reports = useReports();
  const dimensionProgress = useDimensionProgressAll();
  const { approve, isSubmitting } = useApprovalActions();
  const projectName = useProjectName();
  const gisProbeRunRef = useRef(0);
  const [l1Facts, setL1Facts] = useState<L1FactRecord[]>([]);
  const [directoryView, setDirectoryView] = useState<'list' | 'graph'>('list');
  const [dependencyGraph, setDependencyGraph] = useState<PlanningDependencyGraphResponse | null>(null);
  const [dependencyGraphStatus, setDependencyGraphStatus] = useState<'loading' | 'ready' | 'error'>('loading');

  // Spatial output is produced by the backend workflow at DELIVER. There is no
  // client-side generation job to poll: when DELIVER has not produced a
  // snapshot, the UI must explain that state and keep the real basemap visible.
  useEffect(() => {
    if (!sessionId || !gisGenerating) return;
    const probeRun = ++gisProbeRunRef.current;
    const probe = async () => {
      try {
        const snapshot = await planningApi.getRenderLayers(sessionId);
        if (gisProbeRunRef.current !== probeRun) return;
        if (snapshot.layers.length > 0) {
          usePlanningStore.getState().addMessage(
            createWarningMessage(`空间成果快照已返回 ${snapshot.layers.length} 个真实图层，地图将按 DELIVER 快照展示。`),
          );
        } else {
          usePlanningStore.getState().addMessage(
            createWarningMessage(
              "当前会话尚未产出 DELIVER 空间快照。地图保留真实现状底图；规划图层将在后端完成空间交付后显示。",
            ),
          );
        }
      } catch (error) {
        if (gisProbeRunRef.current !== probeRun) return;
        const detail = error instanceof Error ? `（${error.message}）` : "";
        usePlanningStore.getState().addMessage(
          createErrorMessage(`空间成果查询失败${detail}，当前仍显示真实现状底图。`),
        );
      } finally {
        if (gisProbeRunRef.current === probeRun) {
          usePlanningStore.setState({
            gisGenerating: false,
            gisTriggerPending: false,
          });
        }
      }
    };

    void probe();
    return () => {
      if (gisProbeRunRef.current === probeRun) {
        gisProbeRunRef.current += 1;
      }
    };
  }, [sessionId, gisGenerating]);

  useEffect(() => {
    let cancelled = false;
    setL1Facts([]);
    if (!sessionId) return undefined;
    planningApi.getArtifact(sessionId, 'l1_snapshot')
      .then((artifact) => {
        if (cancelled) return;
        const payload = artifact.payload as { fact_records?: unknown };
        const records = Array.isArray(payload.fact_records)
          ? payload.fact_records.filter((fact): fact is L1FactRecord => Boolean(fact && typeof fact === 'object'))
          : [];
        setL1Facts(records);
      })
      .catch(() => {
        if (!cancelled) setL1Facts([]);
      });
    return () => {
      cancelled = true;
    };
  }, [sessionId]);

  useEffect(() => {
    let cancelled = false;
    planningApi.getDependencyGraph()
      .then((value) => {
        if (!cancelled) {
          setDependencyGraph(value);
          setDependencyGraphStatus('ready');
        }
      })
      .catch(() => {
        if (!cancelled) {
          setDependencyGraph(null);
          setDependencyGraphStatus('error');
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Compare mode state
  const [compareMode, setCompareMode] = useState(false);
  const [availableSessions, setAvailableSessions] = useState<CompareSession[]>(
    [],
  );
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(
    null,
  );
  const [compareContent, setCompareContent] = useState<string>("");
  const [compareKnowledgeSources, setCompareKnowledgeSources] = useState<
    KnowledgeSourceItem[]
  >([]);
  const [isLoadingSessions, setIsLoadingSessions] = useState(false);
  const [isLoadingCompare, setIsLoadingCompare] = useState(false);

  // Version history state
  const [availableVersions, setAvailableVersions] = useState<
    DimensionVersion[]
  >([]);
  const [selectedVersion, setSelectedVersion] = useState<number | null>(null);
  const [isLoadingVersions, setIsLoadingVersions] = useState(false);

  // Drag and drop state
  const [isDragOver, setIsDragOver] = useState(false);

  const [feedback, setFeedback] = useState("");
  const [ragExpanded, setRagExpanded] = useState(true);
  const [selectedDocIndex, setSelectedDocIndex] = useState<number | null>(null);

  // Dimension selector state for cascade revision
  const [selectedDimensions, setSelectedDimensions] = useState<string[]>([]);
  const [showDimensionSelector, setShowDimensionSelector] = useState(true);
  const [highlightReviewBox, setHighlightReviewBox] = useState(false);
  const [reviewFocusKey, setReviewFocusKey] = useState(0);
  const reviewPanelRef = useRef<HTMLDivElement>(null);
  const isPaused = useIsPaused();

  // Right-side AI assistant can prepare a revision draft for this review form.
  useEffect(() => {
    if (!revisionDraft) return;
    setFeedback(revisionDraft.feedback || "");
    setSelectedDimensions(revisionDraft.dimensions || []);
    setShowDimensionSelector((revisionDraft.dimensions || []).length > 0);
    setHighlightReviewBox(true);
    setReviewFocusKey((key) => key + 1);
    clearRevisionDraft();
    window.requestAnimationFrame(() => {
      reviewPanelRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    });
    const timer = window.setTimeout(() => setHighlightReviewBox(false), 4000);
    return () => window.clearTimeout(timer);
  }, [revisionDraft, clearRevisionDraft]);

  // Get completed dimensions for current review layer
  const completedLayers = useCompletedLayers();
  const completedDimensions = usePlanningStore(
    (state) => state.completedDimensions,
  );

  // Robust fallback: sometimes the backend pause event arrives without a usable
  // pendingReviewLayer after Layer 2/3. Keep the review/revision panel visible
  // whenever the app is paused and at least one layer has reports.
  const reviewLayerForPanel = useMemo(() => {
    if (pendingReviewLayer) return pendingReviewLayer;

    const hasLayerReports = (layer: number) => {
      const layerReports =
        reports[`layer${layer}` as "layer1" | "layer2" | "layer3"] || {};
      return Object.keys(layerReports).length > 0;
    };

    // Direct paused fallback: show the latest layer that has reports.
    if ((status as string) === "paused") {
      for (let l = 3; l >= 1; l--) {
        if (hasLayerReports(l)) return l;
      }
    }

    // Step-mode safety net: if a layer is complete and the next layer has not started,
    // the review/revision panel must still be visible even if the explicit pause event was missed.
    if (stepMode && executingDimensions.length === 0) {
      for (let l = 3; l >= 1; l--) {
        if (!completedLayers[l as 1 | 2 | 3]) continue;
        if ((currentLayer ?? 0) > l) continue;
        const nextStarted = l < 3 && (hasLayerReports(l + 1) || (currentLayer ?? 0) > l);
        if (!nextStarted && hasLayerReports(l)) return l;
      }
    }

    return null;
  }, [pendingReviewLayer, status, reports, stepMode, executingDimensions.length, completedLayers, currentLayer]);
  const cascadeChain = useCascadeChain();
  const revisionCompletedKeys = useRevisionCompletedKeys();

  // All completed dimensions across all finished layers (for cascade revision)
  // Use DIMENSIONS_BY_LAYER order instead of completedDimensions order
  const allCompletedDimsByLayer = useMemo(() => {
    const result: { layer: number; dims: string[] }[] = [];
    for (let l = 1; l <= 3; l++) {
      const completed = new Set(
        completedDimensions[`layer${l}` as "layer1" | "layer2" | "layer3"] ||
          [],
      );
      const orderedDims = (DIMENSIONS_BY_LAYER[l] || []).filter((d) =>
        completed.has(d),
      );
      if (orderedDims.length > 0) {
        result.push({ layer: l, dims: orderedDims });
      }
    }
    return result;
  }, [completedDimensions]);
  const allCompletedDimsCount = allCompletedDimsByLayer.reduce(
    (sum, g) => sum + g.dims.length,
    0,
  );

  const dimProgressKeyForRag = selectedNavigationKey?.startsWith("dim:")
    ? selectedNavigationKey.slice(4)
    : "";
  const ragSources = useDimensionRagSources(dimProgressKeyForRag);
  const historicalRagSources = useMemo(() => {
    const dimensionKey = dimProgressKeyForRag.split('_').slice(1).join('_');
    if (!dimensionKey) return undefined;
    const layerMessages = messages
      .filter((message): message is LayerCompletedMessage => message.type === 'layer_completed')
      .sort((left, right) => right.timestamp.getTime() - left.timestamp.getTime());
    const sources = layerMessages.find((message) => message.dimensionKnowledgeSources?.[dimensionKey])?.dimensionKnowledgeSources?.[dimensionKey];
    if (!sources || sources.length === 0) return undefined;
    return {
      query: '',
      documents: sources.map((source) => ({
        title: source.source || '知识库片段',
        snippet: source.content || '',
        source: source.source,
      })),
    };
  }, [dimProgressKeyForRag, messages]);
  const effectiveRagSources: RAGDisplaySources | undefined = ragSources
    ? { query: ragSources.query, documents: ragSources.documents }
    : historicalRagSources;

  // Fetch sessions when entering compare mode
  useEffect(() => {
    if (compareMode && projectName) {
      setIsLoadingSessions(true);
      dataApi
        .getVillageSessions(projectName)
        .then((sessions) => {
          const compareSessions = sessions
            .filter((s) => s.session_id !== sessionId)
            .map((s) => ({
              id: s.session_id,
              name: `${projectName} - ${new Date(s.created_at).toLocaleDateString("zh-CN")}`,
              timestamp: s.created_at,
              isCompleted: s.completed_at !== null,
            }));
          setAvailableSessions(compareSessions);
        })
        .catch(console.error)
        .finally(() => setIsLoadingSessions(false));
    }
  }, [compareMode, projectName, sessionId]);

  // Fetch version history when entering compare mode
  useEffect(() => {
    if (compareMode && sessionId && dimProgressKeyForRag) {
      const dimKey =
        dimProgressKeyForRag.split("_").slice(1).join("_") ||
        dimProgressKeyForRag;
      setIsLoadingVersions(true);
      dataApi
        .getDimensionVersions(sessionId, dimKey)
        .then((versions) => {
          // Exclude the latest version from the dropdown (it's the "current" shown on the left)
          if (versions.length > 1) {
            const maxVer = Math.max(...versions.map((v) => v.version));
            setAvailableVersions(versions.filter((v) => v.version < maxVer));
          } else {
            setAvailableVersions([]);
          }
        })
        .catch(() => setAvailableVersions([]))
        .finally(() => setIsLoadingVersions(false));
    }
  }, [compareMode, sessionId, dimProgressKeyForRag]);

  // Handle session selection for compare
  const handleSessionSelect = useCallback(
    async (targetSessionId: string, version?: number) => {
      if (!projectName || !dimProgressKeyForRag) return;

      // Extract pure dimKey from format "layer_dimKey"
      const dimKey =
        dimProgressKeyForRag.split("_").slice(1).join("_") ||
        dimProgressKeyForRag;

      setSelectedSessionId(targetSessionId);
      setIsLoadingCompare(true);

      try {
        const report = await dataApi.getCrossSessionReport(
          projectName,
          dimKey,
          targetSessionId,
          version,
        );
        setCompareContent(report.content || "");
        setCompareKnowledgeSources(report.knowledge_sources || []);
      } catch (error) {
        console.error("[Compare] Failed to fetch compare report:", error);
        setCompareContent("");
        setCompareKnowledgeSources([]);
      } finally {
        setIsLoadingCompare(false);
      }
    },
    [projectName, dimProgressKeyForRag],
  );

  // Handle version selection for current session compare
  const handleVersionSelect = useCallback(
    async (version: number) => {
      if (!sessionId) return;
      setSelectedVersion(version);
      await handleSessionSelect(sessionId, version);
    },
    [sessionId, handleSessionSelect],
  );

  // Handle compare button click
  const handleCompareClick = useCallback(() => {
    setCompareMode(true);
    setSelectedSessionId(null);
    setSelectedVersion(null);
    setCompareContent("");
    setCompareKnowledgeSources([]);
  }, []);

  // Handle exit compare mode
  const handleExitCompare = useCallback(() => {
    setCompareMode(false);
    setSelectedSessionId(null);
    setSelectedVersion(null);
    setCompareContent("");
    setCompareKnowledgeSources([]);
  }, []);

  // Handle drag and drop for compare
  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = "copy";
    setIsDragOver(true);
  }, []);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragOver(false);
  }, []);

  const handleDrop = useCallback(
    async (e: React.DragEvent) => {
      e.preventDefault();
      setIsDragOver(false);

      try {
        const data = JSON.parse(e.dataTransfer.getData("application/json"));

        if (data.sessionId && data.villageName) {
          // Enter compare mode and select the dropped session
          setCompareMode(true);
          setSelectedVersion(null);
          await handleSessionSelect(data.sessionId);
        }
      } catch (error) {
        console.error("[Compare] Failed to parse drop data:", error);
      }
    },
    [handleSessionSelect],
  );

  const handleSubmit = useCallback(
    (data: {
      projectName: string;
      villageName?: string;
      province?: string;
      city?: string;
      county?: string;
      township?: string;
      planningPeriod?: string;
      villageData?: string;
      taskDescription?: string;
      constraints?: string;
      villageDataFiles?: File[];
      taskFiles?: File[];
      constraintFiles?: File[];
    }) =>
      onStartPlanning({
        projectName: data.projectName,
        villageData: data.villageData || "",
        villageName: data.villageName || data.projectName,
        province: data.province,
        city: data.city,
        county: data.county,
        township: data.township,
        planningPeriod: data.planningPeriod,
        taskDescription: data.taskDescription,
        constraints: data.constraints,
        villageDataFiles: data.villageDataFiles,
        taskFiles: data.taskFiles,
        constraintFiles: data.constraintFiles,
      }),
    [onStartPlanning],
  );

  const handleTriggerGIS = useCallback(async () => {
    if (!sessionId || gisTriggerPending || gisGenerating) return;
    // v1: spatial layout is produced by the workflow itself; this just activates
    // the polling wait for delivery_status (useDeliverySync fetches /map-layers).
    usePlanningStore.setState({
      gisTriggerPending: false,
      gisGenerating: true,
      isRightPanelExpanded: true,
      processPanelTab: "map",
    });
  }, [sessionId, gisTriggerPending, gisGenerating]);

  const handleRejectWithFeedback = useCallback(async () => {
    if (!sessionId || isSubmitting) return;
    try {
      const { resolveActiveInterrupt } = await import('../../utils/interrupt-resume');
      const draft = usePlanningStore.getState().revisionDraft;
      const targetDims =
        selectedDimensions.length > 0
          ? selectedDimensions
          : draft?.dimensions?.length
            ? draft.dimensions
            : undefined;
      const feedbackText = feedback.trim() || draft?.feedback?.trim() || '需要修改';

      if (!targetDims?.length) {
        usePlanningStore.getState().addMessage(
          createErrorMessage('请先选择需要重新生成的维度。'),
        );
        usePlanningStore.getState().setStatus('paused');
        setShowDimensionSelector(true);
        return;
      }

      await resolveActiveInterrupt(sessionId, 'reject', {
        feedback: feedbackText,
        dimensions: targetDims,
      });

      const startedDims = targetDims;
      const firstDim = startedDims[0];
      const layer = getDimensionLayer(firstDim);
      usePlanningStore.setState((state) => {
        state.selectedNavigationKey = NAV_KEYS.dim(`${layer}_${firstDim}`);
        for (const dim of startedDims) {
          const dimLayer = getDimensionLayer(dim);
          const layerKey = `layer${dimLayer}` as 'layer1' | 'layer2' | 'layer3';
          if (state.reports[layerKey]) {
            delete state.reports[layerKey][dim];
          }
          delete state.streamingContent[`${dimLayer}_${dim}`];
        }
        state.status = 'revising';
      });

      setFeedback('');
      setSelectedDimensions([]);
      setShowDimensionSelector(false);
      usePlanningStore.getState().triggerSseReconnect();
    } catch (error) {
      console.error('Reject with feedback failed:', error);
      usePlanningStore.getState().addMessage(
        createErrorMessage(`提交修订失败：${error instanceof Error ? error.message : '未知错误'}`),
      );
      usePlanningStore.getState().setStatus('paused');
    }
  }, [sessionId, isSubmitting, feedback, selectedDimensions]);

  // All useMemo hooks must be before any conditional return (React hooks rule)
  const totalDims = useMemo(
    () =>
      [1, 2, 3].reduce(
        (sum, l) => sum + (DIMENSIONS_BY_LAYER[l]?.length || 0),
        0,
      ),
    [],
  );
  const completedDimsCount = useMemo(
    () =>
      [1, 2, 3].reduce((sum, l) => {
        const lr = reports[`layer${l}` as keyof typeof reports] || {};
        return sum + Object.keys(lr).length;
      }, 0),
    [reports],
  );

  const activeAnalysisFocus = useActiveAnalysisFocus();
  const planningBootstrap = usePlanningBootstrapStage();
  const showInputForm = (status as string) === "idle" && !isEmbedded;
  const embeddedNotStarted = isEmbedded
    && !sessionId
    && (status as string) === 'idle'
    && completedDimsCount === 0;

  const phase = usePlanningStore((state) => state.phase);
  const humanReview = usePlanningStore((state) => state.humanReview);

  const l3GateBlocked = useMemo(
    () => isL3HumanReview(humanReview),
    [humanReview],
  );

  const spatialLayoutActive = useMemo(
    () => shouldAutoStartSpatialPolling({
      phase,
      hasGisLayers,
      humanReviewPending: l3GateBlocked,
    }),
    [phase, hasGisLayers, l3GateBlocked],
  );

  useEffect(() => {
    if (!spatialLayoutActive || hasGisLayers) return;
    usePlanningStore.setState({
      gisGenerating: false,
      gisTriggerPending: false,
      isRightPanelExpanded: true,
      processPanelTab: "map",
    });
  }, [spatialLayoutActive, hasGisLayers]);

  const cascadeSet = useMemo(() => {
    const set = new Set<string>();
    if (cascadeChain) {
      set.add(cascadeChain.trigger);
      cascadeChain.impacted.forEach((d) => set.add(d));
    }
    return set;
  }, [cascadeChain]);

  const revisionCompletedSet = useMemo(
    () => new Set(revisionCompletedKeys),
    [revisionCompletedKeys],
  );

  const executingSet = useMemo(
    () => new Set(executingDimensions),
    [executingDimensions],
  );

  const embeddedContentClass = "mx-auto w-full max-w-[760px]";
  const reviewLayer = reviewLayerForPanel;
  const showEmbeddedReview = Boolean(
    isEmbedded
    && isPaused
    && reviewLayer
    && Object.keys(reports[`layer${reviewLayer}` as keyof typeof reports] || {}).length > 0,
  );

  const wasPausedForReviewRef = useRef(false);
  useEffect(() => {
    const pausedForReview = isPaused && (status as string) === "paused" && showEmbeddedReview;
    if (pausedForReview && !wasPausedForReviewRef.current) {
      setReviewFocusKey((key) => key + 1);
    }
    wasPausedForReviewRef.current = pausedForReview;
  }, [isPaused, status, showEmbeddedReview]);

  const renderEmbeddedSideRail = useCallback((options?: {
    showCompare?: boolean;
    onCompare?: () => void;
    ragDocuments?: Array<{ title: string; snippet?: string; score?: number }>;
    ragQuery?: string;
    onOpenRagDoc?: (index: number) => void;
    showGisTrigger?: boolean;
  }) => {
    if (!isEmbedded) return null;
    return (
      <AnalysisSidePanel
        reviewPanelRef={reviewPanelRef}
        reviewLayer={reviewLayer}
        showReview={showEmbeddedReview}
        highlightReviewBox={highlightReviewBox}
        feedback={feedback}
        onFeedbackChange={setFeedback}
        onFeedbackKeyDown={(event) => {
          if (event.key === 'Enter' && !event.shiftKey) {
            event.preventDefault();
            void handleRejectWithFeedback();
          }
        }}
        onApprove={approve}
        onSubmitRevision={() => void handleRejectWithFeedback()}
        isSubmitting={isSubmitting}
        primaryBtnClass={primaryBtnClass}
        secondaryBtnClass={secondaryBtnClass}
        allCompletedDimsCount={allCompletedDimsCount}
        allCompletedDimsByLayer={allCompletedDimsByLayer}
        selectedDimensions={selectedDimensions}
        onToggleDimension={(dimKey) => {
          setSelectedDimensions((current) => (
            current.includes(dimKey)
              ? current.filter((item) => item !== dimKey)
              : [...current, dimKey]
          ));
        }}
        showCompare={options?.showCompare}
        onCompare={options?.onCompare}
        ragDocuments={options?.ragDocuments}
        ragQuery={options?.ragQuery}
        onOpenRagDoc={options?.onOpenRagDoc}
        showGisTrigger={options?.showGisTrigger}
        gisBusy={gisTriggerPending || gisGenerating}
        onTriggerGis={() => void handleTriggerGIS()}
        completedDimsCount={completedDimsCount}
        totalDims={totalDims}
        chatPanel={chatPanel ?? (
          <div className="flex flex-1 items-center justify-center p-4 text-[12px] text-[#9ab2a8]">
            问答面板未连接
          </div>
        )}
        sessionConnected={sessionConnected}
        autoFocusReviewKey={reviewFocusKey}
      />
    );
  }, [
    isEmbedded,
    reviewLayer,
    showEmbeddedReview,
    reviewFocusKey,
    highlightReviewBox,
    feedback,
    approve,
    isSubmitting,
    primaryBtnClass,
    secondaryBtnClass,
    allCompletedDimsCount,
    allCompletedDimsByLayer,
    selectedDimensions,
    gisTriggerPending,
    gisGenerating,
    completedDimsCount,
    totalDims,
    handleRejectWithFeedback,
    handleTriggerGIS,
    chatPanel,
    sessionConnected,
  ]);

  if (selectedNavigationKey?.startsWith("dim:") && !showInputForm) {
    const dimKey = selectedNavigationKey.slice(4);
    const layer = parseInt(dimKey.split("_")[0], 10);
    const layerReports =
      reports[`layer${layer}` as "layer1" | "layer2" | "layer3"] || {};
    const dimKeyPart = dimKey.split("_").slice(1).join("_");

    const dimProgressKey = `${layer}_${dimKeyPart}`;
    const progress = dimensionProgress[dimProgressKey];
    const isCompleted = progress?.status === "completed";
    const reportContent = isCompleted
      ? layerReports[dimKeyPart] || streamingContent[dimProgressKey] || ""
      : streamingContent[dimProgressKey] || layerReports[dimKeyPart] || "";

    return (
      <div className={`flex-1 h-full flex ${surfaceClass}`}>
        {/* Main Report Area */}
        <div className="flex-1 min-w-0 h-full flex flex-col overflow-hidden">
          {/* Header */}
          <div className={`flex items-center justify-between shrink-0 ${isEmbedded ? 'border-b border-[#e5efe9] bg-white px-3 py-2' : `px-5 py-3 ${headerClass}`}`}>
            <div className="flex items-center gap-2 min-w-0">
              {compareMode ? (
                <>
                  <button
                    onClick={handleExitCompare}
                    className={`w-9 h-9 rounded-xl flex items-center justify-center transition-colors ${secondaryBtnClass}`}
                  >
                    <FontAwesomeIcon
                      icon={faArrowLeft}
                      className={isEmbedded ? "text-[#4d7568]" : "text-slate-600"}
                      style={{ width: 16, height: 16 }}
                    />
                  </button>
                  <div className="min-w-0">
                    <h2 className={`text-base font-semibold ${titleClass}`}>
                      报告对比
                    </h2>
                    <p className={`text-xs ${mutedClass}`}>{getDimensionName(dimKeyPart)}</p>
                  </div>
                </>
              ) : isEmbedded ? (
                <h2 className={`text-sm font-semibold truncate ${titleClass}`}>
                  {getDimensionName(dimKeyPart)}
                </h2>
              ) : (
                <>
                  <div className={`w-9 h-9 rounded-xl flex items-center justify-center shrink-0 ${iconWrapClass}`}>
                    <span className="text-base">{getDimensionIcon(dimKeyPart)}</span>
                  </div>
                  <div className="min-w-0">
                    <h2 className={`text-base font-semibold truncate ${titleClass}`}>
                      {getDimensionName(dimKeyPart)}
                    </h2>
                    <p className={`text-xs ${mutedClass}`}>
                      {LAYER_VALUE_MAP[layer] || `Layer ${layer}`}
                    </p>
                  </div>
                </>
              )}
            </div>
            <div className="flex items-center gap-2 shrink-0">
              {compareMode ? (
                <>
                  {/* Version Selector (for current session) */}
                  {availableVersions.length > 0 && (
                    <select
                      value={selectedVersion || ""}
                      onChange={(e) =>
                        handleVersionSelect(Number(e.target.value))
                      }
                      className="px-3 py-2 rounded-lg text-sm bg-white border border-slate-200 text-slate-700 focus:outline-none focus:ring-2 focus:ring-cyan-300"
                      disabled={isLoadingVersions}
                    >
                      <option value="">当前版本</option>
                      {availableVersions.map((v) => (
                        <option key={v.version} value={v.version}>
                          v{v.version} (
                          {new Date(v.generated_at).toLocaleDateString("zh-CN")}
                          )
                        </option>
                      ))}
                    </select>
                  )}
                  {/* Session Selector */}
                  <select
                    value={selectedSessionId || ""}
                    onChange={(e) => {
                      const val = e.target.value;
                      setSelectedVersion(null);
                      setCompareContent("");
                      setCompareKnowledgeSources([]);
                      if (val) {
                        setSelectedSessionId(val);
                        handleSessionSelect(val);
                      } else {
                        setSelectedSessionId(null);
                      }
                    }}
                    className="px-4 py-2 rounded-lg text-sm bg-white border border-slate-200 text-slate-700 focus:outline-none focus:ring-2 focus:ring-cyan-300"
                    disabled={isLoadingSessions}
                  >
                    <option value="">选择对比会话...</option>
                    <option value={sessionId || ""}>当前会话</option>
                    {availableSessions.map((s) => (
                      <option key={s.id} value={s.id}>
                        {s.name} {s.isCompleted ? "✓" : "○"}
                      </option>
                    ))}
                  </select>
                </>
              ) : (
                <>
                  {!isEmbedded && (
                  <button
                    onClick={handleCompareClick}
                    className={`rounded-lg text-sm transition-all flex items-center gap-2 ${secondaryBtnClass} px-3 py-2`}
                    title="对比报告"
                  >
                    <FontAwesomeIcon
                      icon={faExchangeAlt}
                      style={{ width: 14, height: 14 }}
                    />
                    <span>对比</span>
                  </button>
                  )}
                  {!isEmbedded && (
                    <button
                      onClick={onViewProcess}
                      className={`px-3 py-2 rounded-lg text-sm transition-all ${secondaryBtnClass}`}
                    >
                      查看过程
                    </button>
                  )}
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
                  <span className="text-sm font-medium text-cyan-700">
                    当前报告
                  </span>
                </div>
                <div className="flex-1 overflow-y-auto p-4">
                  <div className="bg-white rounded-xl shadow-sm border border-slate-200/60 p-4">
                    <ReportContent content={reportContent} />
                  </div>
                  {/* Current Knowledge Sources */}
                  {effectiveRagSources && effectiveRagSources.documents.length > 0 && (
                    <div className="mt-4 bg-white rounded-xl shadow-sm border border-slate-200/60 p-4">
                      <div className="flex items-center gap-2 mb-3">
                        <FontAwesomeIcon
                          icon={faLink}
                          className="text-emerald-600"
                          style={{ width: 12, height: 12 }}
                        />
                        <span className="text-sm font-medium text-slate-700">
                          知识来源 ({effectiveRagSources.documents.length})
                        </span>
                      </div>
                      <div className="space-y-2">
                        {effectiveRagSources.documents.slice(0, 5).map((doc, idx) => (
                          <div
                            key={idx}
                            className="text-xs text-slate-600 truncate"
                          >
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
                className={`w-1/2 flex flex-col overflow-hidden transition-all ${isDragOver ? "bg-cyan-50 ring-2 ring-cyan-400" : ""}`}
                onDragOver={handleDragOver}
                onDragLeave={handleDragLeave}
                onDrop={handleDrop}
              >
                <div className="px-4 py-3 bg-amber-50 border-b border-slate-200 shrink-0">
                  <span className="text-sm font-medium text-amber-700">
                    {selectedSessionId ? "对比报告" : "选择会话查看对比"}
                  </span>
                </div>
                <div className="flex-1 overflow-y-auto p-4">
                  {isLoadingCompare ? (
                    <div className="flex items-center justify-center h-full">
                      <FontAwesomeIcon
                        icon={faSpinner}
                        className="text-slate-400 animate-spin"
                        style={{ width: 24, height: 24 }}
                      />
                    </div>
                  ) : selectedSessionId ? (
                    <>
                      <div className="bg-white rounded-xl shadow-sm border border-slate-200/60 p-4">
                        <ReportContent content={compareContent} />
                      </div>
                      {/* Compare Knowledge Sources */}
                      {compareKnowledgeSources.length > 0 && (
                        <div className="mt-4 bg-white rounded-xl shadow-sm border border-slate-200/60 p-4">
                          <div className="flex items-center gap-2 mb-3">
                            <FontAwesomeIcon
                              icon={faLink}
                              className="text-emerald-600"
                              style={{ width: 12, height: 12 }}
                            />
                            <span className="text-sm font-medium text-slate-700">
                              知识来源 ({compareKnowledgeSources.length})
                            </span>
                          </div>
                          <div className="space-y-2">
                            {compareKnowledgeSources
                              .slice(0, 5)
                              .map((doc, idx) => (
                                <div
                                  key={idx}
                                  className="text-xs text-slate-600 truncate"
                                >
                                  📄 {doc.title}
                                </div>
                              ))}
                          </div>
                        </div>
                      )}
                    </>
                  ) : (
                    <div className="flex items-center justify-center h-full">
                      <p className="text-sm text-slate-400">
                        请选择一个会话进行对比
                      </p>
                    </div>
                  )}
                </div>
              </div>
            </div>
          ) : (
            /* Single Report View */
            <div
              className={`flex-1 overflow-y-auto transition-all ${isDragOver ? "bg-cyan-50 ring-2 ring-cyan-400 ring-inset" : ""}`}
              onDragOver={handleDragOver}
              onDragLeave={handleDragLeave}
              onDrop={handleDrop}
            >
              <div className={`${isEmbedded && !embeddedNotStarted ? embeddedContentClass : isEmbedded ? 'w-full max-w-none' : ''} space-y-3 ${isEmbedded ? 'p-3' : 'p-6 lg:p-8'}`}>
                {progress?.status === 'failed' && progress.error && (
                  <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
                    <span className="font-semibold">本维度生成失败：</span>
                    {progress.error}
                  </div>
                )}
                {reportContent?.includes('LLM 不可用') && (
                  <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
                    当前报告由离线模板生成，非真实 LLM 分析。修复模型配置后请新建会话重新分析。
                  </div>
                )}
                {reportContent ? (
                  <div className={`bg-white border border-slate-200/60 ${isEmbedded ? "rounded-xl p-4" : "rounded-2xl shadow-sm p-6 lg:p-8"}`}>
                    <ReportContent content={reportContent} />
                  </div>
                ) : planningBootstrap.isBootstrapping ? (
                  <div className="-mx-3 -my-3">
                    <PlanningBootstrapPanel
                      compact
                      headline={planningBootstrap.headline}
                      steps={planningBootstrap.steps}
                    />
                  </div>
                ) : embeddedNotStarted ? (
                  <div className="-mx-3 -my-3">
                    <AnalysisNotStartedPlaceholder onGoToTaskSettings={onGoToTaskSettings} />
                  </div>
                ) : (
                  <div className="flex items-center justify-center h-64">
                    <div className="text-center">
                      <div className="w-16 h-16 rounded-full bg-slate-100 flex items-center justify-center mb-4 mx-auto">
                        <FontAwesomeIcon
                          icon={faLayerGroup}
                          className="text-slate-300"
                          style={{ width: 24, height: 24 }}
                        />
                      </div>
                      <p className="text-slate-400 text-sm">
                        {progress?.status === "streaming" || executingSet.has(dimProgressKey)
                          ? `正在分析「${getDimensionName(dimKeyPart)}」...`
                          : activeAnalysisFocus?.dimKey === dimKeyPart
                            ? `即将分析「${getDimensionName(dimKeyPart)}」`
                            : "该维度尚未生成报告。"}
                      </p>
                    </div>
                  </div>
                )}

                <GroundingEvidencePanel
                  dimensionKey={dimKeyPart}
                  facts={l1Facts}
                  rag={effectiveRagSources}
                />

                {/* RAG Knowledge Sources Panel */}
                {!isEmbedded && effectiveRagSources && effectiveRagSources.documents.length > 0 && (
                  <div className="bg-white rounded-2xl shadow-sm border border-slate-200/60 overflow-hidden">
                    <button
                      onClick={() => setRagExpanded((prev) => !prev)}
                      className="flex items-center gap-3 w-full px-5 py-4 text-left hover:bg-slate-50 transition-colors"
                    >
                      <div className="w-8 h-8 rounded-lg bg-emerald-100 flex items-center justify-center">
                        <FontAwesomeIcon
                          icon={faLink}
                          className="text-emerald-600"
                          style={{ width: 14, height: 14 }}
                        />
                      </div>
                      <div className="flex-1">
                        <span className="text-sm font-medium text-slate-700">
                          知识来源
                        </span>
                        <span className="text-xs text-slate-400 ml-2">
                          ({effectiveRagSources.documents.length}条)
                        </span>
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
                          animate={{ opacity: 1, height: "auto" }}
                          exit={{ opacity: 0, height: 0 }}
                          transition={{ duration: 0.2 }}
                          className="overflow-hidden"
                        >
                          <div className="px-5 pb-4 pt-2 border-t border-slate-100">
                            <div className="mb-3">
                              <span className="text-xs text-slate-500">
                                检索词：
                              </span>
                              <span className="text-xs text-emerald-600 font-mono ml-1">
                                {effectiveRagSources.query}
                              </span>
                            </div>
                            <div className="space-y-2">
                              {effectiveRagSources.documents.map((doc, idx) => (
                                <button
                                  key={idx}
                                  onClick={() =>
                                    setSelectedDocIndex(
                                      selectedDocIndex === idx ? null : idx,
                                    )
                                  }
                                  className="w-full text-left px-4 py-3 rounded-xl bg-slate-50 border border-slate-200 hover:border-emerald-300 hover:bg-emerald-50/30 transition-all"
                                >
                                  <div className="flex items-start justify-between gap-2">
                                    <div className="flex-1 min-w-0">
                                      <div className="flex items-center gap-2">
                                        <div className="text-sm font-medium text-slate-700 truncate">
                                          {doc.title}
                                        </div>
                                        {doc.score !== undefined &&
                                          doc.score > 0 && (
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
                                        <p className="text-xs text-slate-500 mt-1 line-clamp-2">
                                          {doc.snippet}
                                        </p>
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
            {selectedDocIndex !== null && effectiveRagSources && (
              <motion.div
                initial={{ width: 0, opacity: 0 }}
                animate={{ width: 400, opacity: 1 }}
                exit={{ width: 0, opacity: 0 }}
                transition={{ duration: 0.25 }}
                className="h-full bg-white border-l border-slate-200 shrink-0 overflow-hidden"
              >
                <div className="h-full flex flex-col">
                  <div className="flex items-center justify-between px-5 py-4 border-b border-slate-100 shrink-0">
                    <span className="text-sm font-medium text-slate-700">
                      知识详情
                    </span>
                    <button
                      onClick={() => setSelectedDocIndex(null)}
                      className="p-1.5 rounded-lg hover:bg-slate-100 text-slate-400 transition-colors"
                    >
                      <FontAwesomeIcon
                        icon={faTimes}
                        style={{ width: 14, height: 14 }}
                      />
                    </button>
                  </div>
                  <div className="flex-1 overflow-y-auto p-5">
                    <div className="text-base font-medium text-slate-800 mb-3">
                      {effectiveRagSources.documents[selectedDocIndex]?.title}
                    </div>
                    {effectiveRagSources.documents[selectedDocIndex]?.snippet && (
                      <div className="text-sm text-slate-600 leading-relaxed prose prose-sm max-w-none">
                        <MarkdownRenderer
                          content={
                            effectiveRagSources.documents[selectedDocIndex].snippet || ""
                          }
                        />
                      </div>
                    )}
                    {effectiveRagSources.documents[selectedDocIndex]?.source && (
                      <div className="mt-4 text-xs text-slate-400">
                        来源：{effectiveRagSources.documents[selectedDocIndex].source}
                      </div>
                    )}
                  </div>
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        )}

        {renderEmbeddedSideRail({
          showCompare: !compareMode,
          onCompare: handleCompareClick,
          ragDocuments: effectiveRagSources?.documents,
          ragQuery: effectiveRagSources?.query,
          onOpenRagDoc: (index) => setSelectedDocIndex(index),
        })}
      </div>
    );
  }

  return (
    <div className={`flex-1 h-full flex flex-col ${surfaceClass}`}>
      {/* Header */}
      {!isEmbedded && (
      <div className={`flex items-center justify-between px-6 lg:px-8 py-4 shrink-0 ${headerClass}`}>
        <div className="flex items-center gap-4">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-cyan-100 to-teal-100 flex items-center justify-center">
            <FontAwesomeIcon
              icon={faLayerGroup}
              className="text-cyan-600"
              style={{ width: 16, height: 16 }}
            />
          </div>
          <div>
            <h2 className="text-lg font-semibold text-slate-800">规划总览</h2>
            <p className="text-xs text-slate-400">
              当前阶段: {currentLayer ? `Layer ${currentLayer}` : "初始化中"} |
              已完成: {completedDimsCount}/{totalDims}
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
      )}

      {/* Content */}
      <div className={`flex h-full min-h-0 flex-1 ${isEmbedded ? "" : "flex-col"}`}>
        <div className={`flex-1 min-w-0 overflow-y-auto ${isEmbedded ? "px-3 py-2" : "p-6 lg:p-8"}`}>
        <div className={`mx-auto space-y-3 ${isEmbedded && !embeddedNotStarted ? embeddedContentClass : isEmbedded ? 'w-full max-w-none' : 'max-w-4xl'}`}>
          {embeddedNotStarted && (
            <div className="-mx-3 -my-2">
              <AnalysisNotStartedPlaceholder onGoToTaskSettings={onGoToTaskSettings} />
            </div>
          )}

          {planningBootstrap.isBootstrapping && (
            <PlanningBootstrapPanel
              compact
              headline={planningBootstrap.headline}
              steps={planningBootstrap.steps}
            />
          )}

          {isEmbedded && !embeddedNotStarted && !planningBootstrap.isBootstrapping && (
            <div className="space-y-3">
              {activeAnalysisFocus && (
                <AnalysisProgressBanner
                  focus={activeAnalysisFocus}
                  completedCount={completedDimsCount}
                  totalCount={totalDims}
                />
              )}
              <div className="overflow-hidden rounded-2xl border border-[#dcebe4] bg-gradient-to-br from-[#f3faf7] via-white to-[#eef8f3] p-4 shadow-sm">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <div className="text-[11px] font-semibold uppercase tracking-wider text-[#3a8f6f]">规划总览</div>
                    <h3 className="mt-1 text-[18px] font-bold text-[#244c40]">
                      {projectName || '村庄规划分析'}
                    </h3>
                    <p className="mt-1 text-[12px] text-[#78968b]">
                      已完成 {completedDimsCount}/{totalDims} 个专题
                      {(status as string) === 'paused' && ' · 当前暂停审查中'}
                      {(status as string) === 'planning' && ' · 生成进行中'}
                    </p>
                  </div>
                  <div className="flex h-16 w-16 flex-col items-center justify-center rounded-2xl border border-[#c9e8db] bg-white shadow-sm">
                    <span className="text-[20px] font-bold tabular-nums text-[#1f7a59]">
                      {totalDims > 0 ? Math.round((completedDimsCount / totalDims) * 100) : 0}%
                    </span>
                    <span className="text-[10px] text-[#9ab2a8]">总进度</span>
                  </div>
                </div>
                <div className="mt-4 flex flex-wrap items-center gap-2">
                  {([
                    { key: 'L1', label: '现状分析', done: completedLayers[1] },
                    { key: 'L2', label: '规划思路', done: completedLayers[2] },
                    { key: 'L3', label: '详细规划', done: completedLayers[3] },
                    { key: 'GIS', label: '空间布局', done: hasGisLayers },
                  ] as const).map((step, index) => (
                    <React.Fragment key={step.key}>
                      {index > 0 && (
                        <div className={`h-0.5 w-5 ${step.done ? 'bg-[#3fb288]' : 'bg-[#dcebe4]'}`} />
                      )}
                      <div className={`flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] ${
                        step.done
                          ? 'border-[#c9e8db] bg-[#e8f5ef] text-[#1f7a59]'
                          : 'border-[#dcebe4] bg-white text-[#78968b]'
                      }`}
                      >
                        <span className={`flex h-5 w-5 items-center justify-center rounded-full text-[10px] font-semibold ${
                          step.done ? 'bg-[#3fb288] text-white' : 'bg-[#eef4f0] text-[#9ab2a8]'
                        }`}
                        >
                          {step.done ? '✓' : step.key.replace('L', '')}
                        </span>
                        {step.label}
                      </div>
                    </React.Fragment>
                  ))}
                </div>
              </div>

              <div className="grid gap-2 sm:grid-cols-3">
                {([1, 2, 3] as const).map((layer) => {
                  const layerReports = reports[`layer${layer}` as 'layer1' | 'layer2' | 'layer3'] ?? {};
                  const done = Object.keys(layerReports).length;
                  const total = DIMENSIONS_BY_LAYER[layer]?.length || 0;
                  const complete = completedLayers[layer];
                  const percent = total > 0 ? Math.round((done / total) * 100) : 0;
                  return (
                    <div
                      key={layer}
                      className={`rounded-xl border px-3 py-3 ${
                        complete
                          ? 'border-[#c9e8db] bg-[#f3fbf7]'
                          : 'border-[#dcebe4] bg-white'
                      }`}
                    >
                      <div className="flex items-center justify-between">
                        <div className="text-[11px] font-semibold text-[#9ab2a8]">L{layer}</div>
                        <div className="text-[12px] font-semibold tabular-nums text-[#3a8f6f]">{done}/{total}</div>
                      </div>
                      <div className="mt-1 text-[13px] font-semibold text-[#244c40]">
                        {LAYER_VALUE_MAP[layer]}
                      </div>
                      <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-[#e7f2ed]">
                        <div className="h-full rounded-full bg-[#3fb288] transition-all" style={{ width: `${percent}%` }} />
                      </div>
                      <div className="mt-1 text-[11px] text-[#78968b]">
                        {complete ? '本层已完成' : `完成 ${percent}%`}
                      </div>
                    </div>
                  );
                })}
              </div>

              <div className="rounded-2xl border border-[#dcebe4] bg-white p-3 shadow-sm">
                <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                  <div>
                    <div className="text-[12px] font-semibold text-[#244c40]">专题导航目录</div>
                    <div className="mt-0.5 text-[10px] text-[#9ab2a8]">目录定位报告；依赖图查看执行关系</div>
                  </div>
                  <div className="flex items-center gap-1 rounded-lg bg-[#f3f8f5] p-0.5">
                    {([['list', '目录'], ['graph', '依赖图']] as const).map(([view, label]) => (
                      <button
                        key={view}
                        type="button"
                        onClick={() => setDirectoryView(view)}
                        className={`rounded-md px-2 py-1 text-[10px] transition ${directoryView === view ? 'bg-white font-semibold text-[#2d7e61] shadow-sm' : 'text-[#78968b] hover:text-[#2d7e61]'}`}
                      >
                        {label}
                      </button>
                    ))}
                  </div>
                </div>
                {directoryView === 'list' ? (
                <div className="space-y-2">
                  {LAYER_IDS.map((layer) => {
                    const allDims = DIMENSIONS_BY_LAYER[layer] || [];
                    const layerReports = reports[`layer${layer}` as keyof typeof reports] || {};
                    const layerDone = Object.keys(layerReports).length;
                    return (
                      <div key={layer} className="rounded-xl border border-[#eef4f0] bg-[#fafcfb] p-2">
                        <div className="mb-1 flex items-center justify-between px-1">
                          <span className="text-[12px] font-semibold text-[#2d8c6d]">
                            L{layer} · {LAYER_VALUE_MAP[layer]}
                          </span>
                          <span className="text-[11px] text-[#9ab2a8]">{layerDone}/{allDims.length}</span>
                        </div>
                        <div className="grid gap-1 sm:grid-cols-2">
                          {allDims.map((dimKey) => {
                            const progressKey = `${layer}_${dimKey}`;
                            const isCompleted = !!layerReports[dimKey]
                              || dimensionProgress[progressKey]?.status === 'completed';
                            const isRunning = executingSet.has(progressKey)
                              || (!!streamingContent[progressKey] && !isCompleted);
                            return (
                              <button
                                key={dimKey}
                                type="button"
                                onClick={() => usePlanningStore.getState().setSelectedNavigationKey(
                                  NAV_KEYS.dim(`${layer}_${dimKey}`),
                                )}
                                className="flex items-center gap-2 rounded-lg border border-transparent bg-white px-2.5 py-2 text-left text-[12px] text-[#5d7f72] transition-colors hover:border-[#c9e8db] hover:bg-[#f3fbf7]"
                              >
                                <span className={`h-2 w-2 shrink-0 rounded-full ${
                                  isCompleted
                                    ? 'bg-[#3fb288]'
                                    : isRunning
                                      ? 'bg-[#e6a23c] animate-pulse'
                                      : 'bg-[#d5e5dd]'
                                }`}
                                />
                                <span className="min-w-0 flex-1 truncate">{getDimensionName(dimKey)}</span>
                              </button>
                            );
                          })}
                        </div>
                      </div>
                    );
                  })}
                </div>
                ) : (
                  <TopicDependencyGraph
                    graph={dependencyGraph}
                    graphStatus={dependencyGraphStatus === 'error' ? 'error' : 'loading'}
                    reports={reports}
                    dimensionProgress={dimensionProgress}
                    executingDimensions={executingSet}
                    selectedNavigationKey={selectedNavigationKey || ''}
                    onSelectDimension={(navigationKey) => usePlanningStore.getState().setSelectedNavigationKey(navigationKey as NonNullable<typeof selectedNavigationKey>)}
                  />
                )}
              </div>

              {cascadeChain && (
                <div className="rounded-xl border border-amber-200 bg-amber-50/80 px-3 py-2.5 text-[12px] text-amber-800">
                  <span className="font-semibold">级联修复进行中</span>
                  <span className="ml-2 text-amber-700">触发维度：{getDimensionName(cascadeChain.trigger)}</span>
                </div>
              )}
            </div>
          )}

          {/* Pipeline progress: L1 -> L2 -> L3 -> GIS (default layout only) */}
          {!showInputForm && !isEmbedded && (
            <div className={`flex flex-wrap items-center gap-1.5 rounded-lg border px-3 py-2 ${
              isEmbedded
                ? "border-[#dcebe4] bg-white"
                : "border-slate-100 bg-slate-50"
            }`}>
              {([
                { key: 'L1', label: '现状分析', done: completedLayers[1] },
                { key: 'L2', label: '规划思路', done: completedLayers[2] },
                { key: 'L3', label: '详细规划', done: completedLayers[3] },
                { key: 'GIS', label: '空间布局', done: hasGisLayers },
              ] as const).map((step, i) => (
                <React.Fragment key={step.key}>
                  {i > 0 && (
                    <div className={'w-6 h-0.5 ' + (step.done ? 'bg-emerald-400' : 'bg-slate-200')} />
                  )}
                  <div className="flex items-center gap-1.5">
                    <div
                      className={'w-5 h-5 rounded-full text-[10px] font-medium flex items-center justify-center ' + (
                        step.done
                          ? 'bg-emerald-500 text-white'
                          : 'bg-slate-200 text-slate-500'
                      )}
                    >
                      {step.done ? '✓' : step.key}
                    </div>
                    <span className="text-xs text-slate-600">{step.label}</span>
                  </div>
                </React.Fragment>
              ))}
            </div>
          )}

          {/* L3 gate blocked: program validation failed before spatial chain */}
          {!showInputForm && l3GateBlocked && !isEmbedded && (
            <div className="flex flex-col gap-3 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3">
              <div className="flex items-start gap-3">
                <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-amber-100 text-amber-700">
                  <FontAwesomeIcon icon={faPauseCircle} style={{ width: 14, height: 14 }} />
                </div>
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium text-amber-900">
                    L3 程序校验未通过，需确认后才能进入空间布局
                  </p>
                  <p className="mt-1 text-xs text-amber-800">
                    系统检测到规划程序存在矛盾或需修订的维度。确认后将自动重试相关维度并继续空间链。
                  </p>
                  {humanReview?.items?.length ? (
                    <ul className="mt-2 space-y-1 text-xs text-amber-900">
                      {humanReview.items.slice(0, 4).map((item) => {
                        const ctx = (item.context || {}) as Record<string, unknown>;
                        const message = String(ctx.message || ctx.detail || item.request_type || "待处理项");
                        return (
                          <li key={String(item.request_id || message)} className="truncate">
                            · {message}
                          </li>
                        );
                      })}
                      {humanReview.items.length > 4 ? (
                        <li className="text-amber-700">… 另有 {humanReview.items.length - 4} 项</li>
                      ) : null}
                    </ul>
                  ) : null}
                </div>
                <button
                  type="button"
                  onClick={() => void approve()}
                  disabled={isSubmitting}
                  className={`flex shrink-0 items-center gap-2 rounded-xl px-4 py-2 text-sm font-medium text-white transition-colors disabled:opacity-50 ${primaryBtnClass}`}
                >
                  {isSubmitting ? (
                    <>
                      <div className="h-4 w-4 animate-spin rounded-full border-2 border-white border-t-transparent" />
                      <span>处理中...</span>
                    </>
                  ) : (
                    <span>确认并继续</span>
                  )}
                </button>
              </div>
            </div>
          )}

          {/* Spatial chain running after L3 gate PASS */}
          {!showInputForm && spatialLayoutActive && !hasGisLayers && !l3GateBlocked && !isEmbedded && (
            <div className="flex items-center gap-3 rounded-xl border border-cyan-200 bg-gradient-to-r from-cyan-50 to-teal-50 px-4 py-3">
              <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-cyan-100 text-cyan-600">
                <FontAwesomeIcon icon={faMap} style={{ width: 14, height: 14 }} />
              </div>
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium text-cyan-800">正在生成空间布局</p>
                <p className="text-xs text-cyan-600">
                  L3 已通过校验，工作流已进入
                  {isSpatialWorkflowPhase(phase) ? ` ${phase}` : " 空间链"}
                  ，请稍候…
                </p>
              </div>
              <div className="h-4 w-4 shrink-0 animate-spin rounded-full border-2 border-cyan-500 border-t-transparent" />
            </div>
          )}

          {/* GIS generating indicator */}
          {!showInputForm && gisGenerating && !isEmbedded && (
            <div className="flex items-center gap-2 px-4 py-2 bg-cyan-50 rounded-lg border border-cyan-100">
              <div className="w-4 h-4 border-2 border-cyan-500 border-t-transparent rounded-full animate-spin" />
              <span className="text-sm text-cyan-700">正在生成空间布局...</span>
            </div>
          )}

          {/* Input Form Card (idle state) */}
          {showInputForm && <VillageInputForm onSubmit={handleSubmit} />}

          {/* Layer dimension grids (non-idle state) */}
          {!showInputForm && !hideOverviewDimensionGrid &&
            LAYER_IDS.map((layer) => {
              const allDims = DIMENSIONS_BY_LAYER[layer] || [];
              const layerReports =
                reports[`layer${layer}` as keyof typeof reports] || {};
              const completedCount = allDims.filter(
                (d) => layerReports[d],
              ).length;
              const isLayerComplete =
                completedCount === allDims.length && allDims.length > 0;

              return (
                <motion.div
                  key={layer}
                  initial={{ opacity: 0, y: 20 }}
                  animate={{ opacity: 1, y: 0 }}
                  className="bg-white rounded-2xl shadow-sm border border-slate-200/60 overflow-hidden"
                >
                  {/* Layer header */}
                  <div className="flex items-center justify-between px-5 py-3 border-b border-slate-100">
                    <div className="flex items-center gap-3">
                      <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-amber-100 to-orange-100 flex items-center justify-center">
                        <span className="text-sm font-semibold text-amber-600">
                          {layer}
                        </span>
                      </div>
                      <h3 className="text-sm font-medium text-slate-800">
                        {LAYER_VALUE_MAP[layer]}
                      </h3>
                    </div>
                    <div className="flex items-center gap-2">
                      <span
                        className={cn(
                          "text-xs font-medium",
                          isLayerComplete
                            ? "text-emerald-600"
                            : "text-slate-500",
                        )}
                      >
                        {completedCount}/{allDims.length}
                      </span>
                      {isLayerComplete && (
                        <span className="text-emerald-500 text-xs">✓</span>
                      )}
                    </div>
                  </div>

                  {/* Dimension rows */}
                  <div className="divide-y divide-slate-50">
                    {allDims.map((dimKey) => {
                      const progressKey = `${layer}_${dimKey}`;
                      const progress = dimensionProgress[progressKey];
                      const isExecuting = executingSet.has(progressKey);
                      const isStreaming =
                        !!streamingContent[progressKey] &&
                        progress?.status !== "completed";
                      const isCompleted =
                        progress?.status === "completed" ||
                        !!layerReports[dimKey];
                      const isInCascade = cascadeSet.has(dimKey);
                      const isRevisionCompleted =
                        revisionCompletedSet.has(progressKey);

                      const status = getDimensionDisplayStatus({
                        isInCascade,
                        isRevisionCompleted,
                        isExecuting,
                        isStreaming,
                        isCompleted,
                      });

                      const icon = getDimensionIcon(dimKey);
                      const name = getDimensionName(dimKey);

                      return (
                        <button
                          key={dimKey}
                          onClick={() =>
                            usePlanningStore
                              .getState()
                              .setSelectedNavigationKey(
                                NAV_KEYS.dim(`${layer}_${dimKey}`),
                              )
                          }
                          className="w-full flex items-center gap-3 px-5 py-2.5 hover:bg-slate-50/80 transition-colors text-left group"
                        >
                          <span className="text-base shrink-0">{icon}</span>
                          <span className="flex-1 text-sm text-slate-700 group-hover:text-slate-900 truncate">
                            {name}
                          </span>
                          <div className="flex items-center gap-2 shrink-0">
                            <span
                              className={cn(
                                "w-1.5 h-1.5 rounded-full",
                                status.dotColor,
                                status.pulse && "animate-pulse",
                              )}
                            />
                            <span className={cn("text-xs", status.color)}>
                              {status.label}
                            </span>
                          </div>
                        </button>
                      );
                    })}
                  </div>
                </motion.div>
              );
            })}

          {/* Cascade revision card */}
          {cascadeChain && (
            <motion.div
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              className={isEmbedded
                ? "rounded-lg border border-amber-200 bg-amber-50/80 overflow-hidden"
                : "bg-gradient-to-r from-amber-50 to-orange-50 border border-amber-200 rounded-2xl overflow-hidden"
              }
            >
              <div className={isEmbedded ? "px-3 py-2 border-b border-amber-200/60" : "px-5 py-3 border-b border-amber-200/60"}>
                <div className="flex items-center gap-2">
                  <span className="w-2 h-2 rounded-full bg-amber-400 animate-pulse" />
                  <span className={`font-medium text-amber-800 ${isEmbedded ? 'text-xs' : 'text-sm'}`}>
                    级联修复进行中
                  </span>
                </div>
              </div>
              <CascadePanel
                trigger={cascadeChain.trigger}
                impacted={cascadeChain.impacted}
                revisionCompletedKeys={revisionCompletedKeys}
              />
            </motion.div>
          )}


          {/* Review panel - only shown when paused for approval (default layout) */}
          {!isEmbedded && reviewLayerForPanel &&
            (() => {
              const reviewLayer = reviewLayerForPanel;
              const hasReports =
                Object.keys(
                  reports[`layer${reviewLayer}` as keyof typeof reports] || {},
                ).length > 0;
              if (!hasReports) return null;
              return (
                <motion.div
                  ref={reviewPanelRef}
                  initial={{ opacity: 0, y: 20 }}
                  animate={{ opacity: 1, y: 0 }}
                  className={cn(
                    "rounded-2xl border p-5 transition-shadow",
                    isEmbedded
                      ? "border-[#dcebe4] bg-white"
                      : "bg-gradient-to-r from-amber-50 to-orange-50",
                    highlightReviewBox
                      ? isEmbedded
                        ? "border-[#3fb288] ring-2 ring-[#b8e5d2] shadow-md"
                        : "border-amber-400 ring-2 ring-amber-300 shadow-md"
                      : isEmbedded
                        ? ""
                        : "border-amber-200",
                  )}
                >
                  <div className="mb-4 flex items-center gap-3">
                    <div className={`flex h-10 w-10 items-center justify-center rounded-xl ${
                      isEmbedded ? "bg-[#fff4df] text-[#b7791f]" : "bg-amber-100 text-amber-600"
                    }`}>
                      <FontAwesomeIcon
                        icon={faPauseCircle}
                        style={{ width: 20, height: 20 }}
                      />
                    </div>
                    <div>
                      <h3 className={`text-base font-semibold ${isEmbedded ? "text-[#244c40]" : "text-amber-800"}`}>
                        Layer {reviewLayer} 审查
                      </h3>
                      <p className={`text-sm ${isEmbedded ? "text-[#78968b]" : "text-amber-600"}`}>
                        规划已暂停，请审批后继续
                      </p>
                    </div>
                  </div>

                  <div className="flex flex-wrap items-start gap-3">
                    <div className="flex flex-col gap-1">
                      <button
                        onClick={approve}
                        disabled={isSubmitting}
                        className={`flex items-center gap-2 rounded-xl px-5 py-2.5 text-sm font-medium text-white transition-colors disabled:opacity-50 ${primaryBtnClass}`}
                      >
                        <FontAwesomeIcon
                          icon={faCheck}
                          style={{ width: 14, height: 14 }}
                        />
                        <span>批准并进入下一阶段</span>
                      </button>

                    </div>

                    <div className="flex-1 min-w-[280px] flex items-start gap-2">
                      <textarea
                        value={feedback}
                        onChange={(e) => {
                          setFeedback(e.target.value);
                          e.target.style.height = "auto";
                          e.target.style.height =
                            e.target.scrollHeight + "px";
                        }}
                        onKeyDown={(e) => {
                          if (e.key === "Enter" && !e.shiftKey) {
                            e.preventDefault();
                            handleRejectWithFeedback();
                          }
                        }}
                        placeholder="输入修订意见...（Enter 提交，Shift+Enter 换行）"
                        rows={1}
                        className={cn(
                          "flex-1 px-4 py-2.5 rounded-xl border bg-white text-sm text-slate-700 placeholder-slate-400 focus:outline-none resize-none overflow-hidden min-h-[40px] transition-shadow",
                          highlightReviewBox
                            ? "border-amber-400 ring-2 ring-amber-300"
                            : "border-amber-200 focus:ring-2 focus:ring-amber-300",
                        )}
                        style={{ height: feedback ? "auto" : "40px" }}
                      />
                      <button
                        onClick={handleRejectWithFeedback}
                        disabled={isSubmitting}
                        className="px-4 py-2.5 rounded-xl bg-amber-100 text-amber-700 text-sm font-medium hover:bg-amber-200 transition-colors disabled:opacity-50 whitespace-nowrap"
                      >
                        提交修订
                      </button>
                    </div>
                  </div>

                  {/* Dimension Selector for Cascade Revision */}
                  {allCompletedDimsCount > 0 && (
                    <div className="mt-3">
                      <button
                        onClick={() =>
                          setShowDimensionSelector(!showDimensionSelector)
                        }
                        className="text-xs text-amber-600 hover:text-amber-700 flex items-center gap-1 transition-colors"
                      >
                        <FontAwesomeIcon
                          icon={faChevronDown}
                          className={cn(
                            "transition-transform",
                            showDimensionSelector && "rotate-180",
                          )}
                          style={{ width: 10, height: 10 }}
                        />
                        <span>
                          {selectedDimensions.length > 0
                            ? `已选择 ${selectedDimensions.length} 个维度进行修订`
                            : `选择修订维度 (${allCompletedDimsCount} 个可修订)`}
                        </span>
                      </button>

                      <AnimatePresence initial={false}>
                        {showDimensionSelector && (
                          <motion.div
                            initial={{ opacity: 0, height: 0 }}
                            animate={{ opacity: 1, height: "auto" }}
                            exit={{ opacity: 0, height: 0 }}
                            transition={{ duration: 0.2 }}
                            className="overflow-hidden"
                          >
                            <div className="mt-3 p-4 bg-white rounded-xl border border-amber-200">
                              <div className="flex items-center justify-between mb-3">
                                <span className="text-xs text-amber-600">
                                  选择需要重新分析的已完维度（将自动级联修改下游依赖）
                                </span>
                                <button
                                  onClick={() => {
                                    const allDims =
                                      allCompletedDimsByLayer.flatMap(
                                        (g) => g.dims,
                                      );
                                    if (
                                      selectedDimensions.length ===
                                      allDims.length
                                    ) {
                                      setSelectedDimensions([]);
                                    } else {
                                      setSelectedDimensions(allDims);
                                    }
                                  }}
                                  className="text-xs text-amber-500 hover:text-amber-600 underline"
                                >
                                  {selectedDimensions.length > 0
                                    ? "取消全选"
                                    : "全选"}
                                </button>
                              </div>
                              <div className="space-y-2">
                                {allCompletedDimsByLayer.map(
                                  (layerGroup) => (
                                    <div key={layerGroup.layer}>
                                      <div className="text-xs font-medium text-slate-500 mb-1">
                                        Layer {layerGroup.layer} — 可修订维度
                                      </div>
                                      <div className="flex flex-wrap gap-1.5">
                                        {layerGroup.dims.map((dimKey) => (
                                          <label
                                            key={dimKey}
                                            className={cn(
                                              "flex items-center gap-2 px-3 py-2 rounded-lg cursor-pointer transition-all",
                                              selectedDimensions.includes(
                                                dimKey,
                                              )
                                                ? "bg-amber-100 border border-amber-300"
                                                : "bg-slate-50 border border-slate-200 hover:border-amber-200",
                                            )}
                                          >
                                            <input
                                              type="checkbox"
                                              checked={selectedDimensions.includes(
                                                dimKey,
                                              )}
                                              onChange={(e) => {
                                                if (e.target.checked) {
                                                  setSelectedDimensions([
                                                    ...selectedDimensions,
                                                    dimKey,
                                                  ]);
                                                } else {
                                                  setSelectedDimensions(
                                                    selectedDimensions.filter(
                                                      (d) => d !== dimKey,
                                                    ),
                                                  );
                                                }
                                              }}
                                              className="w-4 h-4 rounded border-amber-300 text-amber-500 focus:ring-amber-300"
                                            />
                                            <span className="text-sm text-slate-700 truncate">
                                              {getDimensionName(dimKey)}
                                            </span>
                                          </label>
                                        ))}
                                      </div>
                                    </div>
                                  ),
                                )}
                              </div>
                            </div>
                          </motion.div>
                        )}
                      </AnimatePresence>
                    </div>
                  )}
                </motion.div>
              );
            })()}
        </div>
        </div>
        {isEmbedded && renderEmbeddedSideRail({
          showGisTrigger: !showInputForm && spatialLayoutActive && !hasGisLayers && !l3GateBlocked,
        })}
      </div>
    </div>
  );
});

export default ReportViewer;
