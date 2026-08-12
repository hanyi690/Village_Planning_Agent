'use client';

import { useCallback, useEffect, useState } from 'react';

import { complianceApi, type ComplianceResult } from '@/features/compliance/api';
import LayerCompletenessCard from '@/features/compliance/components/LayerCompletenessCard';

function pct(n: number, digits = 1) {
  return `${n.toFixed(digits)}%`;
}

export default function CompliancePanel({
  sessionId,
  projectName,
}: {
  sessionId: string;
  projectName?: string;
}) {
  const [result, setResult] = useState<ComplianceResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const loadExisting = useCallback(async () => {
    try {
      const status = await complianceApi.getStatus(sessionId);
      if (status.has_result) {
        setResult(await complianceApi.getResults(sessionId));
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
      const res = await complianceApi.run(sessionId);
      if (res.result) setResult(res.result);
      else setResult(await complianceApi.getResults(sessionId));
    } catch (err) {
      setError(err instanceof Error ? err.message : '分析失败');
    } finally {
      setLoading(false);
    }
  }, [loading, sessionId]);

  const gate = result?.delivery_gate;
  const balance = result?.land_balance;

  return (
    <section className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-2xl border border-[#dcebe4] bg-white shadow-sm">
      <div className="flex shrink-0 items-center justify-between gap-3 border-b border-[#e5efe9] px-4 py-3">
        <div>
          <h3 className="text-[14px] font-semibold text-[#264f43]">用地平衡表 · 合规闸门</h3>
          <p className="text-[11px] text-[#8aa59a]">L1 现状 vs L4 规划 · 三线冲突 · 变更比例</p>
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
            生成土地利用结构调整表（附表2）并校验出口合规闸门
          </div>
        )}

        {result && balance && gate && (
          <div className="space-y-4">
            {result.diagnostics.warnings.length > 0 && (
              <div className="rounded-xl border border-[#fde68a] bg-[#fffbeb] px-4 py-3 text-[12px] text-[#92400e]">
                {result.diagnostics.warnings.map((w) => <div key={w}>{w}</div>)}
              </div>
            )}

            {result.diagnostics.layer_completeness && (
              <LayerCompletenessCard completeness={result.diagnostics.layer_completeness} />
            )}

            <div className={`rounded-xl border px-4 py-3 ${gate.passed ? 'border-[#b8e6d4] bg-[#ecfdf5]' : 'border-[#fecdd3] bg-[#fff1f2]'}`}>
              <div className="flex items-center justify-between">
                <span className="text-[13px] font-semibold text-[#264f43]">
                  合规闸门 · {gate.passed ? '通过' : '未通过'}
                </span>
                <span className="text-[11px] text-[#6d8f82]">
                  {result.project_name || projectName || result.diagnostics.village_name}
                </span>
              </div>
              {gate.failures.length > 0 && (
                <ul className="mt-2 space-y-1 text-[12px] text-[#be123c]">
                  {gate.failures.map((f) => <li key={f}>• {f}</li>)}
                </ul>
              )}
              <div className="mt-3 grid grid-cols-2 gap-2 text-[11px] md:grid-cols-4">
                <div className="rounded-lg bg-white/80 px-2 py-1.5">平衡闭合 {balance.is_closed ? '✓' : '✗'}</div>
                <div className="rounded-lg bg-white/80 px-2 py-1.5">三线冲突 {gate.three_line_violations}</div>
                <div className="rounded-lg bg-white/80 px-2 py-1.5">保护侵入 {gate.protected_intrusions}</div>
                <div className="rounded-lg bg-white/80 px-2 py-1.5">变更比例 {pct(gate.changed_parcels_pct)}</div>
              </div>
            </div>

            <div className="rounded-xl border border-[#e1eee8] bg-white p-4">
              <h4 className="text-[13px] font-semibold text-[#264f43]">用地平衡摘要</h4>
              <p className="mt-1 text-[11px] text-[#8aa59a]">
                现状 {balance.total_current_area_ha.toFixed(2)} ha → 规划 {balance.total_planned_area_ha.toFixed(2)} ha
                · 闭合偏差 {pct(balance.closure_deviation_pct)}
              </p>
              <div className="mt-3 overflow-x-auto">
                <table className="min-w-full text-left text-[11px]">
                  <thead className="text-[#6d8f82]">
                    <tr>
                      <th className="px-2 py-1">地类</th>
                      <th className="px-2 py-1">现状(hm²)</th>
                      <th className="px-2 py-1">规划(hm²)</th>
                      <th className="px-2 py-1">增减</th>
                    </tr>
                  </thead>
                  <tbody>
                    {balance.rows.slice(0, 20).map((row) => (
                      <tr key={row.land_use_code} className="border-t border-[#edf4f0]">
                        <td className="px-2 py-1.5">{row.land_use_name}</td>
                        <td className="px-2 py-1.5 tabular-nums">{row.current_area_ha.toFixed(2)}</td>
                        <td className="px-2 py-1.5 tabular-nums">{row.planned_area_ha.toFixed(2)}</td>
                        <td className="px-2 py-1.5 tabular-nums">{row.change_ha.toFixed(2)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {balance.rows.length > 20 && (
                  <p className="mt-2 text-[10px] text-[#9ab2a8]">显示前 20 行，共 {balance.rows.length} 种地类</p>
                )}
              </div>
            </div>
          </div>
        )}
      </div>
    </section>
  );
}
