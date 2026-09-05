'use client';

import { useState } from 'react';

import { planningApi } from '@/features/planning/api';
import type { EvidenceFeatureRef, EvidenceQueryResponse } from '@/features/planning/api/types';

interface EvidenceQueryPanelProps {
  sessionId: string | null;
  villageName: string;
  onFocusFeature?: (feature: EvidenceFeatureRef) => void;
  onFocusFeatures?: (features: EvidenceFeatureRef[]) => void;
}

const percent = (value: number | null | undefined) => `${Math.round(Number(value ?? 0) * 100)}%`;

const compactRelationRef = (value: string) => value
  .split('|')
  .map((segment) => {
    const decoded = decodeURIComponent(segment);
    return decoded.split('#').pop()?.split('/').pop() || decoded;
  })
  .join(' → ');

export default function EvidenceQueryPanel({ sessionId, villageName, onFocusFeature, onFocusFeatures }: EvidenceQueryPanelProps) {
  const [query, setQuery] = useState('当前空间要素');
  const [result, setResult] = useState<EvidenceQueryResponse | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [includeExternal, setIncludeExternal] = useState(false);

  const submit = async (candidateOffset = 0) => {
    if (!sessionId || !query.trim()) return;
    setLoading(true);
    setError('');
    try {
      const response = await planningApi.queryEvidence(sessionId, {
        query: query.trim(),
        village_name: villageName,
        request_type: 'spatial_lookup',
        stage: 'GROUND',
        dimension_key: '',
        query_purpose: 'fact_check',
        candidate_offset: candidateOffset,
        candidate_limit: 12,
        include_external: includeExternal,
      });
      setResult(response);
      onFocusFeatures?.(response.evidence_packet?.candidate_refs ?? []);
    } catch (cause) {
      setResult(null);
      setError(cause instanceof Error ? cause.message : '证据查询失败');
    } finally {
      setLoading(false);
    }
  };

  const packet = result?.evidence_packet;
  const candidates = packet?.candidate_refs ?? [];
  const candidateTotal = packet?.candidate_total ?? candidates.length;
  const hasNextCandidatePage = Boolean(
    packet?.candidates_truncated && packet.next_candidate_offset != null,
  );
  const parserTrace = packet?.query_trace?.find((trace) => trace.step === 'directional_scope_hint');
  const structuredParserTrace = packet?.query_trace?.find((trace) => trace.step === 'spatial_query_parser');
  const candidateScopeTrace = packet?.query_trace?.find((trace) => trace.step === 'semantic_candidate_scope');
  const semanticTrace = packet?.query_trace?.find((trace) => trace.step === 'source_semantic_overlay');
  const coverageTrace = packet?.query_trace?.find((trace) => trace.step === 'semantic_candidate_scope');
  const semanticDiagnostics = Array.isArray(semanticTrace?.diagnostics)
    ? semanticTrace.diagnostics as Array<Record<string, unknown>>
    : [];
  const semanticDiagnostic = semanticDiagnostics[0];
  const failureTraces = (packet?.query_trace ?? []).filter((trace) => {
    const step = String(trace.step ?? '');
    return ['retriever', 'context_hydration', 'evidence_graph_prefetch', 'evidence_graph_enrichment', 'external_exception'].includes(step)
      && String(trace.status ?? '') === 'failed';
  });
  const retrieverTraces = (packet?.query_trace ?? []).filter((trace) => (
    trace.step === 'retriever'
    && ['returned', 'empty', 'failed', 'deferred'].includes(String(trace.status ?? ''))
  ));
  const sourceTypes = Array.from(new Set(
    (result?.evidence_bundle.sources ?? [])
      .map((source) => String(source.source_type ?? ''))
      .filter(Boolean),
  ));
  const sourceRoles = Array.from(new Set(
    (result?.evidence_bundle.sources ?? [])
      .map((source) => {
        const sourceType = String(source.source_type ?? '').trim();
        const role = String(source.evidence_role ?? '').trim();
        const authority = String(source.authority ?? '').trim();
        return [sourceType, role, authority].filter(Boolean).join(' / ');
      })
      .filter(Boolean),
  ));
  const ambiguityLabel = packet?.ambiguity_status === 'resolved'
    ? '已定位'
    : packet?.ambiguity_status === 'multiple'
      ? '多候选'
      : '未定位';
  const scopeLabels: Record<string, string> = {
    facilities: '设施',
    hazards: '灾害点',
    roads: '道路',
    waters: '水体',
    parcels: '地块',
    zones: '分区',
  };
  const effectiveScopes = Array.isArray(candidateScopeTrace?.effective_scopes)
    ? candidateScopeTrace.effective_scopes.map((scope) => scopeLabels[String(scope)] || String(scope))
    : [];
  const projectWideCoverage = coverageTrace?.source_coverage === 'project_wide'
    || coverageTrace?.project_wide === true;
  const facts = result?.evidence_bundle.facts ?? [];
  const sourceSpans = packet?.source_spans ?? [];
  const relationEvidence = packet?.relation_evidence ?? [];
  const unresolvedEvidence = result?.evidence_bundle.unresolved ?? [];
  const conflicts = result?.evidence_bundle.conflicts ?? [];
  const sourceLabel = (reference: string) => {
    const source = (result?.evidence_bundle.sources ?? []).find((item) => item.reference === reference);
    if (!source) return reference;
    return [source.source_type, source.evidence_role, source.authority].filter(Boolean).join(' / ');
  };

  return (
    <div className="overflow-hidden rounded-2xl border border-[#dcebe4] bg-white shadow-[0_7px_24px_rgba(42,102,79,0.04)]">
      <div className="flex items-center justify-between border-b border-[#edf4f0] px-3 py-2.5">
        <div>
          <div className="text-[12px] font-semibold text-[#315f50]">Evidence 查询演示</div>
          <div className="mt-0.5 text-[10px] text-[#8aa59a]">项目全域 Evidence · L1 · report · KG · Bundle · artifact/history · 拓扑统一入口</div>
        </div>
        <span className="rounded-full bg-[#e8f6ef] px-2 py-1 text-[10px] text-[#2e8a68]">只读</span>
      </div>
      <div className="space-y-2.5 p-3">
        <div className="flex gap-2">
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter') void submit();
            }}
            disabled={!sessionId || loading}
            className="min-w-0 flex-1 rounded-lg border border-[#dcebe4] px-2.5 py-2 text-[11px] text-[#315f50] outline-none focus:border-[#42b48a]"
            placeholder="例如：当前空间要素的来源和位置"
          />
          <button
            type="button"
            onClick={() => void submit()}
            disabled={!sessionId || loading || !query.trim()}
            className="rounded-lg bg-[#42b48a] px-3 py-2 text-[11px] font-semibold text-white disabled:cursor-not-allowed disabled:opacity-45"
          >
            {loading ? '查询中' : '查询'}
          </button>
        </div>
        <label className="flex items-center gap-2 text-[10px] text-[#78968b]">
          <input
            type="checkbox"
            checked={includeExternal}
            onChange={(event) => setIncludeExternal(event.target.checked)}
            disabled={!sessionId || loading}
          />
          本地证据不足时允许外源检索（需要部署配置 provider）
        </label>
        {!sessionId && <div className="text-[10px] text-[#a27a58]">启动会话后可查询当前 DATA/WM 快照。</div>}
        {error && <div className="rounded-lg bg-[#fff3ed] px-2.5 py-2 text-[10px] leading-4 text-[#a55d42]">{error}</div>}
        {result && (
          <div className="space-y-2 text-[10px] text-[#5e7b70]">
            <div className="flex flex-wrap gap-1.5">
              <span className="rounded-full bg-[#e8f6ef] px-2 py-1 text-[#2e8a68]">证据包：{packet?.sufficiency ?? 'partial'}</span>
              <span className="rounded-full bg-[#f1f6f4] px-2 py-1">候选：{candidates.length}/{candidateTotal}</span>
              <span className="rounded-full bg-[#f1f6f4] px-2 py-1">结果：{ambiguityLabel}</span>
              {sourceTypes.length > 0 && <span className="rounded-full bg-[#f1f6f4] px-2 py-1">来源：{sourceTypes.join(' · ')}</span>}
              {sourceRoles.length > 0 && <span className="rounded-full bg-[#eef3ff] px-2 py-1 text-[#526da8]">作用：{sourceRoles.join(' · ')}</span>}
              {parserTrace && <span className="rounded-full bg-[#eef3ff] px-2 py-1 text-[#526da8]">范围：{parserTrace.parser === 'llm_structured' ? 'LLM结构化' : '确定性解析'}</span>}
              {structuredParserTrace && (
                <span className={`rounded-full px-2 py-1 ${structuredParserTrace.status === 'failed' ? 'bg-[#fff3ed] text-[#a55d42]' : 'bg-[#f1f6f4]'}`}>
                  查询解析：{structuredParserTrace.status === 'resolved'
                    ? 'LLM结构化'
                    : structuredParserTrace.status === 'disabled'
                      ? '已关闭'
                      : structuredParserTrace.status === 'failed'
                        ? '失败，已暴露诊断'
                        : '未识别结构化空间引用'}
                </span>
              )}
              {candidateScopeTrace && (
                <span className="rounded-full bg-[#eef3ff] px-2 py-1 text-[#526da8]">
                  候选范围：{candidateScopeTrace.status === 'llm_structured'
                    ? `LLM · ${effectiveScopes.join(' · ') || '未指定'}`
                    : candidateScopeTrace.status === 'request_declared'
                      ? effectiveScopes.join(' · ') || '调用方指定'
                      : '全类型精确证据'}
                </span>
              )}
              {projectWideCoverage && (
                <span className="rounded-full bg-[#e8f6ef] px-2 py-1 text-[#2e8a68]">
                  检索范围：项目全域（未指定图层）
                </span>
              )}
              {semanticTrace && (
                <span className="rounded-full bg-[#fff8e8] px-2 py-1 text-[#8a6420]">
                  语义：{Number(semanticTrace.decision_count ?? 0) > 0 ? '已验证' : '未完成'}
                </span>
              )}
            </div>
            {hasNextCandidatePage && (
              <div className="flex items-center justify-between gap-2 rounded-lg bg-[#fff8e8] px-2.5 py-2 text-[#8a6420]">
                <span>
                  当前仅展示这一页，仍有 {Math.max(0, candidateTotal - candidates.length - (packet?.candidate_offset ?? 0))} 个候选；未返回的候选不会被当作不存在。
                </span>
                <button
                  type="button"
                  onClick={() => void submit(packet?.next_candidate_offset ?? 0)}
                  disabled={loading}
                  className="shrink-0 rounded-md border border-[#e4c982] px-2 py-1 text-[10px] font-semibold text-[#8a6420] disabled:opacity-45"
                >
                  下一页
                </button>
              </div>
            )}
            {semanticDiagnostic && (
              <div className="rounded-lg bg-[#fff8e8] px-2.5 py-2 leading-4 text-[#8a6420]">
                语义证据状态：{String(semanticDiagnostic.message ?? semanticDiagnostic.code ?? '未完成')}
              </div>
            )}
            {failureTraces.length > 0 && (
              <div className="rounded-lg bg-[#fff3ed] px-2.5 py-2 leading-4 text-[#a55d42]">
                <div className="font-semibold">检索失败诊断</div>
                {failureTraces.slice(0, 4).map((trace, index) => (
                  <div key={`${String(trace.step)}-${index}`}>
                    {String(trace.step)}：{String(trace.error ?? trace.reason ?? '未提供原因')}
                  </div>
                ))}
              </div>
            )}
            {retrieverTraces.length > 0 && (
              <div className="rounded-lg bg-[#f5f9f7] px-2.5 py-2 leading-4 text-[#607f72]">
                <div className="font-semibold text-[#4b7868]">项目来源检索状态</div>
                <div className="mt-0.5 flex flex-wrap gap-x-2 gap-y-0.5 text-[9px]">
                  {retrieverTraces.map((trace, index) => (
                    <span key={`${String(trace.retriever)}-${index}`}>
                      {String(trace.retriever)}：{String(trace.status)}
                      {trace.fact_count != null ? ` · facts=${String(trace.fact_count)}` : ''}
                      {trace.source_count != null ? ` · sources=${String(trace.source_count)}` : ''}
                    </span>
                  ))}
                </div>
              </div>
            )}
            <details
              className="rounded-lg border border-[#e2eee8] bg-[#fbfefd] px-2.5 py-2"
              open={facts.length > 0 || sourceSpans.length > 0 || relationEvidence.length > 0}
            >
              <summary className="cursor-pointer font-semibold text-[#356c59]">
                项目级相关证据明细（事实 {facts.length} · 文本背景 {sourceSpans.length} · KG/拓扑关系 {relationEvidence.length}）
              </summary>
              <div className="mt-2 space-y-2 leading-4 text-[#607f72]">
                {facts.length > 0 && (
                  <div className="space-y-1.5">
                    <div className="font-semibold text-[#4b7868]">结构化事实</div>
                    {facts.map((fact, index) => (
                      <div key={`${fact.fact_type}-${index}`} className="rounded-md bg-[#f3faf6] px-2 py-1.5">
                        <div className="text-[#315f50]">{fact.statement || '未提供事实陈述'}</div>
                        <div className="mt-0.5 flex flex-wrap gap-x-2 gap-y-0.5 text-[9px] text-[#78968b]">
                          <span>类型：{fact.fact_type || 'statement'}</span>
                          <span>来源种类：{fact.source_kind || '未标注'}</span>
                          <span>作用：{fact.evidence_role || fact.planning_use || 'context'}</span>
                          <span>空间粒度：{fact.spatial_granularity || 'none'}</span>
                          <span>置信度：{percent(fact.confidence)}</span>
                        </div>
                        {fact.source_refs.length > 0 && (
                          <div className="mt-0.5 break-all text-[9px] text-[#78968b]">
                            来源：{fact.source_refs.map((reference) => `${sourceLabel(reference)} [${reference}]`).join('；')}
                          </div>
                        )}
                        {fact.spatial_refs.length > 0 && (
                          <div className="mt-0.5 break-all text-[9px] text-[#78968b]">
                            空间关联：{fact.spatial_refs.join('、')}
                          </div>
                        )}
                        {fact.spatial_granularity !== 'none' && (
                          <div className="mt-0.5 break-all text-[9px] text-[#5d806f]">
                            空间粒度：{fact.spatial_granularity}；空间权威：{fact.source_locator || '由 DATA catalog 提供'}
                          </div>
                        )}
                        {fact.evidence_span && (
                          <div className="mt-0.5 border-l-2 border-[#b9decc] pl-1.5 text-[9px] text-[#6e8c80]">
                            原文证据：{fact.evidence_span}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                )}
                {sourceSpans.length > 0 && (
                  <div className="space-y-1.5">
                    <div className="font-semibold text-[#4b7868]">文本背景（报告 / L1 / RAG 或外源片段）</div>
                    {sourceSpans.map((span, index) => (
                      <div key={`${span.slice(0, 24)}-${index}`} className="border-l-2 border-[#c9dced] pl-1.5 text-[#6e8c80]">
                        {span}
                      </div>
                    ))}
                  </div>
                )}
                {relationEvidence.length > 0 && (
                  <div className="space-y-1.5">
                    <div className="font-semibold text-[#4b7868]">KG / 拓扑关系</div>
                    {relationEvidence.map((relation) => (
                      <div key={relation.relation_id} className="rounded-md bg-[#f1f6fb] px-2 py-1.5 text-[#617795]">
                        <div>
                          {relation.subject.identity.canonical_name || relation.subject.identity.source_feature_id}
                          <span className="mx-1 text-[#8aa5c1]">{compactRelationRef(relation.predicate)}</span>
                          {relation.object.identity.canonical_name || relation.object.identity.source_feature_id}
                        </div>
                        <div className="mt-0.5 text-[9px]">
                          关系证据：{relation.relation_id}
                          {relation.metric_value != null ? `；${relation.metric_value}${relation.metric_unit || ''}` : ''}
                          {relation.computation_method ? `；方法 ${relation.computation_method}` : ''}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
                {unresolvedEvidence.length > 0 && (
                  <div className="rounded-md bg-[#fff8e8] px-2 py-1.5 text-[#8a6420]">
                    未解析证据：{unresolvedEvidence.join('；')}
                  </div>
                )}
                {conflicts.length > 0 && (
                  <div className="rounded-md bg-[#fff3ed] px-2 py-1.5 text-[#a55d42]">
                    证据冲突：{conflicts.map((conflict) => conflict.reason).join('；')}
                  </div>
                )}
                {facts.length === 0 && sourceSpans.length === 0 && relationEvidence.length === 0
                  && unresolvedEvidence.length === 0 && conflicts.length === 0 && (
                    <div className="text-[#8aa59a]">本次没有可展开的文本、事实或关系明细；空间候选仍按 DATA resource reference 展示。</div>
                  )}
                <div className="border-t border-[#e5f0ea] pt-1.5 text-[9px] text-[#8aa59a]">
                  几何只通过候选的 DATA resource/representation ref 使用；报告、L1、WM、RAG 和外源内容作为可审计的语义/关系背景，不直接替代几何权威。
                </div>
              </div>
            </details>
            {candidates.length > 0 ? candidates.slice(0, 12).map((candidate) => (
              <div
                key={`${candidate.resource_ref}-${candidate.identity.source_feature_id || 'feature'}`}
                className="rounded-lg border border-[#e2eee8] bg-[#f8fcfa] px-2.5 py-2"
              >
                <button
                  type="button"
                  onClick={() => {
                    onFocusFeature?.(candidate);
                    onFocusFeatures?.([candidate]);
                  }}
                  className="block w-full text-left hover:text-[#1f7657]"
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0 font-semibold text-[#356c59]">
                      <span className="break-words">{candidate.identity.canonical_name || candidate.identity.role || candidate.identity.entity_type || '空间候选'}</span>
                      <span className="ml-1 font-normal text-[#78968b]">· {candidate.identity.role || candidate.identity.entity_type || '空间实体'}</span>
                    </div>
                    <span className={`shrink-0 rounded-full px-1.5 py-0.5 text-[9px] font-semibold ${
                      packet?.ambiguity_status === 'resolved'
                        ? 'bg-[#dff2e9] text-[#2d7e61]'
                        : packet?.ambiguity_status === 'multiple'
                          ? 'bg-[#fff1d9] text-[#8a6420]'
                          : 'bg-[#fff3ed] text-[#a55d42]'
                    }`}>
                      {packet?.ambiguity_status === 'resolved'
                        ? '已定位'
                        : packet?.ambiguity_status === 'multiple'
                          ? '待选择'
                          : '待核查'}
                    </span>
                  </div>
                  <div className="mt-1 text-[#607f72]">
                    {candidate.entity_refs?.length
                      ? `关联实体（${candidate.entity_refs.length}）：${candidate.entity_refs.join('、')}`
                      : `来源图层：${candidate.identity.source_layer || '未分层'}`}
                  </div>
                  <div className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-[#78968b]">
                    <span>语义 {percent(candidate.semantic_match_score)}</span>
                    <span>空间 {percent(candidate.spatial_support_score)}</span>
                    <span>排序 {percent(candidate.retrieval_score)}</span>
                  </div>
                </button>
                <details className="mt-1.5 border-t border-[#e5f0ea] pt-1.5">
                  <summary className="cursor-pointer text-[10px] text-[#6e9485]">查看来源与空间标识</summary>
                  <div className="mt-1.5 space-y-0.5 break-all text-[10px] leading-4 text-[#78968b]">
                    <div>resource：{candidate.resource_ref || '—'}</div>
                    <div>feature：{candidate.identity.source_feature_id || '—'}</div>
                    <div>geometry：{candidate.geometry_ref || '—'}</div>
                    <div>几何权威（非定位置信度）：{percent(candidate.source_authority_score)} · 最终选择：{candidate.selection_confidence == null ? '尚未执行' : percent(candidate.selection_confidence)}</div>
                    <div>L1 fact：{candidate.l1_fact_refs?.length ? candidate.l1_fact_refs.join('、') : '—'}</div>
                    <div>关系：{candidate.relation_refs?.length ? candidate.relation_refs.map(compactRelationRef).join('、') : '无显式关系'}</div>
                  </div>
                </details>
              </div>
            )) : <div className="rounded-lg bg-[#fff8e8] px-2.5 py-2 text-[#8a6420]">暂无可定位候选，缺口已保留在 evidence packet。</div>}
            {packet?.missing_evidence?.length ? <div>缺口：{packet.missing_evidence.slice(0, 3).join('、')}</div> : null}
          </div>
        )}
      </div>
    </div>
  );
}
