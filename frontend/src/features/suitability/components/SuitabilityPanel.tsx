'use client';

import { useCallback, useEffect, useState } from 'react';

import { suitabilityApi, type SuitabilityResult } from '@/features/suitability/api';
import LayerCompletenessCard from '@/features/compliance/components/LayerCompletenessCard';

function barWidth(score: number) {
  return `${Math.round(score * 100)}%`;
}

export default function SuitabilityPanel({
  sessionId,
  projectName,
}: {
  sessionId: string;
  projectName?: string;
}) {
  const [result, setResult] = useState<SuitabilityResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const loadExisting = useCallback(async () => {
    try {
      const status = await suitabilityApi.getStatus(sessionId);
      if (status.has_result) {
        setResult(await suitabilityApi.getResults(sessionId));
      } else {
        setResult(null);
      }
    } catch {
      setResult(null);
    }
  }, [sessionId]);

  useEffect(() => {
    void loadExisting();
  }, [loadExisting]);

  const runAnalysis = useCallback(async () => {
    if (loading) return;
    setLoading(true);
    setError('');
    try {
      const res = await suitabilityApi.run(sessionId);
      if (res.result) setResult(res.result);
      else setResult(await suitabilityApi.getResults(sessionId));
    } catch (err) {
      setError(err instanceof Error ? err.message : '分析失败');
    } finally {
      setLoading(false);
    }
  }, [loading, sessionId]);

  const summary = result?.area_summary;

  return (
    <section className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-2xl border border-[#dcebe4] bg-white shadow-sm">
      <div className="flex shrink-0 items-center justify-between gap-3 border-b border-[#e5efe9] px-4 py-3">
        <div>
          <h3 className="text-[14px] font-semibold text-[#264f43]">双评价 · 建设适宜性</h3>
          <p className="text-[11px] text-[#8aa59a]">生态 / 农业 / 城镇建设多准则叠加</p>
        </div>
        <button
          type="button"
          onClick={() => void runAnalysis()}
          disabled={loading}
          className="rounded-xl bg-[#3fb288] px-4 py-2 text-[12px] font-medium text-white hover:bg-[#319a75] disabled:opacity-60"
        >
          {loading ? '分析中…' : result ? '重新分析' : '运行分析'}
        </button>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-4">
        {error && (
          <div className="mb-4 rounded-xl border border-[#fecdd3] bg-[#fff1f2] px-4 py-3 text-[12px] text-[#be123c]">
            {error}
          </div>
        )}

        {!result && !loading && (
          <div className="rounded-xl border border-dashed border-[#cfe4da] bg-[#f8fcf9] py-12 text-center text-[12px] text-[#8aa59a]">
            基于现状地块与约束因子，计算国土空间双评价适宜性
          </div>
        )}

        {result && summary && (
          <div className="space-y-4">
            {result.diagnostics.warnings.length > 0 && (
              <div className="rounded-xl border border-[#fde68a] bg-[#fffbeb] px-4 py-3 text-[12px] text-[#92400e]">
                {result.diagnostics.warnings.map((w) => <div key={w}>{w}</div>)}
              </div>
            )}

            {result.diagnostics.layer_completeness && (
              <LayerCompletenessCard completeness={result.diagnostics.layer_completeness} />
            )}

            <div className="rounded-xl border border-[#e1eee8] bg-white p-4">
              <h4 className="text-[13px] font-semibold text-[#264f43]">
                村域加权适宜性 · {result.project_name || projectName || result.diagnostics.village_name}
              </h4>
              <p className="mt-1 text-[11px] text-[#8aa59a]">
                {result.diagnostics.parcel_count} 地块 · 灾害点 {result.diagnostics.hazard_point_count}
                {result.diagnostics.calibration_profile && (
                  <> · 校准 {result.diagnostics.calibration_profile}</>
                )}
              </p>
              <div className="mt-4 grid gap-3 sm:grid-cols-3">
                {[
                  { label: '生态保护适宜', value: summary.ecological_weighted_avg, color: 'bg-[#2d8c6d]' },
                  { label: '农业生产适宜', value: summary.agricultural_weighted_avg, color: 'bg-[#45b88b]' },
                  { label: '城镇建设适宜', value: summary.construction_weighted_avg, color: 'bg-[#3b82f6]' },
                ].map((item) => (
                  <div key={item.label} className="rounded-xl border border-[#e5efe9] px-3 py-3">
                    <div className="text-[11px] text-[#6d8f82]">{item.label}</div>
                    <div className="mt-1 text-xl font-semibold tabular-nums text-[#264f43]">
                      {(item.value * 100).toFixed(0)}%
                    </div>
                    <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-[#e8f2ed]">
                      <div className={`h-full ${item.color}`} style={{ width: barWidth(item.value) }} />
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {result.zone_summaries.length > 0 && (
              <div className="rounded-xl border border-[#e1eee8] bg-white p-4">
                <h4 className="text-[13px] font-semibold text-[#264f43]">分区适宜性</h4>
                <div className="mt-3 space-y-2">
                  {result.zone_summaries.map((z) => (
                    <div key={z.zone} className="rounded-lg bg-[#f6fbf8] px-3 py-2 text-[11px]">
                      <div className="flex justify-between font-medium text-[#264f43]">
                        <span>{z.zone}</span>
                        <span>{z.area_ha.toFixed(1)} ha · {z.dominant_class}</span>
                      </div>
                      <div className="mt-1 text-[#6d8f82]">
                        生态 {Math.round(z.ecological_avg * 100)}% · 农业 {Math.round(z.agricultural_avg * 100)}% · 建设 {Math.round(z.construction_avg * 100)}%
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </section>
  );
}
