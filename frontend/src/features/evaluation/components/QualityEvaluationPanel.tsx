'use client';

import { useCallback, useMemo, useState } from 'react';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import {
  faCheck,
  faChevronDown,
  faChevronUp,
  faCircleExclamation,
  faRotateRight,
  faWandMagicSparkles,
  faTimes,
} from '@fortawesome/free-solid-svg-icons';

import type { DimensionEvaluation } from '@/features/evaluation/api';
import { evaluationApi } from '@/features/evaluation/api';
import type { QualityEvaluationState } from '@/features/evaluation/hooks/useQualityEvaluation';
import { pct, scoreTier, TIER_STYLES, tierLabel } from '@/features/evaluation/utils/score';

interface QualityEvaluationPanelProps {
  sessionId: string;
  projectName?: string;
  embedded?: boolean;
  evaluation: QualityEvaluationState;
  showActionBar?: boolean;
}

type LayerFilter = 'all' | 1 | 2 | 3;
type IssueFilter = 'all' | 'issues';

function ScoreRing({ score, size = 120 }: { score: number; size?: number }) {
  const tier = scoreTier(score);
  const styles = TIER_STYLES[tier];
  const radius = (size - 12) / 2;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference * (1 - score);

  return (
    <div className="relative flex items-center justify-center" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="-rotate-90">
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke="#e8f2ed"
          strokeWidth={10}
        />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          className={styles.ring}
          strokeWidth={10}
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          style={{ transition: 'stroke-dashoffset 0.6s ease' }}
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className={`text-3xl font-bold tabular-nums ${styles.text}`}>
          {pct(score)}
        </span>
        <span className="text-[10px] text-[#8aa59a]">{tierLabel(tier)}</span>
      </div>
    </div>
  );
}

function formatOptionalPct(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined) return '—';
  return pct(value, digits);
}

function scoringModeLabel(mode: string): string {
  switch (mode) {
    case 'offline_template':
      return '离线模板（LLM 未参与）';
    case 'full':
      return '全量指标';
    case 'partial':
      return '部分指标';
    default:
      return '内容深度为主';
  }
}

function MetricTile({
  label,
  value,
  hint,
  isPercent = true,
}: {
  label: string;
  value: number | null | undefined;
  hint?: string;
  isPercent?: boolean;
}) {
  if (value === null || value === undefined) {
    return (
      <div className="rounded-2xl border border-dashed border-[#d6e8df] bg-[#f8fbf9] px-4 py-3">
        <div className="text-[11px] font-medium text-[#6d8f82]">{label}</div>
        <div className="mt-1 text-2xl font-semibold text-[#9ab2a8]">—</div>
        <div className="mt-0.5 text-[10px] text-[#9ab2a8]">暂不可用</div>
      </div>
    );
  }

  const tier = isPercent ? scoreTier(value) : scoreTier(value / 5);
  const styles = TIER_STYLES[tier];
  const display = isPercent ? pct(value) : `${value.toFixed(1)}/5`;

  return (
    <div className={`rounded-2xl border border-[#e1eee8] px-4 py-3 ${styles.bg}`}>
      <div className="text-[11px] font-medium text-[#6d8f82]">{label}</div>
      <div className={`mt-1 text-2xl font-semibold tabular-nums ${styles.text}`}>
        {display}
      </div>
      {hint && <div className="mt-0.5 text-[10px] text-[#9ab2a8]">{hint}</div>}
    </div>
  );
}

function DimensionCard({
  dim,
  expanded,
  onToggle,
}: {
  dim: DimensionEvaluation;
  expanded: boolean;
  onToggle: () => void;
}) {
  const tier = scoreTier(dim.overall_score);
  const styles = TIER_STYLES[tier];
  const issueCount =
    dim.hallucination_points.length + dim.hallucination_citations.length;

  return (
    <div className="rounded-xl border border-[#e5efe9] bg-white transition-shadow hover:shadow-sm">
      <button
        type="button"
        onClick={onToggle}
        className="flex w-full items-center gap-3 px-4 py-3 text-left"
      >
        <span
          className={`shrink-0 rounded-lg px-2 py-0.5 text-[10px] font-semibold ${styles.bg} ${styles.text}`}
        >
          L{dim.layer}
        </span>
        <div className="min-w-0 flex-1">
          <div className="truncate text-[13px] font-medium text-[#264f43]">
            {dim.dimension_name}
          </div>
          <div className="mt-0.5 flex items-center gap-2 text-[10px] text-[#9ab2a8]">
            <span>{dim.text_length.toLocaleString('zh-CN')} 字</span>
            {dim.citation_total > 0 && <span>{dim.citation_total} 处引用</span>}
            {issueCount > 0 && (
              <span className="text-[#e11d48]">
                <FontAwesomeIcon icon={faCircleExclamation} className="mr-0.5" />
                {issueCount} 项待核
              </span>
            )}
          </div>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <div className="h-1.5 w-16 overflow-hidden rounded-full bg-[#e8f2ed]">
            <div
              className={`h-full rounded-full ${styles.bar}`}
              style={{ width: pct(dim.overall_score) }}
            />
          </div>
          <span className={`text-sm font-semibold tabular-nums ${styles.text}`}>
            {pct(dim.overall_score)}
          </span>
          <FontAwesomeIcon
            icon={expanded ? faChevronUp : faChevronDown}
            className="text-[#b0c4bb] text-xs"
          />
        </div>
      </button>

      {expanded && (
        <div className="border-t border-[#edf4f0] px-4 py-3 space-y-3 text-[12px] text-[#5d7f72]">
          <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
            <div className="rounded-lg bg-[#f6fbf8] px-2 py-1.5">
              忠实度 <b className="text-[#2d8c6d]">{formatOptionalPct(dim.faithfulness_score)}</b>
            </div>
            <div className="rounded-lg bg-[#f6fbf8] px-2 py-1.5">
              内容深度 <b className="text-[#2d8c6d]">{dim.content_depth_score.toFixed(1)}</b>
            </div>
            <div className="rounded-lg bg-[#f6fbf8] px-2 py-1.5">
              引用存在 <b className="text-[#2d8c6d]">{formatOptionalPct(dim.citation_existence_rate)}</b>
            </div>
            <div className="rounded-lg bg-[#f6fbf8] px-2 py-1.5">
              引用准确 <b className="text-[#2d8c6d]">{formatOptionalPct(dim.citation_accuracy_rate)}</b>
            </div>
          </div>
          <p className="text-[11px] leading-relaxed text-[#8aa59a]">
            {dim.content_depth_reasoning}
          </p>

          {dim.hallucination_points.length > 0 && (
            <div>
              <div className="mb-1.5 text-[11px] font-semibold text-[#e11d48]">
                未支持陈述 ({dim.hallucination_points.length})
              </div>
              <ul className="space-y-1">
                {dim.hallucination_points.slice(0, 6).map((point) => (
                  <li
                    key={point}
                    className="rounded-lg border border-[#fecdd3] bg-[#fff1f2] px-2.5 py-1.5 text-[11px] text-[#9f1239]"
                  >
                    {point}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {dim.hallucination_citations.length > 0 && (
            <div>
              <div className="mb-1.5 text-[11px] font-semibold text-[#e11d48]">
                幻觉引用 ({dim.hallucination_citations.length})
              </div>
              <ul className="space-y-1">
                {dim.hallucination_citations.map((c) => (
                  <li
                    key={c.text}
                    className="flex items-start gap-2 rounded-lg border border-[#fecdd3] bg-[#fff1f2] px-2.5 py-1.5 text-[11px] text-[#9f1239]"
                  >
                    <FontAwesomeIcon icon={faTimes} className="mt-0.5 shrink-0" />
                    <span>{c.text}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {dim.citations.length > 0 && (
            <div>
              <div className="mb-1.5 text-[11px] font-semibold text-[#264f43]">
                引用溯源 ({dim.citations.length})
              </div>
              <div className="max-h-40 space-y-1 overflow-y-auto">
                {dim.citations.map((c) => (
                  <div
                    key={`${c.text}-${c.type}`}
                    className={`flex items-start gap-2 rounded-lg px-2.5 py-1.5 text-[11px] ${
                      c.exists_in_kb
                        ? 'bg-[#ecfdf5] text-[#166534]'
                        : 'bg-[#fff1f2] text-[#9f1239]'
                    }`}
                  >
                    <FontAwesomeIcon
                      icon={c.exists_in_kb ? faCheck : faTimes}
                      className="mt-0.5 shrink-0"
                    />
                    <div className="min-w-0">
                      <div>{c.text}</div>
                      {c.source_doc_name && (
                        <div className="mt-0.5 truncate text-[10px] opacity-70">
                          → {c.source_doc_name}
                        </div>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

const LAYER_LABELS: Record<number, string> = {
  1: 'L1 现状分析',
  2: 'L2 规划思路',
  3: 'L3 详细规划',
};

export default function QualityEvaluationPanel({
  sessionId,
  projectName,
  embedded = true,
  evaluation,
  showActionBar = true,
}: QualityEvaluationPanelProps) {
  const { result, loading, error, runEvaluation, loadExisting } = evaluation;
  const [expandedKey, setExpandedKey] = useState<string | null>(null);
  const [layerFilter, setLayerFilter] = useState<LayerFilter>('all');
  const [issueFilter, setIssueFilter] = useState<IssueFilter>('all');
  const [cascadeLoading, setCascadeLoading] = useState(false);
  const [cascadeError, setCascadeError] = useState('');
  const cascade = result?.cascade;

  const runCascade = useCallback(async () => {
    if (!sessionId || cascadeLoading) return;
    setCascadeLoading(true);
    setCascadeError('');
    try {
      await evaluationApi.runCascade(sessionId);
      await loadExisting();
    } catch (err) {
      setCascadeError(err instanceof Error ? err.message : '级联分析失败');
    } finally {
      setCascadeLoading(false);
    }
  }, [cascadeLoading, loadExisting, sessionId]);

  const exportMarkdown = useCallback(async () => {
    if (!sessionId) return;
    try {
      const { markdown, filename } = await evaluationApi.exportMarkdown(sessionId);
      const blob = new Blob([markdown], { type: 'text/markdown;charset=utf-8' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = filename;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      setCascadeError(err instanceof Error ? err.message : '导出失败');
    }
  }, [sessionId]);

  const filteredDimensions = useMemo(() => {
    if (!result) return [];
    let dims = [...result.dimensions];
    if (layerFilter !== 'all') {
      dims = dims.filter((d) => d.layer === layerFilter);
    }
    if (issueFilter === 'issues') {
      dims = dims.filter(
        (d) => d.hallucination_points.length > 0 || d.hallucination_citations.length > 0,
      );
    }
    return dims.sort((a, b) => a.layer - b.layer || b.overall_score - a.overall_score);
  }, [result, layerFilter, issueFilter]);

  const grouped = useMemo(() => {
    const groups: Record<number, DimensionEvaluation[]> = { 1: [], 2: [], 3: [] };
    for (const dim of filteredDimensions) {
      groups[dim.layer]?.push(dim);
    }
    return groups;
  }, [filteredDimensions]);

  if (!embedded) {
    return null;
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {showActionBar && (
        <div className="relative z-20 flex shrink-0 items-center justify-between gap-3 border-b border-[#e5efe9] bg-white px-4 py-3 shadow-[0_1px_0_rgba(229,239,233,0.9)]">
          <div className="min-w-0">
            <div className="flex items-center gap-2 text-[13px] font-semibold text-[#264f43]">
              <FontAwesomeIcon icon={faWandMagicSparkles} className="text-[#3fb288]" />
              规划质量自动评估
            </div>
            <p className="mt-0.5 text-[11px] text-[#8aa59a]">
              忠实度 · 内容深度 · 法规引用核验（RAG 文档库）
            </p>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            {result && (
              <button
                type="button"
                onClick={() => void exportMarkdown()}
                className="rounded-lg border border-[#d5e9df] px-3 py-1.5 text-[11px] text-[#52766a] hover:bg-[#f4faf7]"
              >
                导出 Markdown
              </button>
            )}
            {result && (
              <button
                type="button"
                onClick={() => void runCascade()}
                disabled={cascadeLoading}
                className="rounded-lg border border-[#d5e9df] px-3 py-1.5 text-[11px] text-[#52766a] hover:bg-[#f4faf7] disabled:opacity-50"
              >
                {cascadeLoading ? '级联分析中…' : '级联一致性'}
              </button>
            )}
            {result && (
              <button
                type="button"
                onClick={() => void loadExisting()}
                disabled={loading}
                className="rounded-lg border border-[#d5e9df] px-3 py-1.5 text-[11px] text-[#52766a] hover:bg-[#f4faf7] disabled:cursor-not-allowed disabled:opacity-50"
              >
                <FontAwesomeIcon icon={faRotateRight} className="mr-1" />
                刷新
              </button>
            )}
            <button
              type="button"
              onClick={() => void runEvaluation()}
              disabled={loading || !sessionId}
              aria-busy={loading}
              className="rounded-xl bg-[#3fb288] px-4 py-2 text-[12px] font-medium text-white shadow-sm shadow-emerald-100 hover:bg-[#319a75] disabled:cursor-not-allowed disabled:opacity-60"
            >
              {loading ? '评估中…' : result ? '重新评估' : '运行评估'}
            </button>
          </div>
        </div>
      )}

      <div className="relative min-h-0 flex-1 overflow-y-auto overscroll-contain p-4">
        {loading && result && (
          <div className="mb-4 flex items-center gap-2 rounded-xl border border-[#cfe4da] bg-[#f4fbf7] px-4 py-2.5 text-[12px] text-[#2d7e61]">
            <FontAwesomeIcon icon={faRotateRight} spin className="text-[#3fb288]" />
            正在重新分析各维度报告，约需 10–30 秒…
          </div>
        )}

        {error && (
          <div className="mb-4 rounded-xl border border-[#fecdd3] bg-[#fff1f2] px-4 py-3 text-[12px] text-[#be123c]">
            {error}
          </div>
        )}

        {cascadeError && (
          <div className="mb-4 rounded-xl border border-[#fecdd3] bg-[#fff1f2] px-4 py-3 text-[12px] text-[#be123c]">
            {cascadeError}
          </div>
        )}

        {!result && !loading && (
          <div className="flex flex-col items-center justify-center rounded-2xl border border-dashed border-[#cfe4da] bg-gradient-to-b from-[#f8fcf9] to-white py-16 text-center">
            <div className="mb-4 flex h-16 w-16 items-center justify-center rounded-2xl bg-[#e8f5ef] text-2xl text-[#3fb288]">
              <FontAwesomeIcon icon={faWandMagicSparkles} />
            </div>
            <h3 className="text-[15px] font-semibold text-[#264f43]">尚未生成质量报告</h3>
            <p className="mt-2 max-w-sm text-[12px] leading-relaxed text-[#8aa59a]">
              对当前会话的各维度报告进行自动化质量分析，检测文本忠实度、分析深度与法规引用真实性。
            </p>
            <button
              type="button"
              onClick={() => void runEvaluation()}
              disabled={loading || !sessionId}
              className="mt-5 rounded-xl bg-[#3fb288] px-5 py-2.5 text-[13px] font-medium text-white hover:bg-[#319a75] disabled:cursor-not-allowed disabled:opacity-60"
            >
              开始评估
            </button>
          </div>
        )}

        {loading && !result && (
          <div className="flex flex-col items-center justify-center py-20 text-[#8aa59a]">
            <FontAwesomeIcon icon={faRotateRight} spin className="mb-3 text-2xl text-[#3fb288]" />
            <p className="text-[13px]">正在分析各维度报告…</p>
            <p className="mt-1 text-[11px]">首次评估约需 10–30 秒</p>
          </div>
        )}

        {result && (
          <div className="space-y-5">
            {result.diagnostics?.warnings?.length > 0 && (
              <div className="rounded-xl border border-[#fde68a] bg-[#fffbeb] px-4 py-3 text-[12px] text-[#92400e]">
                <div className="mb-1 font-semibold flex items-center gap-1.5">
                  <FontAwesomeIcon icon={faCircleExclamation} />
                  评估说明
                </div>
                <ul className="space-y-1 pl-5 list-disc">
                  {result.diagnostics.warnings.map((warning) => (
                    <li key={warning}>{warning}</li>
                  ))}
                </ul>
              </div>
            )}

            <section className="rounded-2xl border border-[#dcebe4] bg-white p-5 shadow-[0_8px_24px_rgba(46,104,82,0.05)]">
              <div className="flex flex-wrap items-center gap-6">
                <ScoreRing score={result.overall.overall_score} />
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <h2 className="text-[16px] font-bold text-[#244c40]">
                      {result.project_name || projectName || '当前项目'}
                    </h2>
                    <span className={`rounded-full px-2.5 py-0.5 text-[10px] font-medium ${
                      result.diagnostics?.generation_mode === 'offline_template'
                        ? 'bg-[#fff7ed] text-[#c2410c]'
                        : 'bg-[#eef6f1] text-[#3a8f6f]'
                    }`}>
                      {scoringModeLabel(
                        result.diagnostics?.generation_mode === 'offline_template'
                          ? 'offline_template'
                          : result.overall.scoring_mode,
                      )}
                    </span>
                  </div>
                  <p className="mt-1 text-[11px] text-[#8aa59a]">
                    评估于 {new Date(result.evaluated_at).toLocaleString('zh-CN')}
                    · {result.overall.dimensions_evaluated} 个维度
                    · RAG 片段 {result.diagnostics?.dimensions_with_rag_chunks ?? 0} 维
                    · 引用 {result.overall.total_citations} 处
                  </p>
                  {result.overall.hallucination_citations > 0 && (
                    <p className="mt-2 inline-flex items-center gap-1 rounded-full bg-[#fff1f2] px-2.5 py-1 text-[11px] font-medium text-[#be123c]">
                      <FontAwesomeIcon icon={faCircleExclamation} />
                      {result.overall.hallucination_citations} 处引用未在文档库中找到
                    </p>
                  )}
                </div>
              </div>

              <div className="mt-5 grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-5">
                <MetricTile label="忠实度" value={result.overall.faithfulness_avg} />
                <MetricTile
                  label="内容深度"
                  value={result.overall.content_depth_avg}
                  isPercent={false}
                  hint="满分 5"
                />
                <MetricTile label="引用存在率" value={result.overall.citation_existence_avg} />
                <MetricTile label="引用准确率" value={result.overall.citation_accuracy_avg} />
                <MetricTile
                  label="未支持陈述"
                  value={
                    result.overall.total_claims > 0
                      ? result.overall.unsupported_claims / result.overall.total_claims
                      : null
                  }
                  hint={
                    result.overall.total_claims > 0
                      ? `${result.overall.unsupported_claims}/${result.overall.total_claims}`
                      : '无可核验陈述'
                  }
                />
              </div>
            </section>

            {cascade && (
              <section className="rounded-2xl border border-[#dcebe4] bg-white p-5 shadow-[0_8px_24px_rgba(46,104,82,0.05)]">
                <h3 className="text-[14px] font-semibold text-[#264f43]">
                  级联修订一致性 · {pct(cascade.overall_score)}
                </h3>
                {cascade.warnings.length > 0 && (
                  <ul className="mt-2 space-y-1 text-[11px] text-[#92400e]">
                    {cascade.warnings.map((w) => <li key={w}>{w}</li>)}
                  </ul>
                )}
                {cascade.pair_scores.length > 0 && (
                  <div className="mt-3 space-y-1">
                    {cascade.pair_scores.slice(0, 8).map((p) => (
                      <div key={`${p.dimension_key}-${p.target_dimension}`} className="flex justify-between text-[11px] text-[#5d7f72]">
                        <span>{p.dimension_name} ← {p.target_dimension}</span>
                        <span className="tabular-nums font-medium">{pct(p.score)}</span>
                      </div>
                    ))}
                  </div>
                )}
              </section>
            )}

            <div className="flex flex-wrap items-center gap-2">
              <div className="flex rounded-lg bg-[#f3f8f5] p-0.5">
                {(['all', 1, 2, 3] as LayerFilter[]).map((layer) => (
                  <button
                    key={String(layer)}
                    type="button"
                    onClick={() => setLayerFilter(layer)}
                    className={`rounded-md px-3 py-1 text-[11px] font-medium transition-colors ${
                      layerFilter === layer
                        ? 'bg-white text-[#1f7a59] shadow-sm'
                        : 'text-[#5d7f72] hover:text-[#2d8c6d]'
                    }`}
                  >
                    {layer === 'all' ? '全部层级' : LAYER_LABELS[layer]}
                  </button>
                ))}
              </div>
              <div className="flex rounded-lg bg-[#f3f8f5] p-0.5">
                {(['all', 'issues'] as IssueFilter[]).map((mode) => (
                  <button
                    key={mode}
                    type="button"
                    onClick={() => setIssueFilter(mode)}
                    className={`rounded-md px-3 py-1 text-[11px] font-medium transition-colors ${
                      issueFilter === mode
                        ? 'bg-white text-[#1f7a59] shadow-sm'
                        : 'text-[#5d7f72] hover:text-[#2d8c6d]'
                    }`}
                  >
                    {mode === 'all' ? '全部维度' : '仅待核项'}
                  </button>
                ))}
              </div>
              <span className="text-[11px] text-[#9ab2a8]">
                共 {filteredDimensions.length} 项
              </span>
            </div>

            {[1, 2, 3].map((layer) => {
              const dims = grouped[layer];
              if (!dims?.length) return null;
              return (
                <section key={layer}>
                  <h3 className="mb-2 flex items-center gap-2 text-[12px] font-semibold text-[#264f43]">
                    <span className="h-1.5 w-1.5 rounded-full bg-[#3fb288]" />
                    {LAYER_LABELS[layer]}
                    <span className="text-[#9ab2a8] font-normal">({dims.length})</span>
                  </h3>
                  <div className="space-y-2">
                    {dims.map((dim) => (
                      <DimensionCard
                        key={dim.dimension_key}
                        dim={dim}
                        expanded={expandedKey === dim.dimension_key}
                        onToggle={() =>
                          setExpandedKey((prev) =>
                            prev === dim.dimension_key ? null : dim.dimension_key,
                          )
                        }
                      />
                    ))}
                  </div>
                </section>
              );
            })}

            {filteredDimensions.length === 0 && (
              <div className="rounded-xl border border-[#e5efe9] bg-white py-10 text-center text-[12px] text-[#8aa59a]">
                当前筛选条件下没有匹配的维度
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
