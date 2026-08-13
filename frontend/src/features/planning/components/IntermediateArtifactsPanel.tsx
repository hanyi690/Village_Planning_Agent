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

interface ArtifactView {
  key: ArtifactKey;
  status: 'loading' | 'ready' | 'missing' | 'error';
  digest?: string;
  summary?: string;
  detail?: Record<string, unknown> | unknown[];
}

const STAGE_GROUPS: { stage: string; keys: ArtifactKey[] }[] = [
  { stage: '分层解析', keys: ['l1_snapshot', 'l2_strategy', 'planning_program'] },
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
    keys: ['execution_plan', 'execution_result', 'parcel_changeset', 'planned_state'],
  },
  {
    stage: '校验与交付',
    keys: [
      'validation_report',
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

function summarizePayload(payload: unknown): { summary: string; detail?: Record<string, unknown> | unknown[] } {
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
    return { summary: `列表 · ${payload.length} 项${names ? ` · ${names}` : ''}`, detail: payload };
  }

  if (typeof payload === 'object') {
    const obj = payload as Record<string, unknown>;
    const interesting: string[] = [];
    for (const [k, v] of Object.entries(obj)) {
      if (typeof v === 'string' && v.length > 0 && v.length < 60) interesting.push(`${k}=${v}`);
      else if (typeof v === 'number' || typeof v === 'boolean') interesting.push(`${k}=${v}`);
      else if (Array.isArray(v) && v.length < 6) interesting.push(`${k}=[${v.length}]`);
      else if (v && typeof v === 'object' && Array.isArray((v as { items?: unknown[] }).items)) {
        interesting.push(`${k}=${(v as { items: unknown[] }).items.length}`);
      }
      if (interesting.length >= 8) break;
    }
    return { summary: interesting.length > 0 ? interesting.join(' · ') : Object.keys(obj).slice(0, 6).join(', '), detail: obj };
  }

  return { summary: String(payload).slice(0, 80) };
}

interface IntermediateArtifactsPanelProps {
  sessionId: string | null;
}

export function IntermediateArtifactsPanel({ sessionId }: IntermediateArtifactsPanelProps) {
  const [views, setViews] = useState<Record<string, ArtifactView>>({});
  const [refreshing, setRefreshing] = useState(false);
  const [expandedKey, setExpandedKey] = useState<string | null>(null);
  const cancelledRef = useRef(false);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const refresh = useCallback(async () => {
    if (!sessionId || cancelledRef.current) return;
    setRefreshing(true);
    const allKeys = STAGE_GROUPS.flatMap((g) => g.keys);
    const next: Record<string, ArtifactView> = {};
    await Promise.all(
      allKeys.map(async (key) => {
        next[key] = { key, status: 'loading' };
        try {
          const artifact = await planningApi.getArtifact(sessionId, key);
          const { summary, detail } = summarizePayload(artifact.payload);
          next[key] = {
            key,
            status: 'ready',
            digest: artifact.artifact_ref?.digest?.slice(0, 12),
            summary,
            detail,
          };
        } catch (error) {
          const status = (error as { status?: number })?.status === 404 ? 'missing' : 'error';
          next[key] = { key, status, summary: status === 'missing' ? '未产出（404）' : '读取失败' };
        }
      }),
    );
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

  const producedCount = useMemo(
    () => Object.values(views).filter((v) => v.status === 'ready').length,
    [views],
  );

  return (
    <div className="overflow-hidden rounded-2xl border border-[#dcebe4] bg-white shadow-[0_7px_24px_rgba(42,102,79,0.04)]">
      <div className="flex items-center justify-between border-b border-[#e3efe9] px-3 py-2.5">
        <div className="text-[13px] font-semibold text-[#2d7e61]">
          中间产物 <span className="text-[11px] font-normal text-[#8aa79c]">({producedCount} 已产出)</span>
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
      <div className="max-h-[520px] space-y-3 overflow-y-auto px-3 py-3">
        {!sessionId && <div className="py-4 text-center text-[12px] text-[#9aada6]">等待会话创建…</div>}
        {sessionId &&
          STAGE_GROUPS.map((group) => (
            <div key={group.stage}>
              <div className="mb-1 rounded-lg bg-[#dff2e9] px-3 py-1.5 text-[11px] font-semibold text-[#2d7e61]">
                {group.stage}
              </div>
              <div className="space-y-1">
                {group.keys.map((key) => {
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
                        <code className="shrink-0 font-mono text-[11px] font-semibold text-[#2d5f4e]">{key}</code>
                        {view?.digest && (
                          <span className="ml-auto font-mono text-[10px] text-[#9aada6]">#{view.digest}</span>
                        )}
                      </div>
                      <div className="mt-0.5 pl-3 text-[11px] leading-snug text-[#6d8c80]">
                        {view?.status === 'loading' ? '读取中…' : (view?.summary ?? '等待产出…')}
                      </div>
                      {expandedKey === key && view?.detail != null && (
                        <pre className="mt-1.5 max-h-56 overflow-auto rounded-md bg-[#f0f6f3] p-2 font-mono text-[10px] leading-relaxed text-[#4a6a5f]">
                          {JSON.stringify(view.detail, null, 2).slice(0, 4000)}
                          {JSON.stringify(view.detail, null, 2).length > 4000 ? ' …（已截断）' : ''}
                        </pre>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          ))}
        <div className="rounded-lg bg-[#eef6f2] px-3 py-2 text-[11px] leading-relaxed text-[#6d8c80]">
          数据来源：GET /api/v1/sessions/&#123;id&#125;/artifacts/&#123;key&#125;。
          中间产物按后端真实 ARTIFACT_KEYS 轮询；404 表示该阶段尚未产出。
        </div>
      </div>
    </div>
  );
}

export default IntermediateArtifactsPanel;