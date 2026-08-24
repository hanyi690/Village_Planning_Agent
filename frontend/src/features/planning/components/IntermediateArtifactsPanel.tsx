'use client';

/**
 * IntermediateArtifactsPanel - 展示后端真实全流程的中间产物（artifacts）。
 *
 * 数据来源：GET /api/v1/sessions/{id}/artifacts/{key}（v1 权威端点）。
 * artifact key 与后端 `backend/app/infrastructure/artifacts/runtime.py` 的
 * ARTIFACT_KEYS 保持一致；404 表示该阶段尚未产出（正常等待态）。
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { planningApi } from '../api';
import type { ArtifactKey } from './artifact-keys';
import type { PositioningTraceResponse, PositioningTraceStep } from '../api/types';

interface ArtifactView {
  key: ArtifactKey;
  status: 'loading' | 'ready' | 'missing' | 'error';
  digest?: string;
  summary?: string;
  detail?: Record<string, unknown> | unknown[];
}

const STAGE_GROUPS: { stage: string; keys: ArtifactKey[] }[] = [
  { stage: '事实与闸门', keys: ['l1_source_index', 'l1_snapshot', 'l1_observations', 'l1_bindings', 'grounded_anchors', 'l1_gate'] },
  { stage: '策略与意图', keys: ['l2_strategy', 'l2_gate', 'planning_program', 'l3_gate'] },
  {
    stage: '目标与落地',
    keys: [
      'target_projection',
      'grounding_result',
      'demand_portfolio',
      'suitability_surface',
      'portfolio_decision',
      'site_selection',
    ],
  },
  {
    stage: '执行',
    keys: [
      'execution_plan',
      'execution_result',
      'parcel_changeset',
      'planned_state',
      'planning_scenario',
    ],
  },
  {
    stage: '校验与交付',
    keys: [
      'validation_report',
      'final_relation_validation',
      'reconciliation_report',
      'delivery_manifest',
      'layout_configs',
      'render_layers',
      'delivery_spatial_snapshot',
      'deferral_ledger',
      'export_result',
      'render_artifacts',
      'execution_diagnostics',
      'kg_layer1',
    ],
  },
];

const DELIVERY_ARTIFACT_KEYS: ArtifactKey[] = [
  'delivery_manifest',
  'layout_configs',
  'render_layers',
  'delivery_spatial_snapshot',
  'export_result',
  'render_artifacts',
];

const ARTIFACT_LABELS: Record<string, string> = {
  l1_snapshot: 'L1 现状快照',
  l1_source_index: 'L1 原始输入索引',
  l1_gate: 'L1 事实闸门',
  l1_observations: 'L1 观察记录',
  l1_bindings: 'L1 实体绑定',
  grounded_anchors: '空间锚点',
  l2_strategy: 'L2 规划策略',
  l2_gate: 'L2 策略闸门',
  planning_program: '规划程序草案',
  l3_gate: 'L3 规划闸门',
  target_projection: '目标投影',
  grounding_result: '空间落位结果',
  demand_portfolio: '需求组合',
  suitability_surface: '适宜性面',
  portfolio_decision: '组合决策',
  site_selection: '选址结果',
  execution_plan: '执行计划',
  execution_result: '执行结果',
  parcel_changeset: '地块变更集',
  planned_state: '规划状态',
  planning_scenario: '规划情景',
  validation_report: '校验报告',
  final_relation_validation: '最终关系校验',
  reconciliation_report: '一致性报告',
  delivery_manifest: '交付清单',
  layout_configs: '空间布局配置',
  render_layers: '渲染图层',
  delivery_spatial_snapshot: '交付空间快照',
  deferral_ledger: '延期台账',
  export_result: '导出结果',
  render_artifacts: '渲染产物',
  execution_diagnostics: '执行诊断',
  kg_layer1: 'L1 知识图谱层',
};

const ARTIFACT_FIELD_LABELS: Record<string, string> = {
  artifact_id: '产物编号',
  classification_refs: '分类引用',
  constraints: '约束',
  context_version: '上下文版本',
  created_at: '生成时间',
  dependencies: '依赖产物',
  development_goals: '发展目标',
  dimension_provenance: '维度来源',
  evidence_gaps: '证据缺口',
  evidence_refs: '证据引用',
  fact_records: 'L1 事实',
  location_facts: '位置事实',
  spatial_facts_by_dimension: '分维度空间事实',
  implementation_priorities: '实施重点',
  omissions: '省略项',
  opportunities: '机会',
  planning_intents: '规划意图',
  intervention_count: '干预事项',
  semantic_repair_applied: '语义修复',
  target_projection_node: '目标投影节点',
  projection_count: '投影目标数',
  objective_count: '目标数',
  candidate_count: '候选数',
  selected_count: '已选数',
  source_fact_refs: '来源事实',
  source_feature_refs: '来源空间要素',
  report_body: '人类可读正文',
  summary: '摘要',
  conclusion: '结论',
  schema_version: '结构版本',
  sources: '来源',
  spatial_structure: '空间结构',
};

function artifactFieldLabel(key: string): string {
  return ARTIFACT_FIELD_LABELS[key] || key.replaceAll('_', ' ');
}

function readableScalar(key: string, value: string | number | boolean): string {
  if (typeof value === 'boolean') {
    if (key === 'semantic_repair_applied') return value ? '已应用' : '未应用';
    return value ? '是' : '否';
  }
  if (typeof value === 'number' && key.endsWith('_count')) return `${value} 项`;
  return String(value);
}

const SPATIAL_CHAIN = [
  { stages: ['KG_PREBUILD', 'L1'], label: 'L1 事实底座', description: '现状观察、L1 fact、来源与空间锚点' },
  { stages: ['L2', 'EXPLORE', 'CONFLICT'], label: 'L2 策略与证据', description: '策略方向、探索证据与冲突记录' },
  { stages: ['L3', 'TARGET_PROJECTION'], label: 'L3 规划意图', description: '可读正文与结构化 claims 的双通道交付' },
  { stages: ['GROUND', 'SELECT'], label: '空间落位', description: '从意图到真实候选要素和选址结果' },
  { stages: ['EXECUTE'], label: '空间执行', description: '地块变更、道路与设施几何执行' },
  { stages: ['VALIDATE', 'RECONCILE'], label: '空间校验', description: '关系、几何和前后状态一致性检查' },
  { stages: ['DELIVER', 'OUTPUT', 'RENDER'], label: '成果交付', description: '交付快照、图层和人类可查看的渲染结果' },
];

function artifactLabel(key: string): string {
  return ARTIFACT_LABELS[key] || key;
}

function readableArtifactFacts(detail: Record<string, unknown> | unknown[] | undefined): Array<[string, string]> {
  if (!detail) return [];
  if (Array.isArray(detail)) return [['包含项目', `${detail.length} 项`]];
  const facts: Array<[string, string]> = [];
  const labelMap: Record<string, string> = {
    session_id: '会话',
    dimension_key: '维度',
    layer: '层级',
    status: '状态',
    count: '数量',
    feature_count: '空间要素数',
    claim_count: '规划判断数',
    claims_with_evidence: '有证据判断数',
    checksum: '校验摘要',
    schema_version: '结构版本',
    source: '来源',
    reason: '原因',
  };
  for (const [key, value] of Object.entries(detail)) {
    if (['geojson', 'features', 'claims', 'diagnostics', 'payload'].includes(key)) continue;
    if (value == null || value === '') continue;
    if (typeof value === 'object') {
      if (Array.isArray(value)) facts.push([labelMap[key] || artifactFieldLabel(key), `${value.length} 项`]);
      else if (key.endsWith('_node') || key.endsWith('_result')) facts.push([labelMap[key] || artifactFieldLabel(key), '已登记']);
      continue;
    }
    if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') {
      facts.push([labelMap[key] || artifactFieldLabel(key), readableScalar(key, value)]);
    }
    if (facts.length >= 6) break;
  }
  return facts;
}

function structuredArtifactHighlights(detail: Record<string, unknown> | unknown[] | undefined): string[] {
  if (!detail || Array.isArray(detail)) return [];
  const sourceKeys = ['claims', 'planning_intents', 'interventions', 'objectives', 'development_goals'];
  const highlights: string[] = [];
  for (const key of sourceKeys) {
    const values = detail[key];
    if (!Array.isArray(values)) continue;
    for (const value of values) {
      if (typeof value === 'string' && value.trim()) {
        highlights.push(value.trim());
      } else if (value && typeof value === 'object') {
        const item = value as Record<string, unknown>;
        const text = [item.statement, item.title, item.name, item.objective, item.description]
          .find((candidate): candidate is string => typeof candidate === 'string' && candidate.trim().length > 0);
        if (text) highlights.push(text.trim());
      }
      if (highlights.length >= 3) return highlights;
    }
  }
  return highlights;
}

function compactSidebarDetail(detail: Record<string, unknown>): Record<string, unknown> {
  const reportBody = detail.report_body;
  if (typeof reportBody !== 'string' || !reportBody.trim()) return detail;
  return {
    ...detail,
    report_body: `正文已记录（${reportBody.trim().length} 字）；完整正文请在“规划文本成果”中查看`,
  };
}

function summarizePayload(payload: unknown, artifactKey?: string): { summary: string; detail?: Record<string, unknown> | unknown[] } {
  if (payload == null) return { summary: '空 payload' };

  // GeoJSON FeatureCollection
  if (
    typeof payload === 'object' &&
    (payload as { type?: string }).type === 'FeatureCollection'
  ) {
    const fc = payload as { features?: unknown[] };
    const count = Array.isArray(fc.features) ? fc.features.length : 0;
    const firstProps =
      (fc.features?.[0] as { properties?: Record<string, unknown> } | undefined)?.properties;
    const keys = firstProps ? Object.keys(firstProps).slice(0, 8).join(', ') : '';
    return { summary: `FeatureCollection · ${count} 个要素${keys ? ` · 属性: ${keys}` : ''}`, detail: payload as Record<string, unknown> };
  }

  // render_layers 等列表
  if (Array.isArray(payload)) {
    const names = payload
      .slice(0, 12)
      .map((l) => (l as { layerName?: string; layerType?: string })?.layerName ?? (l as { layerType?: string })?.layerType ?? '')
      .filter(Boolean)
      .join('、');
    return { summary: `${artifactKey ? artifactLabel(artifactKey) : '产物'}：包含 ${payload.length} 项${names ? ` · ${names}` : ''}`, detail: payload };
  }

  if (typeof payload === 'object') {
    const obj = payload as Record<string, unknown>;
    const interesting: string[] = [];
    const hiddenMetadata = new Set(['artifact_id', 'context_version', 'created_at', 'schema_version', 'session_id', 'checksum', 'descriptor_digest']);
    for (const [k, v] of Object.entries(obj)) {
      if (hiddenMetadata.has(k) || k === 'diagnostics' || k === 'payload') continue;
      if (k === 'report_body' && typeof v === 'string') {
        interesting.push(`正文：已记录（${v.trim().length} 字）`);
        continue;
      }
      if (typeof v === 'string' && v.length > 0 && v.length < 120) interesting.push(`${artifactFieldLabel(k)}：${v}`);
      else if (typeof v === 'number' || typeof v === 'boolean') interesting.push(`${artifactFieldLabel(k)}：${readableScalar(k, v)}`);
      else if (Array.isArray(v) && v.length < 80) interesting.push(`${artifactFieldLabel(k)}：${v.length} 项`);
      else if (v && typeof v === 'object' && (k.endsWith('_node') || k.endsWith('_result'))) interesting.push(`${artifactFieldLabel(k)}：已登记`);
      else if (v && typeof v === 'object' && Array.isArray((v as { items?: unknown[] }).items)) {
        interesting.push(`${artifactFieldLabel(k)}：${(v as { items: unknown[] }).items.length} 项`);
      }
      if (interesting.length >= 8) break;
    }
    return {
      summary: interesting.length > 0
        ? interesting.slice(0, 4).join(' · ')
        : `${artifactKey ? artifactLabel(artifactKey) : '产物'}已记录，结构化内容可展开查看`,
      detail: compactSidebarDetail(obj),
    };
  }

  return { summary: String(payload).slice(0, 80) };
}

function summarizeStep(step: PositioningTraceStep): string {
  const outputs = step.outputs || {};
  const diagnostics = step.diagnostics || {};
  const parts: string[] = [];
  const labels: Record<string, string> = {
    word_count: '正文',
    claim_count: '规划判断',
    claims_with_evidence: '有证据判断',
    intervention_count: '干预事项',
    semantic_repair_applied: '语义修复',
    target_projection_node: '目标投影节点',
    candidate_count: '候选数',
    recommended_segment_count: '推荐段',
    road_target_count: '道路项目',
  };
  for (const [key, value] of Object.entries(outputs)) {
    if (value == null || value === '') continue;
    const label = labels[key];
    if (!label) continue;
    if (typeof value === 'boolean') {
      parts.push(`${label}${value ? '已应用' : '未应用'}`);
    } else if (typeof value === 'number' || typeof value === 'string') {
      parts.push(`${label} ${value}${key === 'word_count' ? ' 字' : ' 项'}`);
    } else if (Array.isArray(value)) {
      parts.push(`${label} ${value.length} 项`);
    } else if (typeof value === 'object') {
      parts.push(`${label}已登记`);
    }
    if (parts.length >= 3) break;
  }
  if (parts.length === 0 && Object.keys(diagnostics).length > 0) {
    parts.push(`诊断 ${Object.keys(diagnostics).length} 项`);
  }
  return parts.join(' · ') || '已记录步骤，但没有摘要字段';
}

interface IntermediateArtifactsPanelProps {
  sessionId: string | null;
  focusKey?: string | null;
}

export function IntermediateArtifactsPanel({ sessionId, focusKey = null }: IntermediateArtifactsPanelProps) {
  const [views, setViews] = useState<Record<string, ArtifactView>>({});
  const [trace, setTrace] = useState<PositioningTraceResponse | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [expandedKey, setExpandedKey] = useState<string | null>(null);
  const [showTrace, setShowTrace] = useState(false);
  const [showPendingArtifacts, setShowPendingArtifacts] = useState(false);
  const cancelledRef = useRef(false);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const refresh = useCallback(async () => {
    if (!sessionId || cancelledRef.current) return;
    setRefreshing(true);
    const allKeys = STAGE_GROUPS.flatMap((g) => g.keys);
    const next: Record<string, ArtifactView> = {};
    const artifactIndex = await planningApi.listArtifacts(sessionId).catch(() => null);
    const availableKeys = new Set(artifactIndex
      ? artifactIndex.artifacts.map((item) => item.artifact_key)
      : allKeys);
    for (const key of allKeys) {
      if (!availableKeys.has(key)) {
        next[key] = { key, status: 'missing', summary: '尚未产出' };
      }
    }
    await Promise.all([
      Promise.all(
        allKeys.filter((key) => availableKeys.has(key)).map(async (key) => {
          next[key] = { key, status: 'loading' };
          try {
            const artifact = await planningApi.getArtifact(sessionId, key);
            const { summary, detail } = summarizePayload(artifact.payload, key);
            next[key] = {
              key,
              status: 'ready',
              digest: artifact.artifact_ref?.digest?.slice(0, 12),
              summary,
              detail,
            };
          } catch (error) {
            const status = (error as { status?: number })?.status === 404 ? 'missing' : 'error';
            next[key] = { key, status, summary: status === 'missing' ? '尚未产出' : '读取失败' };
          }
        }),
      ),
      planningApi.getPositioningTrace(sessionId).then((value) => {
        if (!cancelledRef.current) setTrace(value);
      }).catch(() => {
        if (!cancelledRef.current) setTrace(null);
      }),
    ]);
    if (!cancelledRef.current) setViews(next);
    setRefreshing(false);
  }, [sessionId]);

  useEffect(() => {
    cancelledRef.current = false;
    setViews({});
    void refresh();
    timerRef.current = setInterval(() => void refresh(), 8000);
    return () => {
      cancelledRef.current = true;
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [sessionId, refresh]);

  useEffect(() => {
    if (!focusKey) return;
    setExpandedKey(focusKey);
  }, [focusKey]);

  const producedCount = useMemo(
    () => Object.values(views).filter((v) => v.status === 'ready').length,
    [views],
  );

  const latestStepByStage = useMemo(() => {
    const result = new Map<string, PositioningTraceStep>();
    for (const step of trace?.reports || []) result.set(step.stage, step);
    return result;
  }, [trace]);

  const pendingArtifactCount = useMemo(
    () => Object.values(views).filter((view) => view.status === 'missing').length,
    [views],
  );

  const latestTraceStep = trace?.reports[trace.reports.length - 1];
  const readyGroupCount = STAGE_GROUPS.filter((group) =>
    group.keys.some((key) => views[key]?.status === 'ready'),
  ).length;
  const totalArtifactCount = STAGE_GROUPS.reduce((count, group) => count + group.keys.length, 0);

  return (
    <div className="overflow-hidden rounded-2xl border border-[#dcebe4] bg-white shadow-[0_7px_24px_rgba(42,102,79,0.04)]">
      <div className="flex items-center justify-between border-b border-[#e3efe9] px-3 py-2.5">
        <div className="text-[13px] font-semibold text-[#2d7e61]">
          过程与产物 <span className="text-[11px] font-normal text-[#8aa79c]">({producedCount}/{totalArtifactCount} 已产出)</span>
        </div>
        <button
          type="button"
          onClick={() => void refresh()}
          disabled={refreshing}
          className="rounded-md bg-[#dff2e9] px-2 py-1 text-[11px] text-[#2d7e61] hover:bg-[#cdeade] disabled:opacity-50"
        >
          {refreshing ? '刷新中…' : '刷新'}
        </button>
      </div>
      <div className="max-h-[380px] space-y-3 overflow-y-auto px-3 py-3">
        {!sessionId && <div className="py-4 text-center text-[12px] text-[#9aada6]">等待会话创建…</div>}
        {sessionId && (
          <details
            className="rounded-xl border border-[#dcebe4] bg-[#f7fcf9]"
            open={showTrace}
            onToggle={(event) => setShowTrace(event.currentTarget.open)}
          >
            <summary className="flex cursor-pointer list-none items-center gap-2 px-3 py-2.5">
              <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-[#dff2e9] text-[11px] font-semibold text-[#2d7e61]">链</span>
              <span className="min-w-0 flex-1">
                <span className="block text-[12px] font-semibold text-[#315f50]">空间链过程</span>
                <span className="block truncate text-[10px] text-[#78968b]">
                  {latestTraceStep ? `当前 ${latestTraceStep.stage} · ${latestTraceStep.step_name || '已记录'}` : '等待后端过程记录'}
                </span>
              </span>
              <span className={`shrink-0 rounded-full px-2 py-1 text-[10px] ${trace?.complete ? 'bg-[#dff2e9] text-[#2d7e61]' : 'bg-[#fff3df] text-[#9a7428]'}`}>
                {trace ? `${trace.reports.length} 条记录` : '未读取'}
              </span>
            </summary>
            <div className="border-t border-[#e3eee8] px-3 py-3">
              <div className="mb-2 text-[10px] leading-4 text-[#78968b]">只展示后端已落库的 StepReport；没有记录的阶段不会被前端补成成果。</div>
              <div className="space-y-1.5">
              {SPATIAL_CHAIN.map((chainStep, index) => {
                const reports = chainStep.stages
                  .map((stage) => latestStepByStage.get(stage))
                  .filter((step): step is PositioningTraceStep => Boolean(step));
                const latest = reports[reports.length - 1];
                const hasTrace = reports.length > 0;
                const hasArtifact = chainStep.stages.some((stage) => (trace?.stage_coverage || {})[stage]);
                return (
                  <details key={chainStep.label} className="group rounded-lg border border-[#e3eee8] bg-white">
                    <summary className="flex cursor-pointer list-none items-center gap-2 px-2.5 py-2">
                      <span className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[10px] font-semibold ${hasTrace || hasArtifact ? 'bg-[#dff2e9] text-[#2d7e61]' : 'bg-[#eef3f0] text-[#9aada6]'}`}>{index + 1}</span>
                      <span className="min-w-0 flex-1">
                        <span className="block text-[11px] font-semibold text-[#3c6255]">{chainStep.label}</span>
                        <span className="block truncate text-[10px] text-[#8aa59a]">{hasTrace ? `${latest?.stage} · ${latest?.step_name || '已记录'}` : chainStep.description}</span>
                      </span>
                      <span className={`shrink-0 text-[10px] ${hasTrace ? 'text-[#2d8a68]' : 'text-[#9aada6]'}`}>{hasTrace ? '已记录' : '未产出'}</span>
                    </summary>
                    <div className="border-t border-[#edf4f0] px-2.5 py-2 text-[10px] leading-5 text-[#6d8c80]">
                      {hasTrace ? (
                        <>
                          <div>{summarizeStep(latest)}</div>
                          <div className="mt-1 text-[#8aa59a]">记录数：{reports.length} · 时间：{latest?.timestamp ? new Date(latest.timestamp).toLocaleString('zh-CN') : '—'}</div>
                          <details className="mt-2 rounded-md bg-[#f0f6f3] px-2 py-1.5">
                            <summary className="cursor-pointer text-[10px] text-[#6d8c80]">查看过程输入 / 输出 / 诊断</summary>
                            <pre className="mt-1 max-h-64 overflow-auto font-mono text-[9px] leading-relaxed text-[#4a6a5f]">{JSON.stringify(latest, null, 2).slice(0, 6000)}</pre>
                          </details>
                        </>
                      ) : (
                        <div>后端尚未落库 {chainStep.stages.join(' / ')} 阶段的 StepReport；这里不会用 artifact 名称或示意图冒充过程成果。</div>
                      )}
                    </div>
                  </details>
                );
              })}
              </div>
            </div>
          </details>
        )}
        {sessionId && (
          <div className="grid grid-cols-3 gap-1.5">
            <div className="rounded-lg border border-[#e3eee8] bg-white px-2 py-2">
              <div className="text-[10px] text-[#8aa59a]">已落库阶段</div>
              <div className="mt-0.5 text-[13px] font-semibold text-[#2d7e61]">{readyGroupCount}/{STAGE_GROUPS.length}</div>
            </div>
            <div className="rounded-lg border border-[#e3eee8] bg-white px-2 py-2">
              <div className="text-[10px] text-[#8aa59a]">可查看产物</div>
              <div className="mt-0.5 text-[13px] font-semibold text-[#2d7e61]">{producedCount} 项</div>
            </div>
            <div className="rounded-lg border border-[#e3eee8] bg-white px-2 py-2">
              <div className="text-[10px] text-[#8aa59a]">空间交付</div>
              <div className="mt-0.5 text-[13px] font-semibold text-[#9a7428]">{DELIVERY_ARTIFACT_KEYS.some((key) => views[key]?.status === 'ready') ? '已到达' : '未到达'}</div>
            </div>
          </div>
        )}
        {sessionId &&
          STAGE_GROUPS.map((group) => {
            const groupReadyCount = group.keys.filter((key) => views[key]?.status === 'ready').length;
            const visibleKeys = showPendingArtifacts
              ? group.keys
              : group.keys.filter((key) => views[key]?.status === 'ready' || views[key]?.status === 'loading' || views[key]?.status === 'error');
            if (!showPendingArtifacts && groupReadyCount === 0 && visibleKeys.length === 0) return null;
            return (
              <details key={group.stage} open={Boolean(focusKey && group.keys.some((key) => key === focusKey))} className="rounded-xl border border-[#dcebe4] bg-white">
              <summary className="flex cursor-pointer list-none items-center gap-2 rounded-xl bg-[#f7fcf9] px-3 py-2">
                <span className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[10px] font-semibold ${groupReadyCount > 0 ? 'bg-[#dff2e9] text-[#2d7e61]' : 'bg-[#eef3f0] text-[#9aada6]'}`}>
                  {groupReadyCount}
                </span>
                <span className="min-w-0 flex-1 text-[11px] font-semibold text-[#2d7e61]">{group.stage}</span>
                <span className="shrink-0 text-[10px] font-normal text-[#6c9685]">{groupReadyCount}/{group.keys.length} 已产出</span>
              </summary>
              <div className="space-y-1 border-t border-[#edf4f0] p-2">
                {visibleKeys.map((key) => {
                  const view = views[key];
                  return (
                    <div
                      key={key}
                      className="cursor-pointer rounded-lg border px-2.5 py-1.5 text-[12px]"
                      style={{
                        borderColor: view?.status === 'ready' ? '#cdeade' : '#e6ece9',
                        background: view?.status === 'ready' ? '#f4fbf7' : '#fafcfa',
                      }}
                      onClick={() => setExpandedKey(expandedKey === key ? null : key)}
                    >
                      <div className="flex items-center gap-1.5">
                        <span
                          className="inline-block h-1.5 w-1.5 shrink-0 rounded-full"
                          style={{
                            background:
                              view?.status === 'ready'
                                ? '#40b388'
                                : view?.status === 'loading'
                                  ? '#c9a86a'
                                  : '#b8c8c1',
                          }}
                        />
                        <span className="min-w-0 truncate text-[11px] font-semibold text-[#2d5f4e]">{artifactLabel(key)}</span>
                        <code className="shrink-0 font-mono text-[9px] text-[#9aada6]">{key}</code>
                        {view?.digest && (
                          <span className="ml-auto font-mono text-[10px] text-[#9aada6]">#{view.digest}</span>
                        )}
                      </div>
                      <div className="mt-0.5 pl-3 text-[11px] leading-snug text-[#6d8c80]">
                        {view?.status === 'loading' ? '读取中…' : view?.status === 'missing' ? '尚未到达该阶段，后端暂未产出' : (view?.summary ?? '等待产出…')}
                      </div>
                      {expandedKey === key && view?.detail != null && (
                        <div className="mt-2 space-y-2 border-t border-[#e6f0eb] pt-2">
                          <div className="grid grid-cols-2 gap-1.5 text-[10px]">
                            {readableArtifactFacts(view.detail).map(([label, value]) => (
                              <div key={`${label}-${value}`} className="rounded-md bg-white px-2 py-1.5">
                                <div className="text-[#9ab2a8]">{label}</div>
                                <div className="mt-0.5 break-words text-[#527467]">{value}</div>
                              </div>
                            ))}
                          </div>
                          {structuredArtifactHighlights(view.detail).length > 0 && (
                            <div className="rounded-md border border-[#e2eee8] bg-white px-2.5 py-2">
                              <div className="mb-1 text-[10px] font-semibold text-[#397b62]">结构化摘要</div>
                              <ul className="list-disc space-y-0.5 pl-4 text-[10px] leading-4 text-[#55786b]">
                                {structuredArtifactHighlights(view.detail).map((item, index) => (
                                  <li key={`${item}-${index}`} className="line-clamp-2">{item}</li>
                                ))}
                              </ul>
                            </div>
                          )}
                          <details className="rounded-md bg-[#f0f6f3] px-2 py-1.5">
                            <summary className="cursor-pointer text-[10px] text-[#6d8c80]">查看结构化 JSON（正文已折叠）</summary>
                            <pre className="mt-1 max-h-56 overflow-auto font-mono text-[10px] leading-relaxed text-[#4a6a5f]">
                              {JSON.stringify(view.detail, null, 2).slice(0, 4000)}
                              {JSON.stringify(view.detail, null, 2).length > 4000 ? ' …（已截断）' : ''}
                            </pre>
                          </details>
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </details>
            );
          })}
        {sessionId && pendingArtifactCount > 0 && (
          <button
            type="button"
            onClick={() => setShowPendingArtifacts((value) => !value)}
            className="w-full rounded-lg border border-dashed border-[#d7e7df] bg-[#fbfdfc] px-3 py-2 text-left text-[11px] text-[#78968b] hover:bg-[#f4faf7]"
          >
            {showPendingArtifacts ? '收起尚未产出的阶段' : `查看尚未产出的阶段（${pendingArtifactCount} 项）`}
            <span className="ml-1 text-[10px] text-[#a0b3aa]">后端未到达，不是前端加载失败</span>
          </button>
        )}
        <div className="rounded-lg bg-[#eef6f2] px-3 py-2 text-[11px] leading-relaxed text-[#6d8c80]">
          数据来自后端 artifacts 索引与 StepReport；只有已登记的产物才会读取详情。
        </div>
      </div>
    </div>
  );
}

export default IntermediateArtifactsPanel;
